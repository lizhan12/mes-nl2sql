"""Pydantic 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


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
    candidate_ids: list[int] | None = Field(None, description="指定发布的候选 ID，为空则发布全部 approved")


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


# ── 通用知识库模型 ──


class GenericKnowledgeFieldDef(BaseModel):
    """通用知识库字段定义。"""

    name: str = Field(..., min_length=1, description="字段名")
    value: str = Field("", description="字段值")
    embed: bool = Field(False, description="是否参与 embedding")


class GenericKnowledgeItem(BaseModel):
    """通用知识库条目。"""

    item_id: str = Field("", description="条目 ID，为空时自动生成")
    label: str = Field("", description="显示标签")
    fields: list[GenericKnowledgeFieldDef] = Field(default_factory=list)
    created_at: str = ""


class GenericKnowledgeItemCreate(BaseModel):
    """创建通用知识库条目请求。"""

    kb_name: str = Field(..., min_length=1, description="知识库名称")
    item: GenericKnowledgeItem


class GenericKnowledgeItemUpdate(BaseModel):
    """更新通用知识库条目请求。"""

    label: str = Field("", description="显示标签")
    fields: list[GenericKnowledgeFieldDef] = Field(default_factory=list)


class GenericKBSummary(BaseModel):
    """知识库摘要信息。"""

    kb_name: str
    label: str
    item_count: int
    field_names: list[str]


class GenericKBCreateRequest(BaseModel):
    """创建知识库请求。"""

    kb_name: str = Field(..., min_length=1, description="知识库名称（唯一标识）")
    label: str = Field("", description="显示标签，为空时使用 kb_name")


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
    use_rerank: bool = Field(False, description="是否对结果启用 Rerank 重排（基于配置 RERANK_MODEL）")
    rerank_top_n: int | None = Field(
        None, ge=1, le=50, description="Rerank 后返回前 N 条；为空则使用 settings.rerank_top_n"
    )


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
    type: str = ""
    match_type: str = Field("vector", description="匹配方式: archive_key_exact / vector")
    archive_key: str = Field("", description="结构化归档主键")
    object_entity: str = Field("", description="实体词")
    action_type: str = Field("", description="动作类型")
    domain: str = Field("", description="领域")


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


class StructuralEntities(BaseModel):
    """结构化实体提取结果。"""

    object_entity: str = Field("", description="实体词")
    action_type: str = Field("", description="动作类型")
    domain: str = Field("", description="领域")
    archive_key: str = Field("", description="归档主键")


class KnowledgeSearchResult(BaseModel):
    """知识库检索结果。"""

    query: str
    embedding_model: str = Field(default="", description="当前使用的 Embedding 模型")
    rerank_model: str = Field(default="", description="当前使用的 Rerank 模型")
    structural_entities: StructuralEntities = Field(default_factory=StructuralEntities, description="结构化实体提取结果")
    schema_results: list[SchemaSearchItem] = Field(default_factory=list)
    few_shot_results: list[FewShotSearchItem] = Field(default_factory=list)
    field_results: list[FieldSearchItem] = Field(default_factory=list)
    keyword_tables: list[str] = Field(default_factory=list, description="关键词匹配的表名列表")
    runtime_rule_results: list[RuntimeRuleSearchItem] = Field(default_factory=list, description="运行时规则检索结果")


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
    type: str = Field("manual", description="来源类型: manual / evolved")
    scenario: str = Field("", description="场景")
    question: str = Field("", description="用户问题")
    full_text: str = Field("", description="完整文本")
    enabled: bool = Field(True, description="是否启用")


class FewShotCreateRequest(BaseModel):
    """创建 FewShot 请求。"""

    scenario: str = Field(..., min_length=1, description="场景")
    question: str = Field(..., min_length=1, description="用户问题")
    sql: str = Field(..., min_length=1, description="SQL 语句")
    type: str = Field("manual", description="来源类型: manual / evolved")


class FewShotUpdateRequest(BaseModel):
    """更新 FewShot 请求。"""

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
    enabled: bool = Field(True, description="是否启用")


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


class ToggleEnabledRequest(BaseModel):
    """启用/禁用请求。"""

    enabled: bool = Field(..., description="是否启用")


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


# ── 知识图谱单点查询模型 ──


class TableFieldWithPK(BaseModel):
    """表字段信息（含主键标记）。"""

    name: str
    type: str
    comment: str
    is_pk: bool = False


class TableDDLResponse(BaseModel):
    """表 DDL 响应。"""

    table_name: str
    module: str
    business_meaning: str
    fields: list[TableFieldWithPK]
    ddl: str = ""


class TableFieldsResponse(BaseModel):
    """表字段列表响应。"""

    table_name: str
    fields: list[TableFieldWithPK]
    field_count: int


class NeighborEdge(BaseModel):
    """邻居边信息。"""

    neighbor: str
    from_field: str
    to_field: str
    join_condition: str
    join_type: str
    description: str
    confidence: str


class TableNeighborsResponse(BaseModel):
    """表邻居关系响应。"""

    table_name: str
    outgoing: list[NeighborEdge]
    incoming: list[NeighborEdge]
    total_neighbors: int


class PathEdge(BaseModel):
    """路径中的一条边。"""

    from_table: str = Field(..., alias="from")
    to_table: str = Field(..., alias="to")
    from_field: str
    to_field: str
    join_condition: str
    join_type: str
    description: str

    model_config = {"populate_by_name": True}


class GraphPathResponse(BaseModel):
    """图路径查找响应。"""

    from_table: str
    to_table: str
    path: list[PathEdge]
    depth: int
    found: bool = True
