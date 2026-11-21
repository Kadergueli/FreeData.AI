"""Stockage PRIVÉ des évaluations de terrain : schéma applicatif (jamais exposé), isolation stricte par owner_id.

Ces données ne sont lues par aucune table publique, aucun modèle global ni ml_benchmark
(ALLOWED_DATASET_SCOPES = ("platform_public",) : aucun scope « agro privé » n'existe).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src import db as _db


class AgroAssessmentStore:
    def __init__(self, db_path: Optional[str] = None, *, database_url: Optional[str] = None, schema: Optional[str] = None) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = _db.validate_schema(schema) if schema else (
            _db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        self.db_path = Path(db_path or os.getenv("FREEDATA_AGRO_DB_PATH", "data/freedata_agro.db"))
        if not self._pg_url:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agro_field_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    hub TEXT NOT NULL,
                    title TEXT NOT NULL,
                    downgraded INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agro_assess_owner
                    ON agro_field_assessments (owner_id, created_at DESC);
                """
            )

    def _connect(self):
        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, owner_id: str, assessment: dict[str, Any]) -> dict[str, Any]:
        if not owner_id:
            raise ValueError("owner_id requis")
        aid = uuid.uuid4().hex
        record = {**assessment, "assessment_id": aid}
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agro_field_assessments (assessment_id, owner_id, hub, title, downgraded, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aid, owner_id, record["hub"], record["title"], 1 if record.get("downgraded") else 0,
                 json.dumps(record, ensure_ascii=False), created),
            )
        return record

    def get(self, owner_id: str, assessment_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM agro_field_assessments WHERE assessment_id = ? AND owner_id = ?",
                (assessment_id, owner_id),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list(self, owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT assessment_id, hub, title, downgraded, created_at FROM agro_field_assessments "
                "WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?",
                (owner_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, owner_id: str, assessment_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM agro_field_assessments WHERE assessment_id = ? AND owner_id = ?", (assessment_id, owner_id))
            return (cur.rowcount or 0) > 0
