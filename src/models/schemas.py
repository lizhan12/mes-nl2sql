"""Pydantic 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class NL2SQLRequest(BaseModel):
    """自然语言查询请求。"""

    query: str = Field(..., min_length=1, description="用户的自然语言查询问题")
    thread_id: str = Field("", description="可选：对话线程ID，用于多轮记忆")
    user_id: str = Field("", description="用户标识，来自前端 localStorage")


class NL2SQLResponse(BaseModel):
    """NL2SQL 响应。"""

    query: str = Field(..., description="原始用户问题")
    sql: str = Field("", description="生成的 SQL（单条模式）")
    sqls: list[str] = Field(default_factory=list, description="生成的所有 SQL（多条模式）")
    safe: bool = Field(True, description="SQL 是否通过安全校验")
    error: str = Field("", description="错误信息")
    tables_used: list[str] = Field(default_factory=list, description="使用的表名列表")
    join_hints: str = Field("", description="JOIN 提示信息")
    execution_result: dict | None = Field(None, description="SQL 执行结果（单条模式）")
    execution_results: list[dict] = Field(default_factory=list, description="多条 SQL 执行结果")
    retry_count: int = Field(0, description="重试次数")
    request_id: str = Field("", description="请求唯一标识")
    knowledge_version: str = Field("", description="命中的运行时知识版本")
    multi_sql: bool = Field(False, description="是否多 SQL 查询")
    sub_queries: list[dict] = Field(default_factory=list, description="子问题列表")


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"


class HarnessFailureLabelRequest(BaseModel):
    """失败案例人工标注请求。"""

    correct_sql: str = Field(..., min_length=1, description="人工确认的正确 SQL")
    note: str = Field("", description="标注备注")
    label_type: str = Field("correct_sql", description="标注类型")


class HarnessCandidateReviewRequest(BaseModel):
    """候选规则审核请求。"""

    action: Literal["approve", "reject"] = Field(..., description="审核动作")
    note: str = Field("", description="审核备注")


class HarnessPublishRequest(BaseModel):
    """发布已审核候选请求。"""

    version: str = Field("", description="发布版本号，可为空")


class SqlPageRequest(BaseModel):
    """分页查询请求。"""

    sql: str = Field(..., min_length=1, description="要执行的 SQL 语句")
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=5, le=1000, description="每页行数")


class SqlPageResponse(BaseModel):
    """分页查询响应。"""

    success: bool
    total_rows: int
    page: int
    page_size: int
    total_pages: int
    columns: list[str]
    rows: list[dict]
    error: str = ""


class HarnessFeedbackRequest(BaseModel):
    """用户点赞/点踩反馈请求。"""

    request_id: str = Field(..., min_length=1, description="NL2SQL 请求的 request_id / thread_id")
    rating: Literal["up", "down"] = Field(..., description="up=点赞, down=点踩")
    reason: str = Field("", description="点踩原因（rating=down 时必填）")


class GraphEdgeCreate(BaseModel):
    """关系图边创建/更新请求。"""

    from_table: str = Field(..., min_length=1, description="源表名")
    to_table: str = Field(..., min_length=1, description="目标表名")
    from_field: str = Field(..., min_length=1, description="源字段")
    to_field: str = Field(..., min_length=1, description="目标字段")
    join_condition: str = Field(..., min_length=1, description="JOIN 条件")
    join_type: str = Field("JOIN", description="JOIN 类型")
    description: str = Field("", description="关系描述")
    confidence: str = Field("high", description="置信度: high/medium/low")
    note: str = Field("", description="备注")

    def to_graph_edge(self):
        from src.services.graph_repository import GraphEdge

        return GraphEdge(
            from_table=self.from_table,
            to_table=self.to_table,
            from_field=self.from_field,
            to_field=self.to_field,
            join_condition=self.join_condition,
            join_type=self.join_type,
            description=self.description,
            confidence=self.confidence,
            note=self.note,
        )


# ── 聊天历史模型 ──


class ChatHistoryItem(BaseModel):
    """会话摘要条目。"""

    thread_id: str
    first_query: str = ""
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ChatHistoryListResponse(BaseModel):
    """用户会话列表响应。"""

    sessions: list[ChatHistoryItem]


class ChatThreadResponse(BaseModel):
    """单个会话线程完整响应。"""

    thread_id: str
    user_id: str
    messages: list[dict]
