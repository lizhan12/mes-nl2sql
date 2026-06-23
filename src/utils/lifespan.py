"""应用生命周期管理：启动时初始化向量库、LangGraph 工作流及各类数据表。

作为公共工具供 main.py 使用，避免入口文件堆积初始化逻辑。
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.core.config import settings
from src.graph.workflow import build_workflow
from src.harness.repository import get_online_harness_repository
from src.services.user_repository import get_user_repository
from src.services.vector_store import (
    build_neo4j_few_shot_store,
    build_neo4j_runtime_rule_store,
    build_neo4j_schema_store,
)
from src.trace.repository import get_trace_repository

logger = logging.getLogger(__name__)

# 强制重建向量库（重新 embedding）：命令行 --rebuild 或环境变量 FORCE_REBUILD
force_rebuild: bool = "--rebuild" in sys.argv or os.environ.get("FORCE_REBUILD", "").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化向量库和 LangGraph 工作流。

    编译后的 LangGraph app 会挂载到 app.state.workflow_app，供工作流路由通过 Request 访问。
    """
    logger.info("正在初始化向量库（Neo4j）...")
    schema_store = await build_neo4j_schema_store(force_rebuild=force_rebuild)
    few_shot_store = await build_neo4j_few_shot_store(force_rebuild=force_rebuild)
    runtime_rule_store = await build_neo4j_runtime_rule_store(force_rebuild=force_rebuild)
    logger.info("向量库初始化完成")

    if settings.use_neo4j_for_graph:
        from src.services.neo4j_graph import init_neo4j_graph

        await init_neo4j_graph()

    logger.info("正在编译 LangGraph 工作流...")
    app.state.workflow_app = build_workflow(schema_store, few_shot_store, runtime_rule_store)
    logger.info("服务就绪，等待请求")

    if settings.enable_online_harness and settings.harness_auto_init_db:
        logger.info("正在初始化线上 Harness 数据表...")
        get_online_harness_repository().ensure_tables()
        logger.info("线上 Harness 数据表初始化完成")

    if settings.enable_online_harness:
        from src.services.neo4j_graph import ensure_harness_knowledge_indexes

        await ensure_harness_knowledge_indexes()
        logger.info("Harness Neo4j 知识索引已就绪")

    logger.info("正在初始化用户数据表...")
    get_user_repository().ensure_tables()
    logger.info("用户数据表初始化完成")

    if settings.trace_enabled:
        logger.info("正在初始化 Trace 追踪数据表...")
        get_trace_repository().ensure_tables()
        logger.info("Trace 追踪数据表初始化完成")

    yield

    from src.services.db_pool import close_all_pools

    close_all_pools()
    logger.info("服务关闭")
