"""术语归一化引擎。

将用户查询中的业务术语映射到指标 ID，处理歧义术语。
支持精确匹配 + 错别字模糊匹配（jieba 分词 + Levenshtein 编辑距离）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import jieba
from Levenshtein import distance as levenshtein_distance

from src.services.metric_registry import AMBIGUOUS_TERMS, TERM_ALIAS_MAP, get_metric

logger = logging.getLogger(__name__)

# 时间词列表（用于无指标词时的默认兜底）
_TIME_WORDS = [
    "今天", "昨天", "前天", "明天",
    "本周", "这周", "上周", "下周", "本周",
    "本月", "这月", "上月", "上个月", "下月",
    "本年", "今年", "去年", "明年",
    "最近", "近7天", "近30天", "近一周", "近一个月", "最近一周",
    "本周", "当日", "当天",
]


def _has_time_word(query: str) -> bool:
    """检查查询中是否包含时间词。"""
    return any(w in query for w in _TIME_WORDS)


# 实体词列表 — 查询中如果出现这些词（即使在时间词之外），说明不是纯时间查询
# 此时不应触发时间词兜底（回退到 M001），而应走 NL2SQL 或追问
_ENTITY_INDICATORS = [
    "设备", "产线", "哪个", "哪些", "班次", "车间",
    "料号", "工单", "供应商", "仓库",
]


def _fuzzy_match_terms(query: str) -> list[str]:
    """对查询进行分词后的模糊匹配（错别字 tolerant）。

    两层策略：
    1. 全查询串匹配：如果原始查询串与某个别名编辑距离 <= 2 且匹配到唯一指标，直接采纳
       （处理"良品lv"→"良品率"这类拼音替换，jieba 分词后无法逐 token 匹配）
    2. 逐 token 匹配：jieba 分词后，对每个长度 >= 2 的 token 做 Levenshtein 距离 <= 1 的匹配，
       仅当匹配到唯一指标时才采纳（避免短 token 的多指标误匹配）

    Args:
        query: 用户原始查询文本

    Returns:
        匹配到的原始术语列表（来自 TERM_ALIAS_MAP 的 key）
    """
    matched: list[str] = []
    seen: set[str] = set()

    # 第一层：全查询串模糊匹配（阈值 2，处理拼音替换）
    # 额外约束：共享字符数 >= 较短串长度的一半，防止"行不行"误匹配"不良"
    full_query = query.strip().lower()
    full_candidates: list[str] = []
    full_metrics: set[str] = set()
    for alias in TERM_ALIAS_MAP:
        if abs(len(full_query) - len(alias)) <= 1 and levenshtein_distance(full_query, alias) <= 2:
            # 共享字符约束：至少 2/3 的字符共享，防止"行不行"误匹配"不良"
            shared = len(set(full_query) & set(alias))
            min_len = min(len(full_query), len(alias))
            if shared * 3 >= min_len * 2:  # shared >= 2/3 * min_len
                full_candidates.append(alias)
                full_metrics.add(TERM_ALIAS_MAP[alias])
    if len(full_metrics) == 1:
        for alias in full_candidates:
            if alias not in seen:
                seen.add(alias)
                matched.append(alias)
        if matched:
            return matched

    # 第二层：逐 token 模糊匹配（阈值 1，唯一指标约束 + 子串约束）
    tokens = list(jieba.cut(query))
    for token in tokens:
        if len(token) < 2:
            continue
        candidates: list[str] = []
        candidate_metrics: set[str] = set()
        for alias in TERM_ALIAS_MAP:
            if abs(len(token) - len(alias)) <= 1 and levenshtein_distance(token, alias) <= 1 and (token in alias or alias in token):
                # 子串约束：token 必须是 alias 的子串或 alias 是 token 的子串
                # 防止 "产线" 误匹配 "产量"（编辑距离 1 但语义完全不同）
                candidates.append(alias)
                candidate_metrics.add(TERM_ALIAS_MAP[alias])
        # 仅当模糊匹配到唯一指标时才采纳（避免"良品"误匹配"成品"、"不良品"等）
        if len(candidate_metrics) == 1:
            for alias in candidates:
                if alias not in seen:
                    seen.add(alias)
                    matched.append(alias)
    return matched


@dataclass
class NormalizeResult:
    """术语归一化结果。"""

    matched_term: str = ""  # 命中的原始术语
    metric_id: str = ""  # 明确的指标 ID（无歧义时）
    metric_name: str = ""  # 指标名称
    ambiguous: bool = False  # 是否歧义
    candidates: list[dict] = field(default_factory=list)  # 歧义时的候选指标列表
    multi_match: bool = False  # 是否命中多个指标
    multi_metric_ids: list[str] = field(default_factory=list)  # 多指标时的指标 ID 列表


def normalize(query: str) -> NormalizeResult:
    """将用户查询中的术语映射到指标 ID。

    算法：
    1. 按 TERM_ALIAS_MAP 的 key 长度降序，扫描所有匹配项
    2. 检查命中的词是否在 AMBIGUOUS_TERMS 中
    3. 歧义词 → 返回候选指标列表
    4. 多个非歧义词 → 返回 multi_match 模式
    5. 单个明确词 → 返回指标 ID

    Args:
        query: 用户原始查询文本

    Returns:
        NormalizeResult，若无匹配则 metric_id 为空
    """
    query_lower = query.lower()
    # 按 key 长度降序排序，优先匹配长词
    sorted_terms = sorted(TERM_ALIAS_MAP.keys(), key=len, reverse=True)

    # 1. 扫描所有匹配项
    matched_terms: list[str] = []
    for term in sorted_terms:
        if term.lower() in query_lower:
            matched_terms.append(term)

    # 1.5 扫描歧义术语（可能不在 TERM_ALIAS_MAP 中）
    ambiguous_matches: list[str] = []
    for term in AMBIGUOUS_TERMS:
        if term.lower() in query_lower:
            ambiguous_matches.append(term)

    if not matched_terms and not ambiguous_matches:
        # 模糊匹配：jieba 分词 + Levenshtein 编辑距离，处理错别字
        fuzzy_matches = _fuzzy_match_terms(query_lower)
        if fuzzy_matches:
            matched_terms = fuzzy_matches
            logger.info("fuzzy_match: query=%s, matched=%s", query, fuzzy_matches)
        else:
            # 时间词兜底：只有时间词（+疑问词）没有指标词时，默认查产量
            # 但如果查询中包含实体词（如"设备"、"哪个"），说明不是纯时间查询，不触发兜底
            if _has_time_word(query_lower):
                has_entity = any(e in query_lower for e in _ENTITY_INDICATORS)
                if not has_entity:
                    return NormalizeResult(
                        matched_term="产量",
                        metric_id="M001",
                        metric_name="工单日产量",
                    )
            return NormalizeResult()

    # 2. 检查歧义术语
    if ambiguous_matches:
        # 如果命中的术语中存在更具体的词包含了歧义词，则优先使用具体词
        # 例如 "IQC合格率" → 特定匹配 M007，而非 "合格率" 的歧义追问
        matched_term = ambiguous_matches[0]
        for term in matched_terms:
            if matched_term.lower() in term.lower() and len(term) > len(matched_term):
                # 有更具体的术语匹配，跳过歧义
                ambiguous_matches = []
                break

        if ambiguous_matches:
            candidate_ids = AMBIGUOUS_TERMS[matched_term]
            candidates = []
            for mid in candidate_ids:
                m = get_metric(mid)
                if m:
                    candidates.append(
                        {
                            "metric_id": m.metric_id,
                            "name": m.name,
                            "description": m.description,
                            "category": m.category,
                            "status": m.status,
                            "note": m.note,
                        }
                    )
            return NormalizeResult(
                matched_term=matched_term,
                ambiguous=True,
                candidates=candidates,
            )

    if not matched_terms:
        return NormalizeResult()

    # 3. 明确匹配 → 收集所有唯一的指标 ID
    metric_ids: list[str] = []
    seen: set[str] = set()
    for term in matched_terms:
        mid = TERM_ALIAS_MAP[term]
        if mid not in seen:
            seen.add(mid)
            metric_ids.append(mid)

    # 4. 多个指标 → multi_match
    if len(metric_ids) > 1:
        return NormalizeResult(
            multi_match=True,
            multi_metric_ids=metric_ids,
        )

    # 5. 单个指标
    metric_id = metric_ids[0]
    metric = get_metric(metric_id)
    return NormalizeResult(
        matched_term=matched_terms[0],
        metric_id=metric_id,
        metric_name=metric.name if metric else "",
    )


def get_clarification_prompt(matched_term: str, candidates: list[dict]) -> str:
    """生成歧义追问提示文本。"""
    options = "\n".join(
        f"  {i + 1}. {c['name']} ({c['metric_id']}) — {c['description']}" for i, c in enumerate(candidates)
    )
    return f"「{matched_term}」在不同部门有不同口径，请确认你要查的是哪种：\n{options}"
