"""聊天历史 PG 持久化仓储。

将会话历史从内存迁移到 PostgreSQL，支持按 user_id 查询历史记录。
"""

from __future__ import annotations

import json
import logging

from src.services.db_pool import app_connection

logger = logging.getLogger(__name__)


class ChatRepository:
    """聊天历史 PG 仓储（使用 AppPool 连接池）。"""

    def ensure_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS chat_history (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            messages JSONB NOT NULL DEFAULT '[]'::jsonb,
            route_type TEXT DEFAULT '',
            row_count INT DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, thread_id)
        );

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'chat_history' AND column_name = 'route_type'
            ) THEN
                ALTER TABLE chat_history ADD COLUMN route_type TEXT DEFAULT '';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'chat_history' AND column_name = 'row_count'
            ) THEN
                ALTER TABLE chat_history ADD COLUMN row_count INT DEFAULT 0;
            END IF;
        END $$;

        CREATE INDEX IF NOT EXISTS idx_chat_history_user
            ON chat_history (user_id, created_at DESC);
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()
        logger.info("chat_history 表初始化完成")

    def save_session(self, user_id: str, thread_id: str, messages: list[dict]) -> None:
        """保存或更新一个会话线程的消息记录。"""
        sql = """
        INSERT INTO chat_history (user_id, thread_id, messages)
        VALUES (%(user_id)s, %(thread_id)s, %(messages)s::jsonb)
        ON CONFLICT (user_id, thread_id) DO UPDATE SET
            messages = EXCLUDED.messages,
            updated_at = NOW()
        """
        params = {
            "user_id": user_id,
            "thread_id": thread_id,
            "messages": json.dumps(messages, ensure_ascii=False, default=str),
        }
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()

    def load_session(self, user_id: str, thread_id: str) -> list[dict] | None:
        """加载指定会话线程的完整消息记录。"""
        sql = """
        SELECT messages FROM chat_history
        WHERE user_id = %(user_id)s AND thread_id = %(thread_id)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id, "thread_id": thread_id})
            row = cur.fetchone()
        if not row:
            return None
        messages = row["messages"]
        if isinstance(messages, str):
            messages = json.loads(messages)
        return messages if isinstance(messages, list) else []

    def list_user_sessions(self, user_id: str, limit: int = 50) -> list[dict]:
        """获取用户的所有会话摘要列表（按更新时间倒序）。"""
        sql = """
        SELECT
            thread_id,
            messages,
            created_at,
            updated_at
        FROM chat_history
        WHERE user_id = %(user_id)s
        ORDER BY updated_at DESC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id, "limit": limit})
            rows = cur.fetchall()

        result: list[dict] = []
        for row in rows:
            messages = row["messages"]
            if isinstance(messages, str):
                messages = json.loads(messages)

            first_query = ""
            if isinstance(messages, list):
                for msg in messages:
                    if isinstance(msg, dict) and msg.get("type") in ("human", "HumanMessage"):
                        content = msg.get("content", "")
                        if content:
                            first_query = content[:100]
                            break

            result.append(
                {
                    "thread_id": row["thread_id"],
                    "first_query": first_query,
                    "message_count": len(messages) if isinstance(messages, list) else 0,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
                }
            )
        return result

    def log_route(self, user_id: str, thread_id: str, route_type: str, row_count: int = 0) -> None:
        """记录路由类型和返回行数，用于审计分析。

        在每次查询完成后调用，更新已有会话的路由信息。
        """
        sql = """
        UPDATE chat_history
        SET route_type = %(route_type)s, row_count = %(row_count)s, updated_at = NOW()
        WHERE user_id = %(user_id)s AND thread_id = %(thread_id)s
        """
        params = {
            "user_id": user_id,
            "thread_id": thread_id,
            "route_type": route_type,
            "row_count": row_count,
        }
        try:
            with app_connection() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
        except Exception:
            logger.warning("记录审计日志失败", exc_info=True)


_chat_repo: ChatRepository | None = None


def get_chat_repository() -> ChatRepository:
    global _chat_repo
    if _chat_repo is None:
        _chat_repo = ChatRepository()
    return _chat_repo
