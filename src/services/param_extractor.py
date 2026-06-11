"""参数提取引擎（槽位填充）。

从用户查询中提取动态参数（日期、产线、料号等），供指标 SQL 拼装使用。

策略：
  1. 数据库匹配：产线名、工序名、供应商名、设备名直接和数据库真实数据做匹配
  2. 规则引擎：日期词、料号模式
  3. LLM 兜底：复杂表达用轻量模型提取
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

import jieba
from Levenshtein import distance as levenshtein_distance

from src.services.metric_registry import ParamDef

logger = logging.getLogger(__name__)

# ── 日期词映射 ────────────────────────────────────────────────────
# 改为函数调用时动态计算，避免模块导入后跨天不更新


def _get_date_patterns() -> dict[str, tuple[date, date]]:
    """每次调用时动态计算日期范围，避免模块级常量跨天不更新。"""
    today = date.today()
    first_of_month = date(today.year, today.month, 1)
    last_of_prev_month = first_of_month - timedelta(days=1)
    return {
        "今天": (today, today),
        "昨天": (today - timedelta(days=1), today - timedelta(days=1)),
        "前天": (today - timedelta(days=2), today - timedelta(days=2)),
        "本周": (today - timedelta(days=today.weekday()), today),
        "上周": (
            today - timedelta(days=today.weekday() + 7),
            today - timedelta(days=today.weekday() + 1),
        ),
        "本月": (first_of_month, today),
        "上月": (date(last_of_prev_month.year, last_of_prev_month.month, 1), last_of_prev_month),
        "近7天": (today - timedelta(days=7), today),
        "近30天": (today - timedelta(days=30), today),
        "近一周": (today - timedelta(days=7), today),
        "近一个月": (today - timedelta(days=30), today),
    }

# ISO 日期格式
_ISO_DATE_PATTERN = re.compile(r"(\d{4}[-/.]\d{2}[-/.]\d{2})")
_DATE_RANGE_PATTERN = re.compile(r"(\d{4}[-/.]\d{2}[-/.]\d{2})\s*[到~至]\s*(\d{4}[-/.]\d{2}[-/.]\d{2})")

# 料号模式
_PART_NO_PATTERN = re.compile(r"\b([A-Z]+\d+)\b", re.ASCII)


@dataclass
class SlotResult:
    """单个槽位提取结果。"""

    value: str = ""  # 提取到的值
    confidence: str = ""  # exact / fuzzy / edit_dist / none


class SlotExtractor:
    """槽位提取器 — 数据库驱动的参数匹配。

    核心思想：不靠正则猜，直接和数据库里的真实数据做匹配。
    数据库里有哪些产线/工序/供应商/设备，就匹配哪些。

    参考数据在首次使用时延迟加载，避免启动时阻塞。
    """

    def __init__(self) -> None:
        self._loaded: bool = False
        # 产线：[(code, name), ...]
        self._pdline_names: list[tuple[str, str]] = []
        # 工序：[(name,), ...]
        self._process_names: list[str] = []
        # 供应商：[(name,), ...]
        self._supplier_names: list[str] = []
        # 设备：[(code, name), ...]
        self._equipment_names: list[tuple[str, str]] = []
        # 仓库：[(name,), ...]
        self._warehouse_names: list[str] = []

    def _ensure_loaded(self) -> None:
        """延迟加载参考数据（从执行库查询）。"""
        if self._loaded:
            return
        try:
            from src.services.db_pool import execution_connection

            with execution_connection() as conn, conn.cursor() as cur:
                # 产线
                cur.execute("SELECT pdline_code, pdline_name FROM t_bd_pdline")
                self._pdline_names = [(r[0], r[1]) for r in cur.fetchall()]

                # 工序
                cur.execute("SELECT DISTINCT process_name FROM t_pd_sn_travel WHERE process_name IS NOT NULL")
                self._process_names = [r[0] for r in cur.fetchall()]

                # 供应商
                cur.execute("SELECT supplier_name FROM t_bd_supplier")
                self._supplier_names = [r[0] for r in cur.fetchall()]

                # 设备
                cur.execute("SELECT equipment_code, equipment_name FROM t_ems_equipment")
                self._equipment_names = [(r[0], r[1]) for r in cur.fetchall()]

                # 仓库（从 t_wms_warehouse 取仓库名称，而非 t_wms_stock 的 warehouse_code）
                cur.execute("SELECT DISTINCT warehouse_name FROM t_wms_warehouse WHERE warehouse_name IS NOT NULL")
                self._warehouse_names = [r[0] for r in cur.fetchall()]

            self._loaded = True
            logger.info(
                "SlotExtractor 加载完成: pdline=%d, process=%d, supplier=%d, equipment=%d, warehouse=%d",
                len(self._pdline_names),
                len(self._process_names),
                len(self._supplier_names),
                len(self._equipment_names),
                len(self._warehouse_names),
            )
        except Exception as exc:
            logger.warning("SlotExtractor 加载参考数据失败: %s", exc)

    # ── 提取入口 ─────────────────────────────────────────────────

    def extract(self, slot_type: str, query: str) -> SlotResult:
        """根据槽位类型从查询中提取值。

        Args:
            slot_type: 槽位类型（time/pdline_name/process_name/...）
            query: 用户查询文本

        Returns:
            SlotResult(value, confidence)
        """
        self._ensure_loaded()

        extractors = {
            "time": self._extract_time,
            "pdline_name": self._extract_pdline,
            "process_name": self._extract_process,
            "supplier_name": self._extract_supplier,
            "equipment_name": self._extract_equipment,
            "warehouse_name": self._extract_warehouse,
            "part_no": self._extract_part_no,
        }
        extractor = extractors.get(slot_type)
        if extractor is None:
            return SlotResult()
        return extractor(query)

    # ── 时间提取 ─────────────────────────────────────────────────

    @staticmethod
    def _extract_time(query: str) -> SlotResult:
        """从查询中提取时间范围（每次调用动态计算日期）。"""
        date_patterns = _get_date_patterns()
        today = date.today()

        # 1. 中文日期词
        for term, (start, end) in date_patterns.items():
            if term in query:
                if start == end:
                    return SlotResult(value=start.isoformat(), confidence="exact")
                return SlotResult(value=f"{start.isoformat()} TO {end.isoformat()}", confidence="exact")

        # 2. ISO 日期范围
        range_match = _DATE_RANGE_PATTERN.search(query)
        if range_match:
            start_str = range_match.group(1).replace("/", "-").replace(".", "-")
            end_str = range_match.group(2).replace("/", "-").replace(".", "-")
            return SlotResult(value=f"{start_str} TO {end_str}", confidence="exact")

        # 3. ISO 单个日期
        date_match = _ISO_DATE_PATTERN.search(query)
        if date_match:
            return SlotResult(value=date_match.group(1).replace("/", "-").replace(".", "-"), confidence="exact")

        # 4. 默认近 7 天
        start = today - timedelta(days=7)
        return SlotResult(value=f"{start.isoformat()} TO {today.isoformat()}", confidence="exact")

    # ── 产线提取（数据库匹配）─────────────────────────────────────

    def _extract_pdline(self, query: str) -> SlotResult:
        """三层匹配提取产线名。

        第一层：精确匹配（query 分词后逐 token 匹配数据库产线名）
        第二层：去掉"产线"/"线"后缀再匹配
        第三层：编辑距离（处理错别字）
        """
        tokens = list(jieba.cut(query))

        # 第一层：精确匹配（逐 token，避免 "1" 误匹配 "SMT1线"）
        for code, name in self._pdline_names:
            for token in tokens:
                if token in (name, code):
                    return SlotResult(value=name, confidence="exact")

        # 第二层：去后缀匹配
        for _code, name in self._pdline_names:
            clean_name = name.replace("产线", "").replace("线", "")
            if clean_name and len(clean_name) >= 2:
                for token in tokens:
                    clean_token = token.replace("产线", "").replace("线", "")
                    if clean_token and clean_token == clean_name:
                        return SlotResult(value=name, confidence="fuzzy")

        # 第三层：编辑距离（jieba 分词后逐 token 匹配）
        for token in tokens:
            if len(token) < 2:
                continue
            for _code, name in self._pdline_names:
                if abs(len(token) - len(name)) <= 1 and levenshtein_distance(token, name) <= 1:
                    return SlotResult(value=name, confidence="edit_dist")

        return SlotResult()

    # ── 工序提取（数据库匹配）─────────────────────────────────────

    def _extract_process(self, query: str) -> SlotResult:
        """从查询中提取工序名，优先精确匹配数据库中的工序名。"""
        query_lower = query.lower()

        # 第一层：精确匹配
        for name in self._process_names:
            if name in query or name.lower() in query_lower:
                return SlotResult(value=name, confidence="exact")

        # 第二层：编辑距离
        tokens = list(jieba.cut(query))
        for token in tokens:
            if len(token) < 2:
                continue
            for name in self._process_names:
                if abs(len(token) - len(name)) <= 1 and levenshtein_distance(token, name) <= 1:
                    return SlotResult(value=name, confidence="edit_dist")

        return SlotResult()

    # ── 供应商提取（数据库匹配）───────────────────────────────────

    def _extract_supplier(self, query: str) -> SlotResult:
        """从查询中提取供应商名。"""
        for name in self._supplier_names:
            if name in query:
                return SlotResult(value=name, confidence="exact")

        # 编辑距离兜底
        tokens = list(jieba.cut(query))
        for token in tokens:
            if len(token) < 2:
                continue
            for name in self._supplier_names:
                if abs(len(token) - len(name)) <= 1 and levenshtein_distance(token, name) <= 1:
                    return SlotResult(value=name, confidence="edit_dist")

        return SlotResult()

    # ── 设备提取（数据库匹配）─────────────────────────────────────

    def _extract_equipment(self, query: str) -> SlotResult:
        """从查询中提取设备名。"""
        # 第一层：精确匹配设备名称或编码
        for code, name in self._equipment_names:
            if name in query or code in query:
                return SlotResult(value=name, confidence="exact")

        # 第二层：编辑距离
        tokens = list(jieba.cut(query))
        for token in tokens:
            if len(token) < 2:
                continue
            for _code, name in self._equipment_names:
                if abs(len(token) - len(name)) <= 1 and levenshtein_distance(token, name) <= 1:
                    return SlotResult(value=name, confidence="edit_dist")

        return SlotResult()

    # ── 仓库提取（数据库匹配）─────────────────────────────────────

    def _extract_warehouse(self, query: str) -> SlotResult:
        """从查询中提取仓库名。"""
        for name in self._warehouse_names:
            if name in query:
                return SlotResult(value=name, confidence="exact")

        return SlotResult()

    # ── 料号提取（正则）───────────────────────────────────────────

    @staticmethod
    def _extract_part_no(query: str) -> SlotResult:
        """从查询中提取料号（正则模式匹配）。"""
        match = _PART_NO_PATTERN.search(query)
        if match:
            return SlotResult(value=match.group(1), confidence="exact")
        return SlotResult()


# ── 全局单例 ──────────────────────────────────────────────────────
_extractor: SlotExtractor | None = None


def get_extractor() -> SlotExtractor:
    """获取 SlotExtractor 单例。"""
    global _extractor
    if _extractor is None:
        _extractor = SlotExtractor()
    return _extractor


# ── 公开 API ──────────────────────────────────────────────────────


def extract_params(query: str, param_defs: list[ParamDef]) -> dict[str, str]:
    """从查询文本中提取参数（同步版本，规则引擎）。

    Args:
        query: 用户查询文本
        param_defs: 该指标支持的参数定义列表

    Returns:
        {param_name: value} 字典
    """
    extractor = get_extractor()
    params: dict[str, str] = {}

    for pdef in param_defs:
        result = extractor.extract(pdef.type, query)
        if result.value:
            params[pdef.name] = result.value

    return params


async def extract_params_with_llm(query: str, param_defs: list[ParamDef]) -> dict[str, str]:
    """LLM 辅助提取参数（兜底方案）。

    先用规则引擎 + 数据库匹配提取，提取不到时用 LLM 兜底。
    """
    params = extract_params(query, param_defs)

    # 如果规则引擎已经提取到了所需参数，直接返回
    required_params = [p for p in param_defs if p.required]
    if all(p.name in params for p in required_params):
        return params

    # 用 LLM 提取
    try:
        from src.services.llm import get_llm

        param_desc = "\n".join(f"- {p.name}: {p.description or p.column}" for p in param_defs)
        prompt = f"""从用户查询中提取以下参数，输出 JSON 格式。

可提取的参数：
{param_desc}

用户查询：{query}

仅输出 JSON，格式如：{{"param_name": "value"}}
未提取到的参数不要包含在 JSON 中。"""

        llm = get_llm(model="gpt-4o-mini", temperature=0)
        response = await llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        import json

        try:
            llm_params = json.loads(raw)
            if isinstance(llm_params, dict):
                for k, v in llm_params.items():
                    if v and k not in params:
                        params[k] = str(v)
        except json.JSONDecodeError:
            logger.warning("LLM 参数提取结果解析失败: %s", raw[:200])

    except Exception as exc:
        logger.warning("LLM 参数提取失败: %s", exc)

    return params


def extract_slots_with_confidence(
    query: str, param_defs: list[ParamDef]
) -> list[SlotResult]:
    """提取所有槽位并返回置信度，用于追问判断。

    Returns:
        [SlotResult, ...] 与 param_defs 顺序一致
    """
    extractor = get_extractor()
    return [extractor.extract(pdef.type, query) for pdef in param_defs]
