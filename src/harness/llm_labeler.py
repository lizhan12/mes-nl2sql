"""LLM 自动标注器。

对失败案例自动生成修正 SQL，并通过多维度评估计算置信度。
低置信度结果自动标记为需要人工审核。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.harness.runner import build_probe_sql, parse_tables
from src.services.db_pool import execution_connection
from src.services.llm import get_llm
from src.security.sql_guard import validate_sql as guard_validate_sql
from src.security.sql_guard import SecurityError

# ── LLM 生成修正 SQL 的 Prompt ───────────────────────────────────

_SQL_GENERATE_SYSTEM = f"""你是 PostgreSQL SQL 专家。用户用自然语言问了一个数据查询问题，之前系统生成的 SQL 执行失败了。

请根据以下信息，生成一条能正确回答用户问题的 SQL 查询。

要求：
- 只输出纯 SQL，不要加任何解释文字、不要加 markdown 代码块标记
- 使用 PostgreSQL 语法
- 表名和字段名必须与提供的信息一致，禁止臆造不存在的列名
- 必要时使用 LEFT JOIN 关联多表
- 添加适当的 WHERE 条件
- 末尾加 LIMIT {settings.default_limit}"""


_SQL_GENERATE_USER = """## 用户问题
{question}

## 之前失败的 SQL
```sql
{failed_sql}
```

## 错误信息
{error_msg}

## 相关表信息
{schema_info}

## JOIN 关系参考
{join_hints}

请输出修正后的完整 SQL："""


# ── LLM 语义评估 Prompt ─────────────────────────────────────────

_SEMANTIC_EVAL_SYSTEM = """你是 SQL 审查专家。请评估一条 SQL 是否准确回答了用户的问题。

按以下维度打分（每项 0-100）：
1. **意图匹配度**：SQL 的查询目标是否与用户问题一致（是否查对了东西）
2. **条件完整性**：用户问题中的过滤条件是否都体现在 SQL 中
3. **输出合理性**：SELECT 的字段是否合理，是否包含用户关心的信息

返回纯 JSON 格式：
{"intent_match": 分数, "condition_completeness": 分数, "output_reasonability": 分数, "overall": 综合分, "comment": "简短评语"}"""

_SEMANTIC_EVAL_USER = """## 用户问题
{question}

## SQL
```sql
{sql}
```

请评估并返回 JSON："""


# ── 维度权重 ─────────────────────────────────────────────────────

# 四个维度的权重（语义一致性权重提高，执行正确性降低，防止答非所问的 SQL 因"能跑通"而高分）
DIMENSION_WEIGHTS = {
    "semantic_consistency": 0.40,  # LLM 语义评估（提高权重，核心维度）
    "structural_integrity": 0.20,  # 结构完整性
    "execution_correctness": 0.30,  # 执行正确性
    "sql_compliance": 0.10,  # SQL 规范度
}

# 置信度阈值
CONFIDENCE_HIGH = 0.85  # >= 此值：自动审批（从 0.70 提高到 0.85，需语义维度也达标）
CONFIDENCE_MEDIUM = 0.50  # >= 此值：待审核（带自动标注备注）
# < CONFIDENCE_MEDIUM：待人工审核

# 语义一致性最低分：低于此值即使总分达标也不自动审批
MIN_SEMANTIC_SCORE = 0.50


@dataclass
class DimensionScores:
    """多维度评估得分。"""

    semantic_consistency: float = 0.0  # 语义一致性 (0-1)
    structural_integrity: float = 0.0  # 结构完整性 (0-1)
    execution_correctness: float = 0.0  # 执行正确性 (0-1)
    sql_compliance: float = 0.0  # SQL 规范度 (0-1)
    details: dict[str, Any] = field(default_factory=dict)  # 详细评估信息

    @property
    def overall_confidence(self) -> float:
        """加权综合置信度。"""
        return round(
            self.semantic_consistency * DIMENSION_WEIGHTS["semantic_consistency"]
            + self.structural_integrity * DIMENSION_WEIGHTS["structural_integrity"]
            + self.execution_correctness * DIMENSION_WEIGHTS["execution_correctness"]
            + self.sql_compliance * DIMENSION_WEIGHTS["sql_compliance"],
            4,
        )

    @property
    def confidence_level(self) -> str:
        """置信度等级：high / medium / low。
        即使总分达标，语义一致性低于 MIN_SEMANTIC_SCORE 也降级到 medium。
        """
        if self.overall_confidence >= CONFIDENCE_HIGH and self.semantic_consistency >= MIN_SEMANTIC_SCORE:
            return "high"
        if self.overall_confidence >= CONFIDENCE_MEDIUM:
            return "medium"
        return "low"

    @property
    def needs_human_review(self) -> bool:
        """是否需要人工审核。
        总分 >= HIGH 且 语义 >= MIN_SEMANTIC_SCORE 才不需要审核。
        """
        return self.overall_confidence < CONFIDENCE_HIGH or self.semantic_consistency < MIN_SEMANTIC_SCORE


def generate_correct_sql(
    question: str,
    failed_sql: str,
    error_msg: str,
    schema_info: str = "",
    join_hints: str = "",
    model: str | None = None,
    temperature: float = 0.1,
) -> str:
    """使用 LLM 为失败案例生成修正后的 SQL。

    Args:
        question: 用户原始问题
        failed_sql: 之前失败的 SQL
        error_msg: 错误信息
        schema_info: 相关表结构信息
        join_hints: JOIN 关系提示
        model: LLM 模型名，默认使用强模型
        temperature: LLM 温度

    Returns:
        生成的修正 SQL 文本（已去除 markdown 包装）
    """
    llm = get_llm(model=model, temperature=temperature)
    user_prompt = _SQL_GENERATE_USER.format(
        question=question,
        failed_sql=failed_sql,
        error_msg=error_msg,
        schema_info=schema_info or "（无额外表结构信息）",
        join_hints=join_hints or "（无额外 JOIN 提示）",
    )
    messages = [
        SystemMessage(content=_SQL_GENERATE_SYSTEM),
        HumanMessage(content=user_prompt),
    ]
    response = llm.invoke(messages)
    sql = _extract_sql_from_text(str(response.content))
    return sql


def _extract_sql_from_text(text: str) -> str:
    """从 LLM 输出中提取纯 SQL 文本（去除 markdown 代码块等）。"""
    text = text.strip()
    # 去掉 ```sql ... ``` 包装
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# ── 多维度评估 ───────────────────────────────────────────────────


def evaluate_sql_multi_dimension(
    question: str,
    sql: str,
    failed_sql: str = "",
    error_msg: str = "",
    table_names: list[str] | None = None,
    db_url: str | None = None,
    model: str | None = None,
) -> DimensionScores:
    """对生成的 SQL 进行多维度评估。

    Args:
        question: 用户原始问题
        sql: 待评估的 SQL
        failed_sql: 之前失败的 SQL
        error_msg: 错误信息
        table_names: 涉及的已知表名列表
        db_url: 数据库连接串（用于实际执行验证）
        model: LLM 模型名

    Returns:
        DimensionScores 含各维度得分和详细信息
    """
    details: dict[str, Any] = {}

    # 维度1：语义一致性（LLM 评估）
    semantic_score, semantic_detail = _evaluate_semantic(question, sql, model)

    # 维度2：结构完整性（规则评估）
    structural_score, structural_detail = _evaluate_structural(sql, failed_sql, error_msg, table_names)

    # 维度3：执行正确性（实际执行）
    exec_score, exec_detail = _evaluate_execution(sql, db_url)

    # 维度4：SQL 规范度
    compliance_score, compliance_detail = _evaluate_compliance(sql)

    details.update(
        {
            "semantic": semantic_detail,
            "structural": structural_detail,
            "execution": exec_detail,
            "compliance": compliance_detail,
        }
    )

    return DimensionScores(
        semantic_consistency=semantic_score,
        structural_integrity=structural_score,
        execution_correctness=exec_score,
        sql_compliance=compliance_score,
        details=details,
    )


def _evaluate_semantic(question: str, sql: str, model: str | None = None) -> tuple[float, dict]:
    """维度1：语义一致性 —— LLM 评估 SQL 是否回答了用户问题。"""
    try:
        llm = get_llm(model=model, temperature=0.0)
        messages = [
            SystemMessage(content=_SEMANTIC_EVAL_SYSTEM),
            HumanMessage(content=_SEMANTIC_EVAL_USER.format(question=question, sql=sql)),
        ]
        response = llm.invoke(messages)
        result = _parse_semantic_json(str(response.content))
    except Exception as exc:
        return 0.0, {"error": str(exc), "raw": str(response.content) if "response" in dir() else ""}

    overall = float(result.get("overall", 0)) / 100.0
    return min(max(overall, 0.0), 1.0), result


def _parse_semantic_json(text: str) -> dict:
    """解析 LLM 返回的语义评估 JSON。"""
    text = text.strip()
    # 尝试提取 JSON 块
    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # 尝试解析整个文本
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "json_parse_failed", "raw": text[:200]}


def _evaluate_structural(
    sql: str, failed_sql: str = "", error_msg: str = "", table_names: list[str] | None = None
) -> tuple[float, dict]:
    """维度2：结构完整性 —— 规则评估 SQL 结构是否合法。

    检查项：
    - 是否有 FROM 子句
    - SELECT 是否不为空
    - 表名是否看起来合理（非明显胡乱拼接）
    - JOIN 语法是否基本正确
    - 是否修复了原错误中提示的问题
    """
    score = 1.0
    checks: list[dict] = []
    sql_upper = sql.upper()

    # 检查1：必须有 FROM
    if "FROM" not in sql_upper:
        score -= 0.3
        checks.append({"check": "has_from", "pass": False, "reason": "缺少 FROM 子句"})
    else:
        checks.append({"check": "has_from", "pass": True})

    # 检查2：必须有 SELECT
    if not sql_upper.strip().startswith("SELECT"):
        score -= 0.3
        checks.append({"check": "starts_with_select", "pass": False, "reason": "SQL 不以 SELECT 开头"})
    else:
        checks.append({"check": "starts_with_select", "pass": True})

    # 检查3：表名合理性（非空，非明显异常字符）
    _, tables, _ = parse_tables(sql)
    if not tables:
        score -= 0.2
        checks.append({"check": "valid_tables", "pass": False, "reason": "无法解析出表名"})
    elif any(len(t) < 4 or " " in t for t in tables):
        score -= 0.1
        checks.append({"check": "valid_tables", "pass": False, "reason": "表名格式可疑"})
    else:
        checks.append({"check": "valid_tables", "pass": True})

    # 检查4：错误中提到的典型问题是否已修复
    if failed_sql and error_msg:
        if _is_error_likely_fixed(failed_sql, sql, error_msg):
            checks.append({"check": "error_fixed", "pass": True})
        else:
            score -= 0.1
            checks.append({"check": "error_fixed", "pass": False, "reason": "可能未完全修复原错误"})

    return min(max(score, 0.0), 1.0), {"checks": checks, "parsed_tables": tables}


def _is_error_likely_fixed(failed_sql: str, new_sql: str, error_msg: str) -> bool:
    """简单启发式判断：新 SQL 是否与旧 SQL 有实质性差异。"""
    # 完全一样则未修复
    if failed_sql.strip().lower() == new_sql.strip().lower():
        return False
    # 列不存在错误：检查新 SQL 是否有不同的列引用
    if "does not exist" in error_msg.lower() or "column" in error_msg.lower():
        return True  # 有差异就认为可能已修复（详细由语义评估覆盖）
    return True


def _evaluate_execution(sql: str, db_url: str | None = None) -> tuple[float, dict]:
    """维度3：执行正确性 —— 在数据库上实际执行 SQL 探针查询。"""
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(build_probe_sql(sql))
            if cur.description:
                columns = [d.name for d in cur.description]
                return 1.0, {"status": "success", "columns": columns, "row_count": cur.rowcount}
            return 0.8, {"status": "success_no_columns", "reason": "执行成功但无结果列"}
    except Exception as exc:
        return 0.0, {"status": "failed", "error": str(exc)[:300]}


def _evaluate_compliance(sql: str) -> tuple[float, dict]:
    """维度4：SQL 规范度 —— 检查安全性和最佳实践。

    检查项：
    - 不含危险操作（DML/DDL）
    - 有 LIMIT 子句
    - 无 SELECT *
    """
    score = 1.0
    checks: list[dict] = []

    # 安全检查
    try:
        safe_sql = guard_validate_sql(sql)
        checks.append({"check": "safe", "pass": True})
    except SecurityError as e:
        score -= 0.4
        checks.append({"check": "safe", "pass": False, "reason": str(e)})

    # LIMIT 检查
    sql_upper = sql.upper()
    if "LIMIT" in sql_upper:
        checks.append({"check": "has_limit", "pass": True})
    else:
        score -= 0.15
        checks.append({"check": "has_limit", "pass": False, "reason": "缺少 LIMIT 子句"})

    # 避免 SELECT *（非严格扣分）
    if re.search(r"\bSELECT\s+\*", sql_upper):
        score -= 0.1
        checks.append({"check": "no_select_star", "pass": False, "reason": "使用了 SELECT *"})
    else:
        checks.append({"check": "no_select_star", "pass": True})

    return min(max(score, 0.0), 1.0), {"checks": checks}


# ── 自动标注入口 ─────────────────────────────────────────────────


@dataclass
class AutoLabelResult:
    """自动标注结果。"""

    corrected_sql: str  # 修正后的 SQL
    confidence: float  # 综合置信度 (0-1)
    dimension_scores: DimensionScores  # 各维度得分
    needs_human_review: bool  # 是否需要人工审核
    candidate_type: str  # 候选类型
    review_note: str = ""  # 审核备注


def auto_label_failure_case(
    question: str,
    failed_sql: str,
    error_msg: str,
    schema_info: str = "",
    join_hints: str = "",
    db_url: str | None = None,
    generate_model: str | None = None,
    eval_model: str | None = None,
) -> AutoLabelResult:
    """对单个失败案例进行 LLM 自动标注 + 多维度评估。

    Args:
        question: 用户原始问题
        failed_sql: 之前失败的 SQL（final_sql）
        error_msg: 错误信息
        schema_info: 相关表结构信息
        join_hints: JOIN 关系提示
        db_url: 数据库连接串（用于执行验证）
        generate_model: 生成 SQL 用的模型
        eval_model: 评估用的模型

    Returns:
        AutoLabelResult
    """
    # 步骤1：LLM 生成修正 SQL
    corrected_sql = generate_correct_sql(
        question=question,
        failed_sql=failed_sql,
        error_msg=error_msg,
        schema_info=schema_info,
        join_hints=join_hints,
        model=generate_model,
    )

    if not corrected_sql.strip():
        return AutoLabelResult(
            corrected_sql="",
            confidence=0.0,
            dimension_scores=DimensionScores(details={"error": "LLM 未生成有效 SQL"}),
            needs_human_review=True,
            candidate_type="llm_labeled_failure",
            review_note="LLM 未生成有效 SQL，需要人工编写",
        )

    # 步骤2：多维度评估
    parsed_main, tables, _ = parse_tables(corrected_sql)
    scores = evaluate_sql_multi_dimension(
        question=question,
        sql=corrected_sql,
        failed_sql=failed_sql,
        error_msg=error_msg,
        table_names=tables,
        db_url=db_url,
        model=eval_model,
    )

    # 步骤3：判断审核等级（语义一致性必须达标才能自动审批）
    confidence = scores.overall_confidence
    needs_review = scores.needs_human_review
    semantic_ok = scores.semantic_consistency >= MIN_SEMANTIC_SCORE

    # 生成审核备注
    if confidence >= CONFIDENCE_HIGH and semantic_ok:
        review_note = f"LLM自动标注，综合置信度 {confidence:.2%}，语义一致性 {scores.semantic_consistency:.2%}（达标），可自动审批。"
        candidate_type = "llm_auto_approved"
    elif confidence >= CONFIDENCE_HIGH and not semantic_ok:
        # 总分达标但语义不达标：降级为待审核
        review_note = (
            f"LLM自动标注，综合置信度 {confidence:.2%}，但语义一致性仅 {scores.semantic_consistency:.2%}"
            f"（<{MIN_SEMANTIC_SCORE:.0%}），SQL 可能未正确回答用户问题，需人工审核。"
        )
        candidate_type = "llm_labeled_failure"
    elif confidence >= CONFIDENCE_MEDIUM:
        dim_info = ", ".join(
            f"{k}={v:.2f}"
            for k, v in {
                "语义": scores.semantic_consistency,
                "结构": scores.structural_integrity,
                "执行": scores.execution_correctness,
                "规范": scores.sql_compliance,
            }.items()
        )
        review_note = f"LLM自动标注，置信度 {confidence:.2%}（中等）。各维度得分: {dim_info}。建议人工快速确认。"
        candidate_type = "llm_labeled_failure"
    else:
        dim_info = ", ".join(
            f"{k}={v:.2f}"
            for k, v in {
                "语义": scores.semantic_consistency,
                "结构": scores.structural_integrity,
                "执行": scores.execution_correctness,
                "规范": scores.sql_compliance,
            }.items()
        )
        review_note = f"LLM自动标注，置信度 {confidence:.2%}（低）。各维度得分: {dim_info}。必须人工编写正确 SQL。"
        candidate_type = "llm_low_confidence_failure"

    return AutoLabelResult(
        corrected_sql=corrected_sql,
        confidence=confidence,
        dimension_scores=scores,
        needs_human_review=needs_review,
        candidate_type=candidate_type,
        review_note=review_note,
    )
