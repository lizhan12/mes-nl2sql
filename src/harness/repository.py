"""线上 Harness 数据库存储。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import psycopg.errors

from src.services.db_pool import app_connection

logger = logging.getLogger(__name__)


def _safe_add_column(cur: Any, ddl: str) -> None:
    """安全执行 ADD COLUMN，使用 savepoint 隔离，失败不影响外层事务。"""
    savepoint = f"sp_{id(ddl)}"
    try:
        cur.execute(f"SAVEPOINT {savepoint}")
        cur.execute(ddl)
        cur.execute(f"RELEASE SAVEPOINT {savepoint}")
    except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        logger.warning("ADD COLUMN 跳过（锁冲突）: %s", ddl[:80])


class OnlineHarnessRepository:
    """线上 Harness 仓储（使用 AppPool 连接池）。"""

    def ensure_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS nl2sql_request_log (
            id BIGSERIAL PRIMARY KEY,
            request_id UUID NOT NULL UNIQUE,
            query_text TEXT NOT NULL,
            generated_sql TEXT NOT NULL DEFAULT '',
            final_sql TEXT NOT NULL DEFAULT '',
            safe BOOLEAN NOT NULL DEFAULT FALSE,
            error_text TEXT NOT NULL DEFAULT '',
            execution_success BOOLEAN NOT NULL DEFAULT FALSE,
            execution_error TEXT NOT NULL DEFAULT '',
            execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            retry_count INTEGER NOT NULL DEFAULT 0,
            tables_used_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            join_hints TEXT NOT NULL DEFAULT '',
            rule_version TEXT NOT NULL DEFAULT '',
            few_shot_version TEXT NOT NULL DEFAULT '',
            promoted_to_knowledge BOOLEAN NOT NULL DEFAULT FALSE,
            failure_case_synced BOOLEAN NOT NULL DEFAULT FALSE,
            user_rating SMALLINT,
            user_feedback TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS nl2sql_failure_case (
            id BIGSERIAL PRIMARY KEY,
            request_log_id BIGINT NOT NULL UNIQUE REFERENCES nl2sql_request_log(id) ON DELETE CASCADE,
            query_text TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            generated_sql TEXT NOT NULL DEFAULT '',
            final_sql TEXT NOT NULL DEFAULT '',
            error_text TEXT NOT NULL DEFAULT '',
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS nl2sql_runtime_knowledge (
            id BIGSERIAL PRIMARY KEY,
            knowledge_type TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'published',
            source TEXT NOT NULL DEFAULT 'online_harness',
            content_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            content_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS nl2sql_rule_candidate (
            id BIGSERIAL PRIMARY KEY,
            candidate_key TEXT NOT NULL UNIQUE,
            candidate_type TEXT NOT NULL,
            pattern_type TEXT NOT NULL DEFAULT '',
            pattern_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            question_example TEXT NOT NULL DEFAULT '',
            source_request_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_failure_case_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            proposed_rule_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            proposed_few_shot_text TEXT NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            review_note TEXT NOT NULL DEFAULT '',
            published_version TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ,
            published_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS nl2sql_failure_label (
            id BIGSERIAL PRIMARY KEY,
            failure_case_id BIGINT NOT NULL UNIQUE REFERENCES nl2sql_failure_case(id) ON DELETE CASCADE,
            label_type TEXT NOT NULL DEFAULT 'correct_sql',
            correct_sql TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_nl2sql_request_log_created_at
            ON nl2sql_request_log (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nl2sql_request_log_promoted
            ON nl2sql_request_log (promoted_to_knowledge, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nl2sql_failure_case_status
            ON nl2sql_failure_case (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nl2sql_runtime_knowledge_lookup
            ON nl2sql_runtime_knowledge (knowledge_type, status, published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nl2sql_rule_candidate_status
            ON nl2sql_rule_candidate (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nl2sql_failure_label_case
            ON nl2sql_failure_label (failure_case_id);
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            # 兼容旧表：补充缺失字段（已存在则跳过）
            # 设置锁超时避免并发死锁
            cur.execute("SET LOCAL lock_timeout = '2s'")
            _safe_add_column(cur, "ALTER TABLE nl2sql_request_log ADD COLUMN IF NOT EXISTS user_rating SMALLINT")
            _safe_add_column(
                cur,
                "ALTER TABLE nl2sql_request_log ADD COLUMN IF NOT EXISTS user_feedback TEXT NOT NULL DEFAULT ''",
            )
            _safe_add_column(
                cur,
                "ALTER TABLE nl2sql_request_log ADD COLUMN IF NOT EXISTS failure_case_synced BOOLEAN NOT NULL DEFAULT FALSE",
            )
            conn.commit()

    def log_request(self, payload: dict[str, Any]) -> str:
        request_id = str(payload.get("request_id") or uuid.uuid4())
        execution_result = payload.get("execution_result") or {}
        execution_success = bool(execution_result.get("success"))
        execution_error = str(execution_result.get("error", ""))

        sql = """
        INSERT INTO nl2sql_request_log (
            request_id, query_text, generated_sql, final_sql, safe, error_text,
            execution_success, execution_error, execution_result_json, retry_count,
            tables_used_json, join_hints, rule_version, few_shot_version
        ) VALUES (
            %(request_id)s, %(query_text)s, %(generated_sql)s, %(final_sql)s, %(safe)s, %(error_text)s,
            %(execution_success)s, %(execution_error)s, %(execution_result_json)s, %(retry_count)s,
            %(tables_used_json)s, %(join_hints)s, %(rule_version)s, %(few_shot_version)s
        )
        ON CONFLICT (request_id) DO NOTHING
        """
        params = {
            "request_id": request_id,
            "query_text": str(payload.get("query_text", "")),
            "generated_sql": str(payload.get("generated_sql", "")),
            "final_sql": str(payload.get("final_sql", "")),
            "safe": bool(payload.get("safe", False)),
            "error_text": str(payload.get("error_text", "")),
            "execution_success": execution_success,
            "execution_error": execution_error,
            "execution_result_json": json.dumps(execution_result, ensure_ascii=False, default=str),
            "retry_count": int(payload.get("retry_count", 0)),
            "tables_used_json": json.dumps(payload.get("tables_used", []), ensure_ascii=False, default=str),
            "join_hints": str(payload.get("join_hints", "")),
            "rule_version": str(payload.get("rule_version", "")),
            "few_shot_version": str(payload.get("few_shot_version", "")),
        }
        with app_connection() as conn, conn.cursor() as cur:
            try:
                cur.execute(sql, params)
            except psycopg.errors.Error:
                # ON CONFLICT 不可用（旧表缺少 UNIQUE 约束），手动判重
                conn.rollback()
                with conn.cursor() as cur2:
                    cur2.execute(
                        "SELECT id FROM nl2sql_request_log WHERE request_id = %(rid)s::uuid",
                        {"rid": request_id},
                    )
                    if cur2.fetchone() is None:
                        # 去掉 ON CONFLICT 子句重新执行
                        cur2.execute(sql.replace("ON CONFLICT (request_id) DO NOTHING", ""), params)
                conn.commit()
            else:
                conn.commit()
        return request_id

    def sync_failure_cases(self) -> int:
        query = """
        SELECT id, query_text, generated_sql, final_sql, execution_success, safe, error_text, execution_error, retry_count
        FROM nl2sql_request_log
        WHERE failure_case_synced = FALSE
          AND (execution_success = FALSE OR safe = FALSE OR retry_count > 0)
        ORDER BY created_at ASC
        """
        inserted = 0
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            for row in rows:
                retry_cnt = row["retry_count"] or 0
                is_exec_success = bool(row["execution_success"])
                if not row["safe"]:
                    failure_type = "unsafe_sql"
                elif not is_exec_success:
                    failure_type = "execution_error"
                else:
                    failure_type = "retry_success"
                error_text = row["execution_error"] or row["error_text"] or ""
                if failure_type == "retry_success" and not error_text:
                    error_text = f"首次 SQL 执行失败，经 {retry_cnt} 次重试后成功"
                try:
                    cur.execute(
                        """
                        INSERT INTO nl2sql_failure_case (
                            request_log_id, query_text, failure_type, generated_sql, final_sql, error_text, retry_count
                        ) VALUES (
                            %(request_log_id)s, %(query_text)s, %(failure_type)s, %(generated_sql)s, %(final_sql)s, %(error_text)s, %(retry_count)s
                        )
                        ON CONFLICT (request_log_id) DO NOTHING
                        """,
                        {
                            "request_log_id": row["id"],
                            "query_text": row["query_text"],
                            "failure_type": failure_type,
                            "generated_sql": row["generated_sql"],
                            "final_sql": row["final_sql"],
                            "error_text": error_text,
                            "retry_count": row["retry_count"],
                        },
                    )
                except psycopg.errors.Error:
                    # ON CONFLICT 不可用，检查是否已存在再插入
                    conn.rollback()
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "SELECT id FROM nl2sql_failure_case WHERE request_log_id = %(rid)s",
                            {"rid": row["id"]},
                        )
                        if cur2.fetchone() is None:
                            cur2.execute(
                                """
                                INSERT INTO nl2sql_failure_case (
                                    request_log_id, query_text, failure_type, generated_sql, final_sql, error_text, retry_count
                                ) VALUES (
                                    %(request_log_id)s, %(query_text)s, %(failure_type)s, %(generated_sql)s, %(final_sql)s, %(error_text)s, %(retry_count)s
                                )
                                """,
                                {
                                    "request_log_id": row["id"],
                                    "query_text": row["query_text"],
                                    "failure_type": failure_type,
                                    "generated_sql": row["generated_sql"],
                                    "final_sql": row["final_sql"],
                                    "error_text": error_text,
                                    "retry_count": row["retry_count"],
                                },
                            )
                    conn.commit()
                cur.execute(
                    "UPDATE nl2sql_request_log SET failure_case_synced = TRUE WHERE id = %(id)s",
                    {"id": row["id"]},
                )
                inserted += 1
            conn.commit()
        return inserted

    def fetch_promotable_requests(self, limit: int = 200) -> list[dict[str, Any]]:
        query = """
        SELECT rl.*
        FROM nl2sql_request_log rl
        WHERE rl.promoted_to_knowledge = FALSE
          AND rl.execution_success = TRUE
          AND rl.retry_count > 0
          AND rl.final_sql <> ''
          AND NOT EXISTS (
            SELECT 1 FROM nl2sql_failure_case fc WHERE fc.request_log_id = rl.id
          )
        ORDER BY rl.created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_liked_requests(self, limit: int = 200) -> list[dict[str, Any]]:
        """获取用户点赞且未同步到知识库的成功请求。"""
        query = """
        SELECT *
        FROM nl2sql_request_log
        WHERE promoted_to_knowledge = FALSE
          AND execution_success = TRUE
          AND user_rating > 0
          AND final_sql <> ''
        ORDER BY created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_user_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出所有用户反馈记录（点赞+点踩）。"""
        query = """
        SELECT request_id, query_text, generated_sql, final_sql, execution_success,
               user_rating, user_feedback, created_at
        FROM nl2sql_request_log
        WHERE user_rating IS NOT NULL
        ORDER BY created_at DESC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_open_failure_cases(self, limit: int = 200) -> list[dict[str, Any]]:
        query = """
        SELECT *
        FROM nl2sql_failure_case
        WHERE status = 'open'
        ORDER BY created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_unlabeled_failure_cases(self, limit: int = 200) -> list[dict[str, Any]]:
        """获取未标注的失败案例（open 或 analyzed 状态），供 LLM 自动标注使用。"""
        query = """
        SELECT *
        FROM nl2sql_failure_case
        WHERE status IN ('open', 'analyzed')
        ORDER BY created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_unlabeled_failure_cases_by_type(self, failure_types: list[str], limit: int = 200) -> list[dict[str, Any]]:
        """获取指定 failure_type 的未标注失败案例。"""
        query = """
        SELECT *
        FROM nl2sql_failure_case
        WHERE status IN ('open', 'analyzed')
          AND failure_type = ANY(%(types)s)
        ORDER BY created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"types": failure_types, "limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_failure_cases(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            query = """
            SELECT fc.*, fl.id AS label_id, fl.label_type, fl.correct_sql, fl.note AS label_note,
                   rl.user_rating, rl.user_feedback
            FROM nl2sql_failure_case fc
            LEFT JOIN nl2sql_failure_label fl ON fl.failure_case_id = fc.id
            LEFT JOIN nl2sql_request_log rl ON rl.id = fc.request_log_id
            WHERE fc.status = %(status)s
            ORDER BY fc.created_at DESC
            LIMIT %(limit)s
            """
            params = {"status": status, "limit": limit}
        else:
            query = """
            SELECT fc.*, fl.id AS label_id, fl.label_type, fl.correct_sql, fl.note AS label_note,
                   rl.user_rating, rl.user_feedback
            FROM nl2sql_failure_case fc
            LEFT JOIN nl2sql_failure_label fl ON fl.failure_case_id = fc.id
            LEFT JOIN nl2sql_request_log rl ON rl.id = fc.request_log_id
            ORDER BY fc.created_at DESC
            LIMIT %(limit)s
            """
            params = {"limit": limit}
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_labeled_failure_cases(self, limit: int = 200) -> list[dict[str, Any]]:
        query = """
        SELECT fc.*, fl.id AS label_id, fl.label_type, fl.correct_sql, fl.note AS label_note
        FROM nl2sql_failure_case fc
        JOIN nl2sql_failure_label fl ON fl.failure_case_id = fc.id
        WHERE fc.status IN ('labeled', 'open')
        ORDER BY fc.created_at ASC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def upsert_failure_label(
        self, failure_case_id: int, correct_sql: str, note: str = "", label_type: str = "correct_sql"
    ) -> int:
        with app_connection() as conn, conn.cursor() as cur:
            row = None
            try:
                cur.execute(
                    """
                    INSERT INTO nl2sql_failure_label (failure_case_id, label_type, correct_sql, note)
                    VALUES (%(failure_case_id)s, %(label_type)s, %(correct_sql)s, %(note)s)
                    ON CONFLICT (failure_case_id) DO UPDATE SET
                        label_type = EXCLUDED.label_type,
                        correct_sql = EXCLUDED.correct_sql,
                        note = EXCLUDED.note,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    {
                        "failure_case_id": failure_case_id,
                        "label_type": label_type,
                        "correct_sql": correct_sql,
                        "note": note,
                    },
                )
                row = cur.fetchone()
            except psycopg.errors.Error:
                conn.rollback()
                with conn.cursor() as cur2:
                    cur2.execute(
                        "SELECT id FROM nl2sql_failure_label WHERE failure_case_id = %(fid)s",
                        {"fid": failure_case_id},
                    )
                    existing = cur2.fetchone()
                    if existing:
                        cur2.execute(
                            """
                            UPDATE nl2sql_failure_label
                            SET label_type = %(label_type)s,
                                correct_sql = %(correct_sql)s,
                                note = %(note)s,
                                updated_at = NOW()
                            WHERE id = %(id)s
                            RETURNING id
                            """,
                            {"id": existing["id"], "label_type": label_type, "correct_sql": correct_sql, "note": note},
                        )
                        row = cur2.fetchone()
                    else:
                        cur2.execute(
                            """
                            INSERT INTO nl2sql_failure_label (failure_case_id, label_type, correct_sql, note)
                            VALUES (%(failure_case_id)s, %(label_type)s, %(correct_sql)s, %(note)s)
                            RETURNING id
                            """,
                            {
                                "failure_case_id": failure_case_id,
                                "label_type": label_type,
                                "correct_sql": correct_sql,
                                "note": note,
                            },
                        )
                        row = cur2.fetchone()
                conn.commit()
            cur.execute(
                "UPDATE nl2sql_failure_case SET status = 'labeled' WHERE id = %(failure_case_id)s",
                {"failure_case_id": failure_case_id},
            )
            conn.commit()
        return int(row["id"])

    def fetch_successful_requests_for_queries(self, queries: list[str]) -> list[dict[str, Any]]:
        if not queries:
            return []
        query = """
        SELECT *
        FROM nl2sql_request_log
        WHERE execution_success = TRUE
          AND final_sql <> ''
          AND query_text = ANY(%(queries)s)
        ORDER BY created_at DESC
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"queries": queries})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_requests_promoted(self, request_ids: list[str]) -> None:
        if not request_ids:
            return
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE nl2sql_request_log SET promoted_to_knowledge = TRUE WHERE request_id = ANY(%(request_ids)s)",
                {"request_ids": request_ids},
            )
            conn.commit()

    def get_ratings_by_request_ids(self, request_ids: list[str]) -> dict[str, dict[str, Any]]:
        """批量查询 request_id 对应的用户评分。

        Returns:
            {request_id: {"rating": 1|-1|null, "feedback": str}}
        """
        if not request_ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT request_id, user_rating, user_feedback FROM nl2sql_request_log WHERE request_id = ANY(%(ids)s::uuid[])",
                {"ids": request_ids},
            )
            for row in cur.fetchall():
                result[str(row["request_id"])] = {
                    "rating": row["user_rating"],
                    "feedback": row["user_feedback"] or "",
                }
        return result

    def submit_user_feedback(self, request_id: str, rating: int, reason: str = "") -> dict[str, Any]:
        """提交用户反馈：更新或创建请求日志记录并（点踩时）创建失败案例。

        如果 request_id 在 nl2sql_request_log 中不存在（例如请求日志未成功写入），
        则自动创建一条最小记录，确保反馈不丢失。

        Returns:
            {"request_id": str, "rating": int, "failure_case_created": bool}
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nl2sql_request_log
                SET user_rating = %(rating)s, user_feedback = %(reason)s
                WHERE request_id = %(request_id)s::uuid
                RETURNING id, query_text, generated_sql, final_sql, error_text, retry_count
                """,
                {"request_id": request_id, "rating": rating, "reason": reason},
            )
            row = cur.fetchone()
            if row is None:
                # 请求日志未写入，创建一条最小记录承载反馈
                try:
                    cur.execute(
                        """
                        INSERT INTO nl2sql_request_log (request_id, query_text, user_rating, user_feedback)
                        VALUES (%(request_id)s::uuid, '', %(rating)s, %(reason)s)
                        RETURNING id, query_text, generated_sql, final_sql, error_text, retry_count
                        """,
                        {"request_id": request_id, "rating": rating, "reason": reason},
                    )
                    row = cur.fetchone()
                    logger.info("反馈写入时发现请求日志缺失，已创建占位记录: request_id=%s", request_id)
                except psycopg.errors.UniqueViolation:
                    # 并发场景下另一个连接已插入，重新尝试 UPDATE
                    logger.info("占位记录冲突，重试 UPDATE: request_id=%s", request_id)
                    cur.execute(
                        """
                        UPDATE nl2sql_request_log
                        SET user_rating = %(rating)s, user_feedback = %(reason)s
                        WHERE request_id = %(request_id)s::uuid
                        RETURNING id, query_text, generated_sql, final_sql, error_text, retry_count
                        """,
                        {"request_id": request_id, "rating": rating, "reason": reason},
                    )
                    row = cur.fetchone()
            conn.commit()

        failure_case_created = False
        if rating < 0 and row:
            # 点踩：直接创建失败案例
            with app_connection() as conn, conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO nl2sql_failure_case (
                            request_log_id, query_text, failure_type, generated_sql, final_sql, error_text, retry_count, status
                        ) VALUES (
                            %(request_log_id)s, %(query_text)s, 'user_reported', %(generated_sql)s, %(final_sql)s, %(error_text)s, %(retry_count)s, 'open'
                        )
                        ON CONFLICT (request_log_id) DO UPDATE SET
                            status = 'open',
                            failure_type = 'user_reported',
                            error_text = EXCLUDED.error_text
                        """,
                        {
                            "request_log_id": row["id"],
                            "query_text": row["query_text"],
                            "generated_sql": row["generated_sql"],
                            "final_sql": row["final_sql"],
                            "error_text": reason or row["error_text"],
                            "retry_count": row["retry_count"],
                        },
                    )
                except Exception:
                    # ON CONFLICT 不可用（旧表缺少 UNIQUE 约束），回退到先查再改
                    conn.rollback()
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "SELECT id FROM nl2sql_failure_case WHERE request_log_id = %(rid)s",
                            {"rid": row["id"]},
                        )
                        existing = cur2.fetchone()
                        if existing:
                            cur2.execute(
                                """
                                UPDATE nl2sql_failure_case
                                SET status = 'open',
                                    failure_type = 'user_reported',
                                    error_text = %(error_text)s
                                WHERE id = %(id)s
                                """,
                                {"id": existing["id"], "error_text": reason or row["error_text"]},
                            )
                        else:
                            cur2.execute(
                                """
                                INSERT INTO nl2sql_failure_case (
                                    request_log_id, query_text, failure_type, generated_sql, final_sql, error_text, retry_count, status
                                ) VALUES (
                                    %(request_log_id)s, %(query_text)s, 'user_reported', %(generated_sql)s, %(final_sql)s, %(error_text)s, %(retry_count)s, 'open'
                                )
                                """,
                                {
                                    "request_log_id": row["id"],
                                    "query_text": row["query_text"],
                                    "generated_sql": row["generated_sql"],
                                    "final_sql": row["final_sql"],
                                    "error_text": reason or row["error_text"],
                                    "retry_count": row["retry_count"],
                                },
                            )
                    conn.commit()
                else:
                    conn.commit()
            failure_case_created = True

        return {
            "request_id": request_id,
            "rating": rating,
            "failure_case_created": failure_case_created,
        }

    def upsert_rule_candidate(self, payload: dict[str, Any]) -> int:
        sql = """
        INSERT INTO nl2sql_rule_candidate (
            candidate_key, candidate_type, pattern_type, pattern_key, status, question_example,
            source_request_ids_json, source_failure_case_ids_json, proposed_rule_json,
            proposed_few_shot_text, confidence, evidence_json, review_note
        ) VALUES (
            %(candidate_key)s, %(candidate_type)s, %(pattern_type)s, %(pattern_key)s, %(status)s, %(question_example)s,
            %(source_request_ids_json)s::jsonb, %(source_failure_case_ids_json)s::jsonb, %(proposed_rule_json)s::jsonb,
            %(proposed_few_shot_text)s, %(confidence)s, %(evidence_json)s::jsonb, %(review_note)s
        )
        ON CONFLICT (candidate_key) DO UPDATE SET
            candidate_type = EXCLUDED.candidate_type,
            pattern_type = EXCLUDED.pattern_type,
            pattern_key = EXCLUDED.pattern_key,
            question_example = EXCLUDED.question_example,
            source_request_ids_json = EXCLUDED.source_request_ids_json,
            source_failure_case_ids_json = EXCLUDED.source_failure_case_ids_json,
            proposed_rule_json = EXCLUDED.proposed_rule_json,
            proposed_few_shot_text = EXCLUDED.proposed_few_shot_text,
            confidence = EXCLUDED.confidence,
            evidence_json = EXCLUDED.evidence_json
        RETURNING id
        """
        params = {
            "candidate_key": str(payload.get("candidate_key", "")),
            "candidate_type": str(payload.get("candidate_type", "")),
            "pattern_type": str(payload.get("pattern_type", "")),
            "pattern_key": str(payload.get("pattern_key", "")),
            "status": str(payload.get("status", "pending")),
            "question_example": str(payload.get("question_example", "")),
            "source_request_ids_json": json.dumps(
                payload.get("source_request_ids", []), ensure_ascii=False, default=str
            ),
            "source_failure_case_ids_json": json.dumps(
                payload.get("source_failure_case_ids", []), ensure_ascii=False, default=str
            ),
            "proposed_rule_json": json.dumps(payload.get("proposed_rule_json", {}), ensure_ascii=False, default=str),
            "proposed_few_shot_text": str(payload.get("proposed_few_shot_text", "")),
            "confidence": float(payload.get("confidence", 0)),
            "evidence_json": json.dumps(payload.get("evidence_json", {}), ensure_ascii=False, default=str),
            "review_note": str(payload.get("review_note", "")),
        }
        with app_connection() as conn, conn.cursor() as cur:
            try:
                cur.execute(sql, params)
                row = cur.fetchone()
            except psycopg.errors.Error:
                conn.rollback()
                with conn.cursor() as cur2:
                    cur2.execute(
                        "SELECT id FROM nl2sql_rule_candidate WHERE candidate_key = %(key)s",
                        {"key": str(payload.get("candidate_key", ""))},
                    )
                    existing = cur2.fetchone()
                    if existing:
                        # 去掉 ON CONFLICT 子句和 RETURNING，手动构造 UPDATE
                        update_sql = (
                            "UPDATE nl2sql_rule_candidate SET "
                            "candidate_type = %(candidate_type)s, "
                            "pattern_type = %(pattern_type)s, "
                            "pattern_key = %(pattern_key)s, "
                            "question_example = %(question_example)s, "
                            "source_request_ids_json = %(source_request_ids_json)s::jsonb, "
                            "source_failure_case_ids_json = %(source_failure_case_ids_json)s::jsonb, "
                            "proposed_rule_json = %(proposed_rule_json)s::jsonb, "
                            "proposed_few_shot_text = %(proposed_few_shot_text)s, "
                            "confidence = %(confidence)s, "
                            "evidence_json = %(evidence_json)s::jsonb, "
                            "review_note = %(review_note)s "
                            "WHERE id = %(existing_id)s "
                            "RETURNING id"
                        )
                        upd_params = {**params, "existing_id": existing["id"]}
                        cur2.execute(update_sql, upd_params)
                        row = cur2.fetchone()
                    else:
                        # 去掉 ON CONFLICT 子句重新执行 INSERT
                        clean_sql = sql[: sql.index("ON CONFLICT")].strip() + " RETURNING id"
                        cur2.execute(clean_sql, params)
                        row = cur2.fetchone()
                conn.commit()
            else:
                conn.commit()
        return int(row["id"])

    def list_rule_candidates(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            query = """
            SELECT *
            FROM nl2sql_rule_candidate
            WHERE status = %(status)s
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """
            params = {"status": status, "limit": limit}
        else:
            query = """
            SELECT *
            FROM nl2sql_rule_candidate
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """
            params = {"limit": limit}
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def review_rule_candidate(self, candidate_id: int, action: str, note: str = "") -> None:
        status = {"approve": "approved", "reject": "rejected"}[action]
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nl2sql_rule_candidate
                SET status = %(status)s, review_note = %(note)s, reviewed_at = NOW()
                WHERE id = %(candidate_id)s
                """,
                {"status": status, "note": note, "candidate_id": candidate_id},
            )
            conn.commit()

    def fetch_publishable_candidates(self) -> list[dict[str, Any]]:
        query = """
        SELECT *
        FROM nl2sql_rule_candidate
        WHERE status = 'approved'
        ORDER BY created_at ASC
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_candidates_published(self, candidate_ids: list[int], version: str) -> None:
        if not candidate_ids:
            return
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nl2sql_rule_candidate
                SET status = 'published', published_version = %(version)s, published_at = NOW()
                WHERE id = ANY(%(candidate_ids)s)
                """,
                {"version": version, "candidate_ids": candidate_ids},
            )
            conn.commit()

    def update_failure_case_statuses(self, failure_case_ids: list[int], status: str) -> None:
        if not failure_case_ids:
            return
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE nl2sql_failure_case SET status = %(status)s WHERE id = ANY(%(ids)s)",
                {"status": status, "ids": failure_case_ids},
            )
            conn.commit()


_repository: OnlineHarnessRepository | None = None


def get_online_harness_repository() -> OnlineHarnessRepository:
    global _repository
    if _repository is None:
        _repository = OnlineHarnessRepository()
    return _repository
