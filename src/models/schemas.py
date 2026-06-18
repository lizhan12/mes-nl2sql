"""Pydantic 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class NL2SQLRequest(BaseModel):
    """自然语言查询请求。"""

    query: str = Field(..., min_length=1, description="用户的自然语言查询问题")
    thread_id: str = Field("", description="可选：对话线程ID，用于多轮记忆")
    streaming: bool | None = Field(None, description="是否启用 LLM 流式输出，None 则使用全局配置")
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
    force: bool = Field(False, description="强制发布（跳过去重检查）")


class HarnessFeedbackRequest(BaseModel):
    """用户点赞/点踩反馈请求。"""

    request_id: str = Field(
        ...,
        min_length=1,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="NL2SQL 请求的 UUID",
    )
    rating: Literal["up", "down"] = Field(..., description="up=点赞, down=点踩")
    reason: str = Field("", description="点踩原因（rating=down 时必填）")


class GraphEdgeCreate(BaseModel):
    """关系图边创建/更新请求。"""

    from_table: str = Field(..., min_length=1, description="源表名")
    to_table: str = Field(..., min_length=1, description="目标表名")
    from_field: str = Field(..., min_length=1, description="源字段")
    to_field: str = Field(..., min_length=1, description="目标字段")
    join_condition: str = Field("", description="JOIN 条件")
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


# ── 知识库管理模型 ──


class TableFieldInfo(BaseModel):
    """表字段信息。"""

    name: str = Field(..., description="字段名")
    type: str = Field("", description="字段类型，如 varchar(40)")
    comment: str = Field("", description="字段说明")


class TableKnowledgeSummary(BaseModel):
    """表知识库摘要。"""

    table_name: str
    module: str
    business_meaning: str
    field_count: int


class TableKnowledgeDetail(BaseModel):
    """表知识库详情。"""

    table_name: str
    module: str
    business_meaning: str
    fields: list[TableFieldInfo]
    relations: list[str]
    scenarios: list[str]


class TableKnowledgeUpdate(BaseModel):
    """表知识库更新请求。"""

    table_name: str = Field(..., min_length=1, description="可修改的表名")
    module: str = ""
    business_meaning: str = ""
    fields: list[TableFieldInfo] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)


class TableExtractRequest(BaseModel):
    """表结构抽取请求。"""

    raw_text: str = Field(..., min_length=1, description="原始表结构文本（DDL/CREATE TABLE/自然语言描述等）")


class TableExtractResponse(BaseModel):
    """表结构抽取响应。"""

    tables: list[TableKnowledgeUpdate] = Field(default_factory=list, description="抽取到的表定义列表")
    relations: list[GraphEdgeCreate] = Field(default_factory=list, description="抽取到的表间关联关系")


class TableBatchAddRequest(BaseModel):
    """批量添加表请求。"""

    tables: list[TableKnowledgeUpdate] = Field(..., min_length=1, description="要添加的表定义列表")
    relations: list[GraphEdgeCreate] = Field(default_factory=list, description="要添加的表间关联关系")


class TableBatchAddResponse(BaseModel):
    """批量添加表响应。"""

    table_names: list[str] = Field(default_factory=list, description="成功添加的表名列表")
    relation_count: int = Field(0, description="成功添加的关系数量")
    message: str = Field("", description="操作结果消息")


# ── 字段剪裁模型 ──


class FieldPruningResult(BaseModel):
    """字段剪裁结果。"""

    table_name: str
    kept_fields: list[str]  # 保留的字段名列表（按原始顺序）
    all_fields: list[str]  # 全部字段名列表


# ── 知识库检索模型 ──


class KnowledgeSearchRequest(BaseModel):
    """知识库检索请求。"""

    query: str = Field(..., min_length=1, description="查询文本")
    search_types: list[str] = Field(
        default_factory=lambda: ["schema", "few_shot", "fields"],
        description="检索类型列表，可选: schema, few_shot, fields",
    )
    top_k: int = Field(10, ge=1, le=50, description="每种检索返回数量上限")
    similarity_threshold: float = Field(0.55, ge=0.0, le=1.0, description="相似度阈值")


class SchemaSearchItem(BaseModel):
    """表结构检索结果条目。"""

    table_name: str
    module: str
    business_meaning: str
    full_text: str
    score: float


class FewShotSearchItem(BaseModel):
    """SQL 示例检索结果条目。"""

    scenario: str
    question: str
    full_text: str
    score: float


class FieldSearchItem(BaseModel):
    """字段级检索结果条目。"""

    table_name: str
    field_name: str
    type: str
    comment: str
    score: float


class RuntimeRuleSearchItem(BaseModel):
    """运行时规则检索结果条目。"""

    question: str
    normalized_question: str
    preferred_main_table: str
    required_tables: list[str]
    required_joins: list[str]
    source: str
    score: float = 0.0


class EvolvedFewShotSearchItem(BaseModel):
    """进化 few-shot 检索结果条目。"""

    full_text: str
    scenario: str = ""
    question: str = ""
    score: float = 0.0


class KnowledgeSearchResult(BaseModel):
    """知识库检索结果。"""

    query: str
    schema_results: list[SchemaSearchItem] = Field(default_factory=list)
    few_shot_results: list[FewShotSearchItem] = Field(default_factory=list)
    field_results: list[FieldSearchItem] = Field(default_factory=list)
    keyword_tables: list[str] = Field(default_factory=list, description="关键词匹配的表名列表")
    runtime_rule_results: list[RuntimeRuleSearchItem] = Field(default_factory=list, description="运行时规则检索结果")
    evolved_few_shot_results: list[EvolvedFewShotSearchItem] = Field(
        default_factory=list, description="进化 few-shot 检索结果"
    )


class SyncFromNeo4jResponse(BaseModel):
    """从 Neo4j 同步知识库到本地文件的响应。"""

    table_count: int
    few_shot_count: int
    relation_count: int
    message: str
    synced_files: list[str]


# ── FewShot 管理模型 ──


class FewShotItem(BaseModel):
    """FewShot 示例项。"""

    id: str = Field("", description="FewShot ID")
    scenario: str = Field("", description="场景")
    question: str = Field("", description="用户问题")
    full_text: str = Field("", description="完整文本")


class FewShotCreateRequest(BaseModel):
    """创建 FewShot 请求。"""

    scenario: str = Field(..., min_length=1, description="场景")
    question: str = Field(..., min_length=1, description="用户问题")
    sql: str = Field(..., min_length=1, description="SQL 语句")


class FewShotUpdateRequest(BaseModel):
    """更新 FewShot 请求。"""

    scenario: str = Field(..., min_length=1, description="场景")
    question: str = Field(..., min_length=1, description="用户问题")
    sql: str = Field(..., min_length=1, description="SQL 语句")


class EvolvedFewShotItem(BaseModel):
    """EvolvedFewShot 示例项。"""

    id: str = Field("", description="EvolvedFewShot ID")
    scenario: str = Field("", description="场景")
    question: str = Field("", description="用户问题")
    full_text: str = Field("", description="完整文本")


class EvolvedFewShotCreateRequest(BaseModel):
    """创建 EvolvedFewShot 请求。"""

    scenario: str = Field(..., min_length=1, description="场景")
    question: str = Field(..., min_length=1, description="用户问题")
    sql: str = Field(..., min_length=1, description="SQL 语句")


class EvolvedFewShotUpdateRequest(BaseModel):
    """更新 EvolvedFewShot 请求。"""

    scenario: str = Field(..., min_length=1, description="场景")
    question: str = Field(..., min_length=1, description="用户问题")
    sql: str = Field(..., min_length=1, description="SQL 语句")


# ── RuntimeRule 管理模型 ──


class RuntimeRuleItem(BaseModel):
    """RuntimeRule 规则项。"""

    normalized_question: str = Field("", description="归一化问题（唯一键）")
    question: str = Field("", description="用户问题")
    preferred_main_table: str = Field("", description="首选主表")
    required_tables: list[str] = Field(default_factory=list, description="所需表列表")
    required_joins: list[str] = Field(default_factory=list, description="所需 JOIN 列表")
    source: str = Field("", description="来源")


class RuntimeRuleCreateRequest(BaseModel):
    """创建 RuntimeRule 请求。"""

    question: str = Field(..., min_length=1, description="用户问题")
    normalized_question: str = Field(..., min_length=1, description="归一化问题")
    preferred_main_table: str = Field("", description="首选主表")
    required_tables: list[str] = Field(default_factory=list, description="所需表列表")
    required_joins: list[str] = Field(default_factory=list, description="所需 JOIN 列表")
    source: str = Field("manual", description="来源")


class RuntimeRuleUpdateRequest(BaseModel):
    """更新 RuntimeRule 请求。"""

    question: str = Field(..., min_length=1, description="用户问题")
    preferred_main_table: str = Field("", description="首选主表")
    required_tables: list[str] = Field(default_factory=list, description="所需表列表")
    required_joins: list[str] = Field(default_factory=list, description="所需 JOIN 列表")
    source: str = Field("", description="来源")


# ── 去重检查模型 ──


class DedupSimilarItem(BaseModel):
    """去重检测到的相似条目。"""

    key: str = Field("", description="唯一标识（few_shot 为 id，runtime_rule 为 normalized_question）")
    question: str = Field("", description="用户问题")
    score: float = Field(0.0, description="向量相似度分数")
    match_type: str = Field("exact", description="匹配类型: exact / vector")
    existing_item: dict = Field(default_factory=dict, description="已有条目详情")


class DedupCheckResponse(BaseModel):
    """去重检查结果。"""

    has_duplicate: bool = Field(False, description="是否存在重复")
    exact_match: bool = Field(False, description="是否为精确匹配")
    similar_items: list[DedupSimilarItem] = Field(default_factory=list, description="相似条目列表")


class PrePublishCheckResponse(BaseModel):
    """Harness 发布前去重检查结果。"""

    total_candidates: int = Field(0, description="候选总数")
    duplicate_items: list[DedupSimilarItem] = Field(default_factory=list, description="存在重复的候选列表")
    clean_count: int = Field(0, description="无重复的候选数量")


# ── 认证与用户管理模型 ──


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="密码")


class UserInfo(BaseModel):
    """用户信息（对外，不含敏感字段）。"""

    id: int
    username: str
    display_name: str = ""
    role: str = "user"
    created_at: str = ""
    last_login_at: str = ""


class LoginResponse(BaseModel):
    """登录响应。"""

    token: str = Field(..., description="认证 token")
    user: UserInfo = Field(..., description="用户信息")


class UserListResponse(BaseModel):
    """用户列表分页响应。"""

    items: list[UserInfo] = Field(default_factory=list)
    total_rows: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class UserCreateRequest(BaseModel):
    """创建用户请求。"""

    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    display_name: str = Field("", max_length=100, description="显示名")
    role: Literal["admin", "user"] = Field("user", description="角色")


class UserUpdateRequest(BaseModel):
    """更新用户请求。"""

    display_name: str = Field("", max_length=100, description="显示名")
    role: Literal["admin", "user"] = Field("user", description="角色")


class PasswordResetRequest(BaseModel):
    """重置密码请求。"""

    new_password: str = Field(..., min_length=6, max_length=128, description="新密码")
