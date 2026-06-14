"""Harness 数据与运行时知识管理。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.harness.repository import get_online_harness_repository

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _ROOT_DIR / "data"
_HARNESS_DIR = _DATA_DIR / "harness"
_CASES_PATH = _HARNESS_DIR / "cases.json"
_RUNTIME_RULES_PATH = _HARNESS_DIR / "runtime_rules.json"
_EVOLVED_FEW_SHOT_PATH = _HARNESS_DIR / "evolved_few_shot.txt"
_NORMALIZE_PATTERN = re.compile(r"[\s,，。、“”‘’\"'`?？!！:：;；()（）\[\]\-]+")


def normalize_question(question: str) -> str:
    return _NORMALIZE_PATTERN.sub("", question.strip())


def ensure_harness_dir() -> Path:
    _HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    return _HARNESS_DIR


def split_cn_list(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[；;]", raw or "") if item.strip()]


def normalize_join_expr(expr: str, alias_map: dict[str, str]) -> str:
    match = re.search(
        r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)",
        expr,
        re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", " ", expr.strip())

    left_alias, left_col, right_alias, right_col = match.groups()
    left_table = alias_map.get(left_alias, left_alias)
    right_table = alias_map.get(right_alias, right_alias)
    ordered = sorted([f"{left_table}.{left_col}", f"{right_table}.{right_col}"])
    return f"{ordered[0]} = {ordered[1]}"


def parse_expected_joins(raw: str) -> list[str]:
    results: list[str] = []
    for expr in split_cn_list(raw):
        alias_map = {name: name for name in re.findall(r"[a-zA-Z_][\w]*", expr)}
        results.append(normalize_join_expr(expr, alias_map))
    return results


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path: Path, payload: Any) -> None:
    ensure_harness_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_cases_path() -> Path:
    ensure_harness_dir()
    return _CASES_PATH


def get_runtime_rules_path() -> Path:
    ensure_harness_dir()
    return _RUNTIME_RULES_PATH


def get_evolved_few_shot_path() -> Path:
    ensure_harness_dir()
    return _EVOLVED_FEW_SHOT_PATH


def load_cases() -> list[dict[str, Any]]:
    data = load_json_file(_CASES_PATH, [])
    return data if isinstance(data, list) else []


def save_cases(cases: list[dict[str, Any]]) -> None:
    save_json_file(_CASES_PATH, cases)


def load_runtime_rules() -> list[dict[str, Any]]:
    """加载运行时规则，去重并限制数量。

    去重策略：按 normalized_question 去重，保留最后出现的版本（最新）。
    数量限制：超过 settings.max_runtime_rules 时截断尾部。
    """
    if settings.enable_online_harness:
        if getattr(settings, "use_neo4j_for_harness_knowledge", False):
            from src.services.neo4j_graph import load_published_rules

            rules = load_published_rules()
        else:
            knowledge = get_online_harness_repository().load_published_knowledge()
            rules = knowledge.rules
    else:
        data = load_json_file(_RUNTIME_RULES_PATH, [])
        rules = data if isinstance(data, list) else []

    # 按 normalized_question 去重，后出现的覆盖先出现的
    seen: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        key = str(rule.get("normalized_question") or normalize_question(str(rule.get("question", ""))))
        if not key:
            continue
        seen[key] = rule

    deduped = list(seen.values())
    if len(deduped) > settings.max_runtime_rules:
        deduped = deduped[-settings.max_runtime_rules :]
    return deduped


def save_runtime_rules(rules: list[dict[str, Any]]) -> None:
    save_json_file(_RUNTIME_RULES_PATH, rules)


def load_evolved_few_shot_text() -> str:
    """加载进化后的 few-shot 文本，去重并限制条数。

    去重策略：按「用户问题」字段去重，保留最后出现的版本。
    条数限制：超过 settings.max_evolved_few_shot_items 时截断。
    """
    if settings.enable_online_harness:
        if getattr(settings, "use_neo4j_for_harness_knowledge", False):
            from src.services.neo4j_graph import load_published_few_shot_text

            raw = load_published_few_shot_text()
        else:
            knowledge = get_online_harness_repository().load_published_knowledge()
            raw = knowledge.few_shot_text
    elif _EVOLVED_FEW_SHOT_PATH.exists():
        raw = _EVOLVED_FEW_SHOT_PATH.read_text(encoding="utf-8").strip()
    else:
        return ""

    return _dedupe_and_truncate_few_shot(raw, settings.max_evolved_few_shot_items)


def _dedupe_and_truncate_few_shot(text: str, max_items: int) -> str:
    """对 few-shot 文本按 chunk 去重并限制条数。

    每个 chunk 由 "\n---\n" 分隔，按「用户问题：xxx」行提取去重 key。
    """
    if not text or not text.strip():
        return ""

    chunks = [c.strip() for c in text.split("\n---\n") if c.strip()]
    if not chunks:
        return ""

    # 按「用户问题」去重，后出现的覆盖先出现的
    seen: dict[str, str] = {}
    for chunk in chunks:
        key = _extract_few_shot_question(chunk)
        seen[key or chunk] = chunk

    deduped = list(seen.values())
    if len(deduped) > max_items:
        deduped = deduped[:max_items]

    return "\n---\n".join(deduped)


def _extract_few_shot_question(chunk: str) -> str:
    """从 few-shot chunk 中提取「用户问题」行作为去重 key。"""
    for line in chunk.split("\n"):
        line = line.strip()
        if line.startswith("用户问题："):
            return normalize_question(line[len("用户问题：") :].strip())
    return ""


def save_evolved_few_shot_text(content: str) -> None:
    ensure_harness_dir()
    _EVOLVED_FEW_SHOT_PATH.write_text(content.strip(), encoding="utf-8")
