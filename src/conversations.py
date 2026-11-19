"""Cloud Conversation Sync Store (SQLite / Supabase PostgreSQL freedata_app)."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src import db as _db

MAX_CLOUD_CONVERSATIONS = 100


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationStore:
    """Persistance cloud des conversations Chat pour synchronisation multi-appareils."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        database_url: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = (
            _db.validate_schema(schema)
            if schema
            else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        )
        self.db_path = Path(db_path or os.getenv("FREEDATA_CONVERSATIONS_DB_PATH", "data/freedata_conversations.db"))
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
                CREATE TABLE IF NOT EXISTS user_conversations (
                    owner_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    is_saved_in_library INTEGER NOT NULL DEFAULT 0,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    messages_json TEXT NOT NULL,
                    project_id TEXT,
                    project_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, conversation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_conversations_owner_updated
                    ON user_conversations(owner_id, updated_at DESC);
                """
            )
            # Migration douce (idempotente) pour bases SQLite/Postgres existantes sans colonnes project_id / project_name
            # PostgreSQL avorte la transaction courante sur DuplicateColumn : utiliser IF NOT EXISTS + SAVEPOINT.
            alter_kw = "ADD COLUMN IF NOT EXISTS" if self._pg_url else "ADD COLUMN"
            for idx_i, stmt in enumerate((
                f"ALTER TABLE user_conversations {alter_kw} project_id TEXT",
                f"ALTER TABLE user_conversations {alter_kw} project_name TEXT",
                "CREATE INDEX IF NOT EXISTS idx_user_conversations_owner_project "
                "ON user_conversations(owner_id, project_id, updated_at DESC)",
            )):
                sp = f"sp_conv_mig_{idx_i}"
                try:
                    if self._pg_url:
                        conn.execute(f"SAVEPOINT {sp}")
                    conn.execute(stmt)
                    if self._pg_url:
                        conn.execute(f"RELEASE SAVEPOINT {sp}")
                except Exception:
                    if self._pg_url:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        conn.execute(f"RELEASE SAVEPOINT {sp}")
            if self._pg_url:
                _db.harden_tables(conn)

    @staticmethod
    def _row_to_thread(row: Any) -> dict[str, Any]:
        d = dict(row)
        try:
            msgs = json.loads(d.get("messages_json") or "[]")
            if not isinstance(msgs, list):
                msgs = []
        except ValueError:
            msgs = []
        return {
            "id": d["conversation_id"],
            "title": d["title"],
            "isSavedInLibrary": bool(d.get("is_saved_in_library")),
            "isDeleted": bool(d.get("is_deleted")),
            "projectId": d.get("project_id"),
            "projectName": d.get("project_name"),
            "createdAt": d["created_at"],
            "updatedAt": d["updated_at"],
            "messages": msgs,
        }

    def list_conversations(self, owner_id: str, *, include_deleted: bool = True, limit: int = MAX_CLOUD_CONVERSATIONS) -> list[dict[str, Any]]:
        sql = "SELECT * FROM user_conversations WHERE owner_id = ?"
        params: list[Any] = [owner_id]
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(MAX_CLOUD_CONVERSATIONS, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_thread(r) for r in rows]

    def upsert_conversation(self, owner_id: str, thread: dict[str, Any]) -> dict[str, Any]:
        conv_id = str(thread.get("id") or "").strip()[:80]
        if not conv_id:
            raise ValueError("Identifiant de conversation requis.")
        msgs = thread.get("messages")
        if not isinstance(msgs, list) or not msgs:
            raise ValueError("Impossible de sauvegarder une conversation vide.")
        # Limiter la taille stockée par conversation (anti-abus)
        trimmed_msgs = msgs[-120:]
        title = str(thread.get("title") or "Nouvelle conversation").strip()[:140] or "Nouvelle conversation"
        saved_flag = 1 if thread.get("isSavedInLibrary") else 0
        deleted_flag = 1 if thread.get("isDeleted") else 0
        raw_proj_id = thread.get("projectId") or thread.get("project_id")
        project_id = str(raw_proj_id).strip()[:80] if raw_proj_id else None
        raw_proj_name = thread.get("projectName") or thread.get("project_name")
        project_name = str(raw_proj_name).strip()[:140] if raw_proj_name else None
        now = _utc_now_iso()
        created_at = str(thread.get("createdAt") or now)[:40]
        updated_at = str(thread.get("updatedAt") or now)[:40]
        raw_msgs = json.dumps(trimmed_msgs, ensure_ascii=False)

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT updated_at FROM user_conversations WHERE owner_id = ? AND conversation_id = ?",
                (owner_id, conv_id),
            ).fetchone()
            # Ne pas écraser une version cloud plus récente lors d'une synchro
            if existing and str(existing["updated_at"]) > updated_at:
                row = conn.execute(
                    "SELECT * FROM user_conversations WHERE owner_id = ? AND conversation_id = ?",
                    (owner_id, conv_id),
                ).fetchone()
                return self._row_to_thread(row)
            conn.execute(
                """
                INSERT INTO user_conversations (
                    owner_id, conversation_id, title, is_saved_in_library, is_deleted,
                    messages_json, project_id, project_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (owner_id, conversation_id) DO UPDATE SET
                    title = excluded.title,
                    is_saved_in_library = excluded.is_saved_in_library,
                    is_deleted = excluded.is_deleted,
                    messages_json = excluded.messages_json,
                    project_id = COALESCE(excluded.project_id, user_conversations.project_id),
                    project_name = COALESCE(excluded.project_name, user_conversations.project_name),
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    conv_id,
                    title,
                    saved_flag,
                    deleted_flag,
                    raw_msgs,
                    project_id,
                    project_name,
                    created_at,
                    updated_at,
                ),
            )
            self._trim_owner_conversations(conn, owner_id)
            row = conn.execute(
                "SELECT * FROM user_conversations WHERE owner_id = ? AND conversation_id = ?",
                (owner_id, conv_id),
            ).fetchone()
        return self._row_to_thread(row)

    @staticmethod
    def _trim_owner_conversations(conn: Any, owner_id: str) -> None:
        rows = conn.execute(
            """
            SELECT conversation_id, is_saved_in_library, is_deleted
            FROM user_conversations
            WHERE owner_id = ?
            ORDER BY updated_at DESC
            """,
            (owner_id,),
        ).fetchall()
        if len(rows) <= MAX_CLOUD_CONVERSATIONS:
            return
        pinned = [r["conversation_id"] for r in rows if r["is_saved_in_library"] and not r["is_deleted"]]
        others = [r["conversation_id"] for r in rows if not (r["is_saved_in_library"] and not r["is_deleted"])]
        slots = max(0, MAX_CLOUD_CONVERSATIONS - len(pinned))
        keep = set(pinned) | set(others[:slots])
        for r in rows:
            cid = r["conversation_id"]
            if cid not in keep:
                conn.execute(
                    "DELETE FROM user_conversations WHERE owner_id = ? AND conversation_id = ?",
                    (owner_id, cid),
                )

    def sync_conversations(self, owner_id: str, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in (incoming or [])[:MAX_CLOUD_CONVERSATIONS]:
            if isinstance(item, dict) and item.get("id") and item.get("messages"):
                try:
                    self.upsert_conversation(owner_id, item)
                except ValueError:
                    continue
        return self.list_conversations(owner_id, include_deleted=True, limit=MAX_CLOUD_CONVERSATIONS)

    def detach_project(self, owner_id: str, project_id: str) -> int:
        """Detaches conversations from a deleted project while preserving the user's message history."""
        if not owner_id or not project_id:
            return 0
        clean_pid = project_id.strip()[:80]
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE user_conversations SET project_id = NULL, project_name = NULL WHERE owner_id = ? AND project_id = ?",
                (owner_id, clean_pid),
            )
            return int(cur.rowcount or 0)

    def delete_conversation(self, owner_id: str, conversation_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM user_conversations WHERE owner_id = ? AND conversation_id = ?",
                (owner_id, conversation_id),
            )
            return cur.rowcount > 0

    def purge_owner(self, owner_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM user_conversations WHERE owner_id = ?", (owner_id,))
            return int(cur.rowcount or 0)

