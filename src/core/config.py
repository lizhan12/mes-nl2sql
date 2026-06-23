"""应用配置管理，环境变量从 .env 和 .env.dev 加载，.env.dev 中的值优先。"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 加载顺序：先加载 .env（基础配置），再加载 .env.dev（开发覆盖），后者优先
_project_root = Path(__file__).resolve().parent.parent.parent  # mes_graph/
load_dotenv(_project_root / ".env", override=False)
load_dotenv(_project_root / ".env.dev", override=True)


class Settings(BaseSettings):
    """全局配置，字段名与 .env 中的变量名一一对应。"""

    # ---- LLM ----
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    intent_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 4096
    intent_max_tokens: int = 1024
    llm_streaming_enabled: bool = True

    # ---- Embedding ----
    embedding_provider: str = "openai"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_api_key: str = ""
    embedding_dimensions: int = 1024  # 向量维度，需与模型匹配（bge-large-zh-v1.5=1024, qwen3-embedding-8b=4096）
    embedding_max_chars: int = 800  # embed_text 最大字符数，需与模型上下文匹配

    # ---- Rerank ----
    rerank_base_url: str = "https://api.siliconflow.cn/v1"  # 硅基流动 rerank 端点
    rerank_api_key: str = ""  # 为空则复用 embedding_key
    rerank_model: str = "Qwen/Qwen3-Reranker-4B"
    rerank_top_n: int = 8  # rerank 后默认返回前 N 条
    rerank_timeout: float = 30.0  # 单次 rerank 请求超时（秒）

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/mes"
    project_database_url: str = ""
    sql_execution_database_url: str = ""

    # ---- Online Harness ----
    enable_online_harness: bool = False
    harness_auto_init_db: bool = True
    harness_request_log_enabled: bool = True

    # ---- Service ----
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- Trace ----
    trace_enabled: bool = True
    trace_max_prompt_preview_chars: int = 500
    trace_max_preview_chars: int = 1500
    trace_max_span_retention_days: int = 30

    # ---- BFS ----
    bfs_max_hops: int = 2
    bfs_max_tables: int = 10

    # ---- Retrieval ----
    retrieval_top_k: int = 8
    few_shot_top_k: int = 3
    retrieval_similarity_threshold: float = 0.55
    runtime_rule_similarity_threshold: float = 0.9
    dedup_similarity_threshold: float = 0.9
    default_limit: int = 500

    # ---- Harness Knowledge Limits ----
    max_runtime_rules: int = 200
    max_evolved_few_shot_items: int = 5
    max_few_shot_total_items: int = 8
    max_schema_context_items: int = 8
    max_prompt_chars: int = 32000

    # ---- Admin API Key ----
    admin_api_key: str = ""

    # ---- Auth ----
    auth_token_expiry_hours: int = 0  # 0 = 永不过期；>0 则检查 last_login_at 是否超时
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    # ---- Neo4j ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    use_neo4j_for_graph: bool = True
    # 禁止从 PG/本地 JSON 自动重建 Neo4j 关系图（保护线上精简后的知识库不被全量覆盖）
    neo4j_graph_auto_init: bool = False

    model_config = {"env_file_encoding": "utf-8"}

    @property
    def embedding_key(self) -> str:
        """Embedding API key，若未单独设置则复用 LLM key."""
        return self.embedding_api_key or self.openai_api_key

    @property
    def rerank_key(self) -> str:
        """Rerank API key，若未单独设置则复用 embedding_key."""
        return self.rerank_api_key or self.embedding_key

    @property
    def app_database_url(self) -> str:
        """项目内部库连接串，用于向量库和 Harness 等内部表。"""
        return self.project_database_url or self.database_url

    @property
    def execution_database_url(self) -> str:
        """业务 SQL 执行库连接串。"""
        return self.sql_execution_database_url or self.database_url


settings = Settings()
