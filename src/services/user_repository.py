"""用户表 PG 持久化仓储。

管理 app_user 表，提供用户 CRUD、登录 token 管理、分页查询。
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext

from src.core.config import settings
from src.services.db_pool import app_connection

logger = logging.getLogger(__name__)

# pbkdf2_sha256 哈希上下文（纯 Python 实现，无外部 C 依赖）
_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def _generate_token() -> str:
    """生成随机 token（43 字符，URL 安全）。"""
    return secrets.token_urlsafe(32)


def _to_user_info(row: dict) -> dict:
    """将数据库行转换为对外用户信息（剔除敏感字段）。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row.get("display_name", ""),
        "role": row.get("role", "user"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else "",
    }


class UserRepository:
    """用户表 PG 仓储（使用 AppPool 连接池）。"""

    def ensure_tables(self) -> None:
        """建表，并在表为空时创建默认 admin 账号。"""
        ddl = """
        CREATE TABLE IF NOT EXISTS app_user (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user',
            api_token TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_app_user_token
            ON app_user (api_token) WHERE api_token <> '';
        CREATE INDEX IF NOT EXISTS idx_app_user_role
            ON app_user (role);
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            # 检查是否已有用户，若无则创建默认 admin
            cur.execute("SELECT COUNT(*) AS cnt FROM app_user")
            count = cur.fetchone()
            if count and count["cnt"] == 0:
                cur.execute(
                    """
                    INSERT INTO app_user (username, password_hash, display_name, role)
                    VALUES (%(username)s, %(password_hash)s, %(display_name)s, %(role)s)
                    """,
                    {
                        "username": settings.default_admin_username,
                        "password_hash": _hash_password(settings.default_admin_password),
                        "display_name": "系统管理员",
                        "role": "admin",
                    },
                )
                logger.info("已创建默认管理员账号: %s", settings.default_admin_username)
            conn.commit()
        logger.info("app_user 表初始化完成")

    def authenticate(self, username: str, password: str) -> dict | None:
        """验证用户名密码，成功则生成并写入 token，返回用户信息。"""
        sql = """
        SELECT id, username, password_hash, display_name, role, created_at, last_login_at
        FROM app_user
        WHERE username = %(username)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"username": username})
            row = cur.fetchone()
            if not row or not _verify_password(password, row["password_hash"]):
                return None

            token = _generate_token()
            cur.execute(
                """
                UPDATE app_user
                SET api_token = %(token)s, last_login_at = NOW()
                WHERE id = %(user_id)s
                """,
                {"token": token, "user_id": row["id"]},
            )
            conn.commit()

        info = _to_user_info(row)
        info["token"] = token
        return info

    def get_user_by_token(self, token: str) -> dict | None:
        """通过 token 查询用户（用于鉴权）。"""
        if not token:
            return None
        sql = """
        SELECT id, username, display_name, role, created_at, last_login_at
        FROM app_user
        WHERE api_token = %(token)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"token": token})
            row = cur.fetchone()
        if not row:
            return None

        # 检查 token 是否过期
        if settings.auth_token_expiry_hours > 0 and row.get("last_login_at"):
            expiry = row["last_login_at"] + timedelta(hours=settings.auth_token_expiry_hours)
            if datetime.now(UTC) > expiry:
                return None

        return _to_user_info(row)

    def clear_token(self, user_id: int) -> None:
        """登出时清除 token。"""
        sql = "UPDATE app_user SET api_token = '' WHERE id = %(user_id)s"
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id})
            conn.commit()

    def get_user_by_id(self, user_id: int) -> dict | None:
        """按 ID 查询用户。"""
        sql = """
        SELECT id, username, display_name, role, created_at, last_login_at
        FROM app_user
        WHERE id = %(user_id)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id})
            row = cur.fetchone()
        return _to_user_info(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        """按用户名查询用户（含 password_hash，用于内部校验）。"""
        sql = """
        SELECT id, username, password_hash, display_name, role, created_at, last_login_at
        FROM app_user
        WHERE username = %(username)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"username": username})
            row = cur.fetchone()
        return dict(row) if row else None

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
        role: str = "user",
    ) -> dict:
        """创建用户。"""
        sql = """
        INSERT INTO app_user (username, password_hash, display_name, role)
        VALUES (%(username)s, %(password_hash)s, %(display_name)s, %(role)s)
        RETURNING id, username, display_name, role, created_at, last_login_at
        """
        params = {
            "username": username,
            "password_hash": _hash_password(password),
            "display_name": display_name,
            "role": role,
        }
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            conn.commit()
        return _to_user_info(row)

    def list_users(self, page: int, page_size: int, search: str = "") -> dict:
        """分页查询用户列表（按创建时间倒序）。

        Returns:
            {"items": [...], "total_rows": int, "page": int, "page_size": int, "total_pages": int}
        """
        offset = (page - 1) * page_size
        where_clause = ""
        params: dict = {"limit": page_size, "offset": offset}
        if search:
            where_clause = "WHERE username ILIKE %(search)s OR display_name ILIKE %(search)s"
            params["search"] = f"%{search}%"

        # 显式列出字段，禁止 SELECT *
        list_sql = f"""
        SELECT id, username, display_name, role, created_at, last_login_at
        FROM app_user
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """
        count_sql = f"SELECT COUNT(*) AS cnt FROM app_user {where_clause}"

        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(count_sql, params)
            count_row = cur.fetchone()
            total_rows = count_row["cnt"] if count_row else 0
            cur.execute(list_sql, params)
            rows = cur.fetchall()

        total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 0
        return {
            "items": [_to_user_info(r) for r in rows],
            "total_rows": total_rows,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def update_user(self, user_id: int, display_name: str, role: str) -> dict | None:
        """更新用户显示名和角色。"""
        sql = """
        UPDATE app_user
        SET display_name = %(display_name)s, role = %(role)s
        WHERE id = %(user_id)s
        RETURNING id, username, display_name, role, created_at, last_login_at
        """
        params = {"user_id": user_id, "display_name": display_name, "role": role}
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            conn.commit()
        return _to_user_info(row) if row else None

    def reset_password(self, user_id: int, new_password: str) -> None:
        """重置用户密码（同时清除现有 token，强制重新登录）。"""
        sql = """
        UPDATE app_user
        SET password_hash = %(password_hash)s, api_token = ''
        WHERE id = %(user_id)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id, "password_hash": _hash_password(new_password)})
            conn.commit()

    def delete_user(self, user_id: int) -> bool:
        """删除用户。"""
        sql = "DELETE FROM app_user WHERE id = %(user_id)s"
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"user_id": user_id})
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted


_user_repo: UserRepository | None = None


def get_user_repository() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = UserRepository()
    return _user_repo
