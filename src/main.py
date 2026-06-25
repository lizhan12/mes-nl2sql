"""FastAPI 应用入口 — MES 知识库管理服务。

启动方式：
  uv run uvicorn src.main:app --reload
  uv run python src/main.py

强制重建向量库（重新 embedding）：
  uv run python src/main.py --rebuild
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.auth import router as auth_router
from src.api.entity_lexicon import router as entity_lexicon_router
from src.api.graph import router as graph_router
from src.api.harness import router as harness_router
from src.api.knowledge import router as knowledge_router
from src.api.knowledge_few_shots import router as knowledge_few_shots_router
from src.api.knowledge_generic import router as knowledge_generic_router
from src.api.knowledge_graph import router as knowledge_graph_router
from src.api.knowledge_runtime_rules import router as knowledge_runtime_rules_router
from src.api.users import router as users_router
from src.core.config import settings
from src.models.schemas import HealthResponse
from src.utils.lifespan import lifespan

# ---- 日志配置 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
UI_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"

app = FastAPI(
    title="MES 知识库管理 API",
    description="MES 知识库管理服务：表结构、关系图、FewShot、运行时规则、实体词典、数据飞轮",
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

if UI_DIST_DIR.exists():
    app.mount("/console/assets", StaticFiles(directory=UI_DIST_DIR / "assets"), name="console-assets")

# ---- 注册路由 ----
app.include_router(harness_router)
app.include_router(graph_router)
app.include_router(knowledge_router)
app.include_router(knowledge_few_shots_router)
app.include_router(knowledge_generic_router)
app.include_router(knowledge_graph_router)
app.include_router(knowledge_runtime_rules_router)
app.include_router(entity_lexicon_router)
app.include_router(auth_router)
app.include_router(users_router)


# ---- 系统接口 ----


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查。"""
    return HealthResponse(status="ok")


@app.get("/")
async def root_redirect():
    """默认跳转到控制台。"""
    if UI_DIST_DIR.exists():
        return RedirectResponse(url="/console")
    return RedirectResponse(url="/docs")


@app.get("/console")
async def console_index():
    """返回控制台首页。"""
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

    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=False)
