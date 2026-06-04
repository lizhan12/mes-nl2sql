"""应用配置管理，所有环境变量从 .env 文件加载。"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置，字段名与 .env 中的变量名一一对应。"""

    # ---- LLM ----
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    intent_model: str = "gpt-4o-mini"

    # ---- Embedding ----
    embedding_provider: str = "openai"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_api_key: str = ""

    # ---- Database ----
    # 兼容旧配置：若未显式配置双库，则仍回退到 DATABASE_URL。
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/mes"
    project_database_url: str = ""
    sql_execution_database_url: str = ""

    # ---- Online Harness ----
    enable_online_harness: bool = False
    harness_auto_init_db: bool = True
    harness_runtime_cache_ttl_seconds: int = 60
    harness_request_log_enabled: bool = True

    # ---- Service ----
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- BFS ----
    bfs_max_hops: int = 2
    bfs_max_tables: int = 10

    # ---- Retrieval ----
    retrieval_top_k: int = 8
    few_shot_top_k: int = 3
    retrieval_similarity_threshold: float = 0.55  # 向量检索相似度阈值，低于此值丢弃
    default_limit: int = 500

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def embedding_key(self) -> str:
        """Embedding API key，若未单独设置则复用 LLM key."""
        return self.embedding_api_key or self.openai_api_key

    @property
    def app_database_url(self) -> str:
        """项目内部库连接串，用于向量库和 Harness 等内部表。"""
        return self.project_database_url or self.database_url

    @property
    def execution_database_url(self) -> str:
        """业务 SQL 执行库连接串。"""
        return self.sql_execution_database_url or self.database_url


settings = Settings()
