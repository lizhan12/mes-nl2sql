"""Pydantic 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class NL2SQLRequest(BaseModel):
    """自然语言查询请求。"""

    query: str = Field(..., min_length=1, description="用户的自然语言查询问题")
    thread_id: str = Field("", description="可选：对话线程ID，用于多轮记忆")


class NL2SQLResponse(BaseModel):
    """NL2SQL 响应。"""

    query: str = Field(..., description="原始用户问题")
    sql: str = Field("", description="生成的 SQL")
    safe: bool = Field(True, description="SQL 是否通过安全校验")
    error: str = Field("", description="错误信息")
    tables_used: list[str] = Field(default_factory=list, description="使用的表名列表")
    join_hints: str = Field("", description="JOIN 提示信息")
    execution_result: dict | None = Field(None, description="SQL 执行结果（行数/列名/数据预览/错误信息）")
    retry_count: int = Field(0, description="重试次数")
    request_id: str = Field("", description="请求唯一标识")
    knowledge_version: str = Field("", description="命中的运行时知识版本")


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
