"""Pydantic 请求/响应模型。"""

from pydantic import BaseModel, Field


class NL2SQLRequest(BaseModel):
    """自然语言查询请求。"""

    query: str = Field(..., description="用户的自然语言查询问题", min_length=1)


class NL2SQLResponse(BaseModel):
    """NL2SQL 响应。"""

    query: str = Field(..., description="原始用户问题")
    sql: str = Field("", description="生成的 SQL")
    safe: bool = Field(True, description="SQL 是否通过安全校验")
    error: str = Field("", description="错误信息（如有）")
    tables_used: list[str] = Field(default_factory=list, description="使用的表名")
    join_hints: str = Field("", description="JOIN 提示信息")


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
