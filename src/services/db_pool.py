"""数据库连接池管理，显式区分两个 PG 数据源，避免混用。

- AppPool：项目内部库（graph / harness / vector）
- ExecutionPool：业务 SQL 执行库（用户查询的 MES 业务表）
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # 获取连接超时（秒）


def _build_app_pool() -> ConnectionPool:
    url = settings.app_database_url.replace("+asyncpg", "")
    logger.info("创建 AppPool → %s", _mask_url(url))
    return ConnectionPool(
        conninfo=url,
        kwargs={
            "row_factory": dict_row,
            "application_name": "mes_nl2sql_app",
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 30,
            "keepalives_count": 3,
        },
        min_size=1,
        max_size=5,
        timeout=_TIMEOUT,
        max_idle=300,  # 空闲 5 分钟后回收
        max_lifetime=1800,  # 连接最大存活 30 分钟，到期自动关闭
        reconnect_timeout=10,
        check=ConnectionPool.check_connection,  # 每次取连接前验证
        open=True,
    )


def _build_execution_pool() -> ConnectionPool:
    url = settings.execution_database_url.replace("+asyncpg", "")
    logger.info("创建 ExecutionPool → %s", _mask_url(url))
    return ConnectionPool(
        conninfo=url,
        kwargs={
            "row_factory": dict_row,
            "application_name": "mes_nl2sql_exec",
            "options": "-c statement_timeout=30000",  # 30 秒查询超时
            "keepalives": 1,
            "keepalives_idle": 60,
            "keepalives_interval": 30,
            "keepalives_count": 3,
        },
        min_size=1,
        max_size=3,
        timeout=_TIMEOUT,
        max_idle=300,  # 空闲 5 分钟后回收
        max_lifetime=1800,  # 连接最大存活 30 分钟
        reconnect_timeout=10,
        check=ConnectionPool.check_connection,
        open=True,
    )


def _mask_url(url: str) -> str:
    """隐藏密码部分，用于日志输出。"""
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


# ---- 全局池单例 ----

_app_pool: ConnectionPool | None = None
_execution_pool: ConnectionPool | None = None


def get_app_pool() -> ConnectionPool:
    """获取项目内部库连接池（延迟初始化）。"""
    global _app_pool
    if _app_pool is None:
        _app_pool = _build_app_pool()
    return _app_pool


def get_execution_pool() -> ConnectionPool:
    """获取业务 SQL 执行库连接池（延迟初始化）。"""
    global _execution_pool
    if _execution_pool is None:
        _execution_pool = _build_execution_pool()
    return _execution_pool


@contextmanager
def app_connection(**kwargs: object) -> Generator[psycopg.Connection, None, None]:
    """从 AppPool 获取连接，自动归还。

    用法：
        with app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    pool = get_app_pool()
    conn = pool.getconn(**kwargs)  # type: ignore[arg-type]
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def execution_connection(**kwargs: object) -> Generator[psycopg.Connection, None, None]:
    """从 ExecutionPool 获取连接，自动归还。

    用法：
        with execution_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    pool = get_execution_pool()
    conn = pool.getconn(**kwargs)  # type: ignore[arg-type]
    try:
        yield conn
    finally:
        pool.putconn(conn)


def close_all_pools() -> None:
    """关闭所有连接池（用于应用关闭时清理）。"""
    global _app_pool, _execution_pool
    if _app_pool is not None:
        _app_pool.close()
        _app_pool = None
        logger.info("AppPool 已关闭")
    if _execution_pool is not None:
        _execution_pool.close()
        _execution_pool = None
        logger.info("ExecutionPool 已关闭")
