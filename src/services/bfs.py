"""BFS 图扩展服务。

表间的 JOIN 关系图，提供：
  1. bfs_expand: 从种子表出发做 BFS 辐射扩展（域感知 + 代价模型）
  2. find_path_between: 找两个表之间的最短 JOIN 路径
  3. build_join_hints: 将 JOIN 路径转为 LLM 可读的提示文本

图数据加载策略：
  1. 优先从 Neo4j 加载（若配置启用）
  2. 降级到 PG 数据库加载（支持动态编辑、版本感知热更新）
  3. 若 PG 不可用，降级到本地 JSON 文件
"""

import json
import logging
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 域映射 ────────────────────────────────────────────────────────
DOMAIN_MAP: dict[str, str] = {
    "t_pd_": "production",
    "t_qm_": "quality",
    "t_wms_": "warehouse",
    "t_ems_": "equipment",
    "t_bd_": "master",
    "t_bc_": "barcode",
}


def _get_domain(table: str) -> str:
    """根据表名前缀判断所属业务域。"""
    for prefix, domain in DOMAIN_MAP.items():
        if table.startswith(prefix):
            return domain
    return "other"


# ── 图缓存（版本感知）─────────────────────────────────────────────
_GRAPH: dict[str, list[dict]] = {}
_CACHED_VERSION: int = 0
_GRAPH_INITIALIZED: bool = False


def _load_graph_from_json() -> dict[str, list[dict]]:
    """从本地 JSON 文件加载关系图（降级方案）。"""
    graph_path = Path(__file__).parent.parent.parent / "data" / "mes_relation_graph.json"
    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "graph" in data:
        return data["graph"]
    return data


def _get_graph() -> dict[str, list[dict]]:
    """获取当前关系图，数据源优先级：Neo4j > PG > JSON。

    首次调用时加载图数据，后续调用复用缓存（Neo4j 每次请求重新加载以保证最新）。
    """
    global _GRAPH, _CACHED_VERSION, _GRAPH_INITIALIZED

    from src.core.config import settings

    # 优先从 Neo4j 加载
    if getattr(settings, "use_neo4j_for_graph", False):
        try:
            from src.services.neo4j_graph import load_graph_from_neo4j

            _GRAPH = load_graph_from_neo4j()
            if _GRAPH:
                logger.info("从 Neo4j 加载关系图，表: %d", len(_GRAPH))
                return _GRAPH
        except Exception as e:
            logger.warning("Neo4j 不可用，降级到 PG/JSON: %s", e)

    # 降级：从 PG 加载
    try:
        from src.services.graph_repository import get_graph_repository

        repo = get_graph_repository()
        if not _GRAPH_INITIALIZED:
            repo.ensure_tables()
            _GRAPH_INITIALIZED = True

        current_version = repo.get_version()
        if current_version != _CACHED_VERSION or not _GRAPH:
            _GRAPH = repo.load_full_graph()
            _CACHED_VERSION = current_version
            if _GRAPH:
                logger.info("从 PG 加载关系图，版本: %d, 表: %d", current_version, len(_GRAPH))
            else:
                logger.warning("PG 中关系图为空，降级到 JSON 文件")
                _GRAPH = _load_graph_from_json()
    except Exception:
        if not _GRAPH:
            _GRAPH = _load_graph_from_json()
            logger.info("PG 不可用，从 JSON 文件加载关系图，表: %d", len(_GRAPH))

    return _GRAPH


# ── BFS 扩展 ─────────────────────────────────────────────────────
def bfs_expand(
    seed_tables: list[str],
    max_hops: int = 2,
    max_tables: int = 10,
    exclude_prefixes: list[str] | None = None,
    max_cost: float | None = None,
    intent_domains: list[str] | None = None,
) -> dict:
    """从种子表出发做 BFS 辐射扩展，返回相关表集合及 JOIN 路径。

    支持两种模式：
      - 旧模式（max_hops）：按跳数扩展，向后兼容
      - 新模式（max_cost）：按域感知代价扩展，跨域跳转代价更高

    代价模型：
      - master 域 (t_bd_): cost=0.5（基础数据几乎必然需要）
      - 同域跳转: cost=1
      - 跨域跳转: cost=2

    置信度过滤：
      - confidence="low": 跳过
      - confidence="medium": 若提供了 intent_domains 且邻居域不在其中且非 master，跳过

    Args:
        seed_tables: 起始表名列表
        max_hops: 最大扩展跳数（仅 max_cost 未设置时生效）
        max_tables: 最大返回表数量
        exclude_prefixes: 需要过滤的表名前缀（如系统表）
        max_cost: 最大扩展代价（设置后替代 max_hops，启用域感知代价模型）
        intent_domains: 意图涉及的业务域列表（如 ["production", "quality"]）

    Returns:
        {"tables": [...], "join_paths": [{"from":..., "to":..., ...}, ...], "warning": str}
    """
    if exclude_prefixes is None:
        exclude_prefixes = ["t_basic_", "t_demo_", "t_dev_", "t_lb_", "t_print_"]

    intent_domain_set: set[str] = set(intent_domains) if intent_domains else set()

    # ── 代价模式 ──
    if max_cost is not None:
        return _bfs_expand_cost(seed_tables, max_cost, max_tables, exclude_prefixes, intent_domain_set)

    # ── 跳数模式（向后兼容）──
    visited: set[str] = set(seed_tables)
    queue: deque[tuple[str, int]] = deque((t, 0) for t in seed_tables)
    join_paths: list[dict] = []

    while queue and len(visited) < max_tables:
        current, hop = queue.popleft()
        if hop >= max_hops:
            continue

        neighbors = _get_graph().get(current, [])
        for edge in neighbors:
            neighbor = edge["to"]
            if neighbor in visited:
                continue
            if len(visited) >= max_tables:
                break
            if any(neighbor.startswith(p) for p in exclude_prefixes):
                continue

            visited.add(neighbor)
            queue.append((neighbor, hop + 1))
            join_paths.append(
                {
                    "from": current,
                    "to": neighbor,
                    "join_on": edge["join"],
                    "desc": edge["desc"],
                    "hop": hop + 1,
                }
            )

    return {"tables": list(visited), "join_paths": join_paths, "warning": ""}


def _bfs_expand_cost(
    seed_tables: list[str],
    max_cost: float,
    max_tables: int,
    exclude_prefixes: list[str],
    intent_domains: set[str],
) -> dict:
    """域感知代价模型 BFS 扩展。"""
    visited: dict[str, float] = dict.fromkeys(seed_tables, 0.0)
    # (当前表, 累计代价)
    queue: deque[tuple[str, float]] = deque((t, 0.0) for t in seed_tables)
    join_paths: list[dict] = []

    while queue and len(visited) < max_tables:
        current, cost = queue.popleft()
        current_domain = _get_domain(current)

        for edge in _get_graph().get(current, []):
            neighbor = edge["to"]
            if neighbor in visited:
                continue
            if len(visited) >= max_tables:
                break
            if any(neighbor.startswith(p) for p in exclude_prefixes):
                continue

            neighbor_domain = _get_domain(neighbor)

            # 置信度过滤
            confidence = edge.get("confidence", "high")
            if confidence == "low":
                continue
            if confidence == "medium" and intent_domains:
                if neighbor_domain not in intent_domains and neighbor_domain != "master":
                    continue

            # 计算跳转代价
            if neighbor_domain == "master":
                hop_cost = 0.5
            elif neighbor_domain == current_domain:
                hop_cost = 1
            else:
                hop_cost = 2

            new_cost = cost + hop_cost
            if new_cost > max_cost:
                continue

            visited[neighbor] = new_cost
            queue.append((neighbor, new_cost))
            join_paths.append(
                {
                    "from": current,
                    "to": neighbor,
                    "join_on": edge["join"],
                    "join_type": edge.get("join_type", "JOIN"),
                    "desc": edge["desc"],
                    "confidence": confidence,
                    "note": edge.get("note", ""),
                }
            )

    # 生成警告信息
    warning = ""
    medium_joins = [jp for jp in join_paths if jp.get("confidence") == "medium"]
    if medium_joins:
        paths_str = ", ".join(f"{jp['from']}→{jp['to']}" for jp in medium_joins)
        warning = f"以下{len(medium_joins)}条JOIN路径置信度为medium，结果请人工核实：{paths_str}"

    return {"tables": list(visited.keys()), "join_paths": join_paths, "warning": warning}


# ── 路径查找 ─────────────────────────────────────────────────────
def find_path_between(
    table_a: str,
    table_b: str,
    max_depth: int = 4,
) -> list[str] | None:
    """BFS 找两个表之间的最短 JOIN 路径。

    适用场景：用户问题提到了首尾两个表（如"工单用的设备"），
    但中间表（如产线→工作站）没有明确提及，需要推断出完整 JOIN 链。

    Args:
        table_a: 起始表名
        table_b: 目标表名
        max_depth: 最大搜索深度（路径中最多经过几张表）

    Returns:
        [table_a, mid1, mid2, ..., table_b] 或 None
    """
    if table_a == table_b:
        return [table_a]

    if table_a not in _get_graph() or table_b not in _get_graph():
        return None

    queue: deque[tuple[str, list[str]]] = deque([(table_a, [table_a])])
    visited: set[str] = {table_a}

    while queue:
        node, path = queue.popleft()
        if len(path) > max_depth + 1:
            continue

        for edge in _get_graph().get(node, []):
            neighbor = edge["to"]
            if neighbor == table_b:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return None


# ── JOIN 提示文本 ────────────────────────────────────────────────
def build_path_join_hints(path: list[str]) -> list[dict]:
    """根据路径中的表序列，从关系图中查找对应的 JOIN 边信息。

    Args:
        path: 表名路径，如 ["t_pd_wo", "t_bd_pdline", "t_bd_terminal", "t_ems_equipment"]

    Returns:
        [{"from":..., "to":..., "join_on":..., "desc":..., "hop":...}, ...]
    """
    hints: list[dict] = []
    for i in range(len(path) - 1):
        src = path[i]
        dst = path[i + 1]
        for edge in _get_graph().get(src, []):
            if edge["to"] == dst:
                hints.append(
                    {
                        "from": src,
                        "to": dst,
                        "join_on": edge["join"],
                        "desc": edge["desc"],
                        "hop": i + 1,
                    }
                )
                break
        else:
            # 正向没找到，尝试反向（图是双向的，但边可能只定义在 src 端）
            for edge in _get_graph().get(dst, []):
                if edge["to"] == src:
                    hints.append(
                        {
                            "from": dst,
                            "to": src,
                            "join_on": edge["join"],
                            "desc": edge["desc"],
                            "hop": i + 1,
                        }
                    )
                    break

    return hints


def build_join_hints(join_paths: list[dict]) -> str:
    """将 JOIN 路径列表转换为 LLM 可读的提示文本。

    - 跳过 desc 中包含"反向"的边
    - 对有 note 字段且非空的边添加 ⚠️ 提示
    - 使用 join_type 字段（默认 JOIN）替代硬编码
    """
    lines: list[str] = []
    for jp in join_paths:
        # 跳过反向边
        if "反向" in jp.get("desc", ""):
            continue

        desc = jp.get("desc", "")
        join_type = jp.get("join_type", "JOIN")
        join_on = jp["join_on"]
        to_table = jp["to"]
        note = jp.get("note", "")

        lines.append(f"-- {desc}")
        warn_suffix = f"  -- ⚠️ {note}" if note else ""
        lines.append(f"{join_type} {to_table} ON {join_on}{warn_suffix}")

    return "\n".join(lines)


def build_chain_join_hints(path: list[str]) -> str:
    """将路径转换为带编号的 JOIN 链提示文本，强调 JOIN 顺序。

    与 build_join_hints 的区别：这里会标注步骤序号，让 LLM 明确知道 JOIN 的先后顺序。
    """
    hints = build_path_join_hints(path)
    if not hints:
        return ""

    lines = ["-- [跨表路径] 以下 JOIN 按顺序连接，形成完整链路："]
    for i, jp in enumerate(hints):
        lines.append(f"-- 步骤{i + 1}: {jp['desc']}")
        lines.append(f"JOIN {jp['to']} ON {jp['join_on']}")
    return "\n".join(lines)
