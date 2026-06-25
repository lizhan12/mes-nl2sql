"""应用生命周期管理：启动时初始化向量库、知识库及各类数据表。

作为公共工具供 main.py 使用，避免入口文件堆积初始化逻辑。
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.core.config import settings
from src.harness.repository import get_online_harness_repository
from src.services.user_repository import get_user_repository
from src.services.vector_store import (
    build_neo4j_few_shot_store,
    build_neo4j_runtime_rule_store,
    build_neo4j_schema_store,
)

logger = logging.getLogger(__name__)

# 强制重建向量库（重新 embedding）：命令行 --rebuild 或环境变量 FORCE_REBUILD
force_rebuild: bool = "--rebuild" in sys.argv or os.environ.get("FORCE_REBUILD", "").lower() in ("1", "true", "yes")

# 全局向量库实例（启动时初始化，供 API 层直接访问）
_schema_store = None
_few_shot_store = None
_runtime_rule_store = None


def get_schema_store():
    """获取 schema 向量库实例。"""
    return _schema_store


def get_few_shot_store():
    """获取 few_shot 向量库实例。"""
    return _few_shot_store


def get_runtime_rule_store():
    """获取 runtime_rule 向量库实例。"""
    return _runtime_rule_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化向量库和知识库基础设施。"""
    global _schema_store, _few_shot_store, _runtime_rule_store

    logger.info("正在初始化向量库（Neo4j）...")
    _schema_store = await build_neo4j_schema_store(force_rebuild=force_rebuild)
    _few_shot_store = await build_neo4j_few_shot_store(force_rebuild=force_rebuild)
    _runtime_rule_store = await build_neo4j_runtime_rule_store(force_rebuild=force_rebuild)
    logger.info("向量库初始化完成")

    if settings.use_neo4j_for_graph:
        from src.services.neo4j_graph import init_neo4j_graph

        await init_neo4j_graph()

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

    yield

    from src.services.db_pool import close_all_pools

    close_all_pools()
    logger.info("服务关闭")
