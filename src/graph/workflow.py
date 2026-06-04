"""LangGraph 工作流组装。

Pipeline:
  意图理解 → 并行检索 → BFS扩展 → Schema组装 → SQL生成 → 安全校验 → SQL执行与修复
"""

import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph.nodes import (
    init_stores,
    node_1_intent_understanding,
    node_2_parallel_retrieval,
    node_3_bfs_expand,
    node_4_schema_assembly,
    node_5_sql_generation,
    node_6_safety_check,
    node_7_execute_and_repair,
)
from src.graph.state import GraphState

_MAX_RETRIES = 3


def build_workflow(schema_store, few_shot_store):
    """构建并编译 LangGraph 工作流。

    Args:
        schema_store: 表结构 PGVector store
        few_shot_store: SQL 示例 PGVector store
    """
    init_stores(schema_store, few_shot_store)

    workflow = StateGraph(GraphState)

    # 添加节点
    workflow.add_node("intent", node_1_intent_understanding)
    workflow.add_node("retrieval", node_2_parallel_retrieval)
    workflow.add_node("bfs", node_3_bfs_expand)
    workflow.add_node("schema", node_4_schema_assembly)
    workflow.add_node("sql_gen", node_5_sql_generation)
    workflow.add_node("safety", node_6_safety_check)
    workflow.add_node("execute", node_7_execute_and_repair)

    # 定义边
    workflow.set_entry_point("intent")
    workflow.add_edge("intent", "retrieval")
    workflow.add_edge("retrieval", "bfs")
    workflow.add_edge("bfs", "schema")
    workflow.add_edge("schema", "sql_gen")
    # workflow.add_edge("sql_gen", END)
    workflow.add_edge("sql_gen", "safety")
    workflow.add_edge("safety", "execute")

    # 条件边：execute 节点根据结果决定是结束还是重试
    workflow.add_conditional_edges(
        "execute",
        _route_after_execute,
        {
            "end": END,
            "retry": "execute",  # 回到自己重试
        },
    )

    return workflow.compile(checkpointer=MemorySaver())


def _route_after_execute(state: GraphState) -> str:
    """判断 execute 节点后是结束还是重试。"""
    retry_count = state.get("retry_count", 0)
    multi_sql = state.get("multi_sql", False)

    # 多 SQL 模式不循环重试
    if multi_sql:
        return "end"

    # 不安全或空 SQL → 直接结束
    final_sqls = state.get("final_sqls", [])
    if not state.get("safe", False) or not final_sqls:
        return "end"

    # 解析执行结果
    try:
        results = json.loads(state.get("execution_results", "[{}]"))
    except (json.JSONDecodeError, TypeError):
        results = [{}]

    # 执行成功 → 结束
    if results and results[0].get("success"):
        return "end"

    # 执行失败但还有重试次数 → 重试（retry_count 已经在 node_7 中 +1 了）
    if retry_count < _MAX_RETRIES:
        return "retry"

    # 已达最大重试次数 → 结束
    return "end"
