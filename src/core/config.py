"""应用配置管理，环境变量从 .env 和 .env.dev 加载，.env.dev 中的值优先。"""

from pathlib import Path

from pydantic_settings import BaseSettings

_project_root = Path(__file__).resolve().parent.parent.parent  # mes_graph/


class Settings(BaseSettings):
    """全局配置，字段名与 .env 中的变量名一一对应。"""

    # ---- LLM ----
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    intent_model: str = "gpt-4o-mini"
    llm_request_timeout: int = 120  # LLM 调用超时（秒），超时后抛出 ReadTimeout 异常
    llm_streaming_enabled: bool = False

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
    admin_api_key: str = ""  # 管理员 API Key，用于 /admin/* 和 /api/graph/* 鉴权，为空则跳过校验

    # ---- Rate Limit ----
    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 30  # 每个时间窗口内最大请求数
    rate_limit_window_seconds: int = 60  # 限流时间窗口（秒）

    # ---- Trace ----
    trace_enabled: bool = True
    trace_max_prompt_preview_chars: int = 500
    trace_max_span_retention_days: int = 30
    trace_max_preview_chars: int = 20000

    # ---- BFS ----
    bfs_max_hops: int = 2
    bfs_max_tables: int = 10

    # ---- Retrieval ----
    retrieval_top_k: int = 8
    few_shot_top_k: int = 3
    retrieval_similarity_threshold: float = 0.55  # 向量检索相似度阈值，低于此值丢弃
    default_limit: int = 500
    sql_max_rows: int = 2000  # SQL 安全校验兜底上限，无 LIMIT 时自动追加

    # ---- Harness Knowledge Limits ----
    max_runtime_rules: int = 200  # 运行时规则最大加载条数
    max_evolved_few_shot_items: int = 5  # 进化 few-shot 最多注入条数（每条约 350-450 字符）
    max_few_shot_total_items: int = 12  # few_shot_docs 总条数上限（基础 + 进化）
    max_schema_context_items: int = 12  # schema_context 表结构 chunk 条数上限（每条约 420 字符）
    max_prompt_chars: int = 48000  # SQL 生成 prompt 总字符硬上限（最终兜底）

    # ---- Neo4j ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    use_neo4j_for_graph: bool = True
    use_neo4j_for_harness_knowledge: bool = True

    model_config = {
        # env_file 列表中后面的文件优先级更高：.env.dev > .env
        "env_file": [
            str(_project_root / ".env"),
            str(_project_root / ".env.dev"),
        ],
        "env_file_encoding": "utf-8",
    }

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
