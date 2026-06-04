"""LangGraph 状态定义。

工作流变量流转：
  query → intent_json → schema_docs + few_shot_docs
       → expanded_tables + join_hints → schema_context
       → generated_sql → final_sql → (执行+修复重试) → execution_result
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class GraphState(TypedDict):
    """LangGraph 全局状态，所有节点共享。"""

    # ---- 输入 ----
    query: str  # 用户原始问题

    # ---- 节点1 输出 ----
    intent_json: str  # 意图理解 JSON
    query_guidance: str  # 规则层补充的查询约束

    # ---- 节点2 输出 ----
    schema_docs: str  # 知识库检索到的表结构文档（换行分隔）
    few_shot_docs: str  # 检索到的 SQL 示例

    # ---- 节点3 输出 ----
    expanded_tables: str  # BFS 扩展后的表名列表（逗号分隔）
    join_hints: str  # JOIN 提示文本
    warning: str  # BFS 扩展产生的警告信息（如跨域置信度低）

    # ---- 节点4 输出 ----
    schema_context: str  # 精简后的 DDL 上下文

    # ---- 节点5 输出 ----
    generated_sql: str  # LLM 生成的 SQL

    # ---- 节点6 输出 ----
    final_sql: str  # 安全校验后的最终 SQL
    safe: bool  # 是否通过安全校验
    error: str  # 错误信息

    # ---- 节点7 输出 ----
    execution_result: str  # SQL 执行结果（JSON 字符串：行数/列名/数据预览/错误信息）
    retry_count: int  # 当前重试次数（0=首次执行）

    # ---- 元信息 ----
    messages: Annotated[list, add_messages]  # 对话历史（可选扩展用）
