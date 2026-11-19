"""Privacy-conscious Support Tickets, Structured Feedback, and Product Analytics Store."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3

from src import db as _db
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SupportFeedbackStore:
    """SQLite-backed store for user support tickets, structured feedback, and product analytics."""

    def __init__(self, db_path: Optional[str] = None, *, database_url: Optional[str] = None, schema: Optional[str] = None) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = _db.validate_schema(schema) if schema else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        self.db_path = Path(db_path or os.getenv("FREEDATA_SUPPORT_DB_PATH", "data/freedata_support.db"))
        if not self._pg_url:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS support_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'open',
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tickets_owner ON support_tickets (owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS user_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    owner_hash TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_events (
                    event_id TEXT PRIMARY KEY,
                    user_hash TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    properties_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prod_events_name ON product_events (event_name, created_at DESC);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    @staticmethod
    def _hash_user(owner_id: str) -> str:
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]

    def create_ticket(
        self,
        owner_id: str,
        *,
        category: str,
        subject: str,
        description: str,
        priority: str = "normal",
    ) -> dict[str, Any]:
        now = _utc_now()
        tid = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO support_tickets (ticket_id, owner_id, category, priority, status, subject, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (tid, owner_id, category, priority, subject.strip()[:140], description.strip()[:2000], now, now),
            )
        return self.get_user_ticket(owner_id, tid)

    def get_user_ticket(self, owner_id: str, ticket_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ticket_id, category, priority, status, subject, description, created_at, updated_at "
                "FROM support_tickets WHERE ticket_id = ? AND owner_id = ?",
                (ticket_id, owner_id),
            ).fetchone()
            if not row:
                raise KeyError(f"Ticket introuvable : {ticket_id}")
            return dict(row)

    def list_user_tickets(self, owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticket_id, category, priority, status, subject, description, created_at, updated_at "
                "FROM support_tickets WHERE owner_id = ? ORDER BY updated_at DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def admin_list_tickets(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT ticket_id, owner_id, category, priority, status, subject, description, created_at, updated_at FROM support_tickets WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def admin_update_ticket(
        self,
        ticket_id: str,
        *,
        status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if not row:
                raise KeyError(f"Ticket introuvable : {ticket_id}")
            new_status = status if status in ("open", "in_progress", "resolved", "closed") else row["status"]
            new_prio = priority if priority in ("low", "normal", "high", "urgent") else row["priority"]
            conn.execute(
                "UPDATE support_tickets SET status = ?, priority = ?, updated_at = ? WHERE ticket_id = ?",
                (new_status, new_prio, now, ticket_id),
            )
            updated = conn.execute("SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            return dict(updated)

    def submit_feedback(
        self,
        owner_id: str,
        *,
        feature: str,
        rating: int,
        category: str = "general",
        comment: str = "",
    ) -> dict[str, Any]:
        fid = f"FBK-{uuid.uuid4().hex[:8].upper()}"
        clamped_rating = max(1, min(5, int(rating)))
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_feedback (feedback_id, owner_hash, feature, rating, category, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (fid, self._hash_user(owner_id), feature, clamped_rating, category, comment.strip()[:1000], now),
            )
        return {"feedback_id": fid, "feature": feature, "rating": clamped_rating, "created_at": now}

    def record_product_event(
        self,
        owner_id: str,
        *,
        event_name: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> str:
        ev_id = f"PEV-{uuid.uuid4().hex[:10].upper()}"
        safe_props = {k: v for k, v in (properties or {}).items() if k not in ("prompt", "message", "content", "password", "token")}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO product_events (event_id, user_hash, event_name, properties_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (ev_id, self._hash_user(owner_id), event_name[:60], json.dumps(safe_props, ensure_ascii=False), _utc_now()),
            )
        return ev_id

    def get_admin_overview(self) -> dict[str, Any]:
        with self._connect() as conn:
            t_rows = conn.execute("SELECT status, COUNT(*) AS cnt FROM support_tickets GROUP BY status").fetchall()
            c_rows = conn.execute("SELECT category, COUNT(*) AS cnt FROM support_tickets GROUP BY category").fetchall()
            f_row = conn.execute("SELECT COUNT(*) AS cnt, AVG(rating) AS avg_r FROM user_feedback").fetchone()
            e_rows = conn.execute("SELECT event_name, COUNT(*) AS cnt FROM product_events GROUP BY event_name").fetchall()
            u_cnt = conn.execute("SELECT COUNT(DISTINCT user_hash) FROM product_events").fetchone()[0]
        return {
            "tickets_by_status": {r["status"]: int(r["cnt"]) for r in t_rows},
            "tickets_by_category": {r["category"]: int(r["cnt"]) for r in c_rows},
            "feedback": {
                "total_count": int(f_row["cnt"] or 0),
                "avg_rating": round(float(f_row["avg_r"]), 2) if f_row["avg_r"] is not None else None,
            },
            "product_analytics": {
                "unique_active_users": int(u_cnt),
                "events_by_name": {r["event_name"]: int(r["cnt"]) for r in e_rows},
            },
        }

