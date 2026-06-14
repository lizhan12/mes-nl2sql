"""FastAPI 应用入口。

启动方式：
  uv run uvicorn src.main:app --reload
  uv run python src/main.py

强制重建向量库（重新 embedding）：
  uv run python src/main.py --rebuild
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.chat import router as chat_router
from src.api.chat import set_langgraph_app as set_chat_app
from src.api.execute import router as execute_router
from src.api.graph import router as graph_router
from src.api.harness import router as harness_router
from src.api.metrics import router as metrics_router
from src.api.nl2sql import router as nl2sql_router
from src.api.nl2sql import set_langgraph_app as set_nl2sql_app
from src.api.rate_limit import RateLimitMiddleware
from src.api.trace import router as trace_router
from src.core.config import settings
from src.graph.workflow import build_workflow
from src.harness.repository import get_online_harness_repository
from src.models.schemas import HealthResponse
from src.services.chat_repository import get_chat_repository
from src.services.vector_store import build_neo4j_few_shot_store, build_neo4j_schema_store
from src.trace.repository import get_trace_repository

# ---- 日志配置 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
UI_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"

# ---- 全局变量 ----
_app = None  # 编译后的 LangGraph app
_force_rebuild = "--rebuild" in sys.argv or os.environ.get("FORCE_REBUILD", "").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化向量库和 LangGraph 工作流。"""
    global _app

    logger.info("正在初始化向量库（Neo4j）...")
    schema_store = build_neo4j_schema_store(force_rebuild=_force_rebuild)
    few_shot_store = build_neo4j_few_shot_store(force_rebuild=_force_rebuild)
    logger.info("向量库初始化完成")

    logger.info("正在编译 LangGraph 工作流...")
    _app = build_workflow(schema_store, few_shot_store)
    logger.info("服务就绪，等待请求")

    # 注入到路由模块
    set_chat_app(_app)
    set_nl2sql_app(_app)

    if settings.use_neo4j_for_graph:
        logger.info("正在初始化 Neo4j 关系图...")
        from src.services.neo4j_graph import init_neo4j_graph

        init_neo4j_graph()
        logger.info("Neo4j 关系图初始化完成")

    if settings.enable_online_harness and settings.harness_auto_init_db:
        logger.info("正在初始化线上 Harness 数据表...")
        get_online_harness_repository().ensure_tables()
        logger.info("线上 Harness 数据表初始化完成")

    if settings.enable_online_harness and getattr(settings, "use_neo4j_for_harness_knowledge", False):
        logger.info("正在初始化 Neo4j Harness 知识索引...")
        from src.services.neo4j_graph import ensure_harness_knowledge_indexes

        ensure_harness_knowledge_indexes()
        logger.info("Neo4j Harness 知识索引初始化完成")

    logger.info("正在初始化聊天历史数据表...")
    get_chat_repository().ensure_tables()
    logger.info("聊天历史数据表初始化完成")

    if settings.trace_enabled:
        logger.info("正在初始化 Trace 追踪数据表...")
        get_trace_repository().ensure_tables()
        logger.info("Trace 追踪数据表初始化完成")

    yield
    from src.services.db_pool import close_all_pools

    close_all_pools()
    logger.info("服务关闭")


# ── 管理员鉴权依赖 ─────────────────────────────────────────────────


async def require_admin(x_admin_key: str = Header(default="", alias="X-Admin-Key")) -> str:
    """管理员 API Key 校验。

    通过 Header X-Admin-Key 传入。若未配置 admin_api_key 则跳过校验。
    """
    if not settings.admin_api_key:
        return ""  # 未配置密钥时跳过校验
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


app = FastAPI(
    title="MES NL2SQL API",
    description="MES 自然语言转 SQL 查询服务，基于 LangGraph",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求限流（CORS 之后、路由之前）
app.add_middleware(RateLimitMiddleware)

# ── 注册模块化路由 ─────────────────────────────────────────────────
app.include_router(nl2sql_router)
app.include_router(chat_router)
app.include_router(harness_router)
app.include_router(graph_router)
app.include_router(metrics_router)
app.include_router(execute_router)
app.include_router(trace_router)

# ── 管理员鉴权 Middleware ────────────────────────────────────────────
# 保护 /admin/*、/api/graph/*(写操作)、/api/trace/* 路由
_ADMIN_PROTECTED_PREFIXES = ("/admin/",)
_TRACE_PROTECTED_PREFIXES = ("/api/trace/",)
_GRAPH_WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path

    needs_admin = False
    if path.startswith(_ADMIN_PROTECTED_PREFIXES) or path.startswith(_TRACE_PROTECTED_PREFIXES) or path.startswith("/api/graph/") and request.method in _GRAPH_WRITE_METHODS:
        needs_admin = True

    if needs_admin and settings.admin_api_key:
        key = request.headers.get("X-Admin-Key", "")
        if key != settings.admin_api_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: invalid or missing X-Admin-Key"},
            )

    return await call_next(request)


if UI_DIST_DIR.exists():
    app.mount("/console/assets", StaticFiles(directory=UI_DIST_DIR / "assets"), name="console-assets")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查。"""
    return HealthResponse(status="ok")


@app.get("/")
async def root_redirect():
    """默认跳转到测试页面。"""
    if UI_DIST_DIR.exists():
        return RedirectResponse(url="/console")
    return RedirectResponse(url="/docs")


@app.get("/console")
async def console_index():
    """返回测试页面首页。"""
    if not UI_DIST_DIR.exists():
        return {"error": "前端页面尚未构建，请先执行 web 构建"}
    return FileResponse(UI_DIST_DIR / "index.html")


@app.get("/console/{full_path:path}")
async def console_spa_fallback(full_path: str):
    """SPA 回退到 index.html。"""
    target = UI_DIST_DIR / full_path
    if UI_DIST_DIR.exists() and target.exists() and target.is_file():
        return FileResponse(target)
    if not UI_DIST_DIR.exists():
        return {"error": "前端页面尚未构建，请先执行 web 构建"}
    return FileResponse(UI_DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=True)
