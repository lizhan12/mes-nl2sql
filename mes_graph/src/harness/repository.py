"""线上 Harness 数据库存储。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.core.config import settings

_runtime_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class PublishedKnowledge:
    version: str
    rules: list[dict[str, Any]]
    few_shot_text: str


class OnlineHarnessRepository:
    """线上 Harness 仓储。"""

    def __init__(self, db_url: str, cache_ttl_seconds: int = 60) -> None:
        self.db_url = db_url.replace("+asyncpg", "")
        self.cache_ttl_seconds = cache_ttl_seconds

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.db_url, row_factory=dict_row)

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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(ddl)
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
        return request_id

    def sync_failure_cases(self) -> int:
        query = """
        SELECT id, query_text, generated_sql, final_sql, execution_success, safe, error_text, execution_error, retry_count
        FROM nl2sql_request_log
        WHERE failure_case_synced = FALSE
          AND (execution_success = FALSE OR safe = FALSE)
        ORDER BY created_at ASC
        """
        inserted = 0
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            for row in rows:
                failure_type = "unsafe_sql" if not row["safe"] else "execution_error"
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
                        "error_text": row["execution_error"] or row["error_text"],
                        "retry_count": row["retry_count"],
                    },
                )
                cur.execute(
                    "UPDATE nl2sql_request_log SET failure_case_synced = TRUE WHERE id = %(id)s",
                    {"id": row["id"]},
                )
                inserted += 1
            conn.commit()
        return inserted

    def fetch_promotable_requests(self, limit: int = 200) -> list[dict[str, Any]]:
        query = """
        SELECT *
        FROM nl2sql_request_log
        WHERE promoted_to_knowledge = FALSE
          AND execution_success = TRUE
          AND retry_count > 0
          AND final_sql <> ''
        ORDER BY created_at ASC
        LIMIT %(limit)s
        """
        with self.connect() as conn, conn.cursor() as cur:
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_failure_cases(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            query = """
            SELECT fc.*, fl.id AS label_id, fl.label_type, fl.correct_sql, fl.note AS label_note
            FROM nl2sql_failure_case fc
            LEFT JOIN nl2sql_failure_label fl ON fl.failure_case_id = fc.id
            WHERE fc.status = %(status)s
            ORDER BY fc.created_at DESC
            LIMIT %(limit)s
            """
            params = {"status": status, "limit": limit}
        else:
            query = """
            SELECT fc.*, fl.id AS label_id, fl.label_type, fl.correct_sql, fl.note AS label_note
            FROM nl2sql_failure_case fc
            LEFT JOIN nl2sql_failure_label fl ON fl.failure_case_id = fc.id
            ORDER BY fc.created_at DESC
            LIMIT %(limit)s
            """
            params = {"limit": limit}
        with self.connect() as conn, conn.cursor() as cur:
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"limit": limit})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def upsert_failure_label(
        self, failure_case_id: int, correct_sql: str, note: str = "", label_type: str = "correct_sql"
    ) -> int:
        with self.connect() as conn, conn.cursor() as cur:
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"queries": queries})
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_requests_promoted(self, request_ids: list[str]) -> None:
        if not request_ids:
            return
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE nl2sql_request_log SET promoted_to_knowledge = TRUE WHERE request_id = ANY(%(request_ids)s)",
                {"request_ids": request_ids},
            )
            conn.commit()

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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def review_rule_candidate(self, candidate_id: int, action: str, note: str = "") -> None:
        status = {"approve": "approved", "reject": "rejected"}[action]
        with self.connect() as conn, conn.cursor() as cur:
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_candidates_published(self, candidate_ids: list[int], version: str) -> None:
        if not candidate_ids:
            return
        with self.connect() as conn, conn.cursor() as cur:
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
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE nl2sql_failure_case SET status = %(status)s WHERE id = ANY(%(ids)s)",
                {"status": status, "ids": failure_case_ids},
            )
            conn.commit()

    def publish_runtime_knowledge(
        self,
        version: str,
        rules: list[dict[str, Any]],
        few_shot_text: str,
        source: str = "online_harness",
    ) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nl2sql_runtime_knowledge (knowledge_type, version, status, source, content_json, content_text)
                VALUES ('runtime_rules', %(version)s, 'published', %(source)s, %(content_json)s::jsonb, '')
                """,
                {
                    "version": version,
                    "source": source,
                    "content_json": json.dumps(rules, ensure_ascii=False, default=str),
                },
            )
            cur.execute(
                """
                INSERT INTO nl2sql_runtime_knowledge (knowledge_type, version, status, source, content_json, content_text)
                VALUES ('evolved_few_shot', %(version)s, 'published', %(source)s, '[]'::jsonb, %(content_text)s)
                """,
                {
                    "version": version,
                    "source": source,
                    "content_text": few_shot_text,
                },
            )
            conn.commit()
        self.invalidate_cache()

    def load_published_knowledge(self) -> PublishedKnowledge:
        cache_key = "published_knowledge"
        now = time.time()
        cached = _runtime_cache.get(cache_key)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT knowledge_type, version, content_json, content_text
                FROM nl2sql_runtime_knowledge
                WHERE status = 'published'
                ORDER BY published_at DESC, id DESC
                """
            )
            rows = cur.fetchall()

        rules: list[dict[str, Any]] = []
        few_shot_text = ""
        version = ""
        for row in rows:
            knowledge_type = str(row["knowledge_type"])
            version = version or str(row["version"] or "")
            if knowledge_type == "runtime_rules" and not rules:
                content = row["content_json"]
                if isinstance(content, str):
                    content = json.loads(content)
                rules = content if isinstance(content, list) else []
            elif knowledge_type == "evolved_few_shot" and not few_shot_text:
                few_shot_text = str(row["content_text"] or "")
            if rules and few_shot_text:
                break

        published = PublishedKnowledge(version=version, rules=rules, few_shot_text=few_shot_text)
        _runtime_cache[cache_key] = (now, published)
        return published

    def invalidate_cache(self) -> None:
        _runtime_cache.clear()


_repository: OnlineHarnessRepository | None = None


def get_online_harness_repository() -> OnlineHarnessRepository:
    global _repository
    if _repository is None:
        _repository = OnlineHarnessRepository(
            db_url=settings.app_database_url,
            cache_ttl_seconds=settings.harness_runtime_cache_ttl_seconds,
        )
    return _repository
