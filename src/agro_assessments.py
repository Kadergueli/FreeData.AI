"""Stockage privé des diagnostics de terrain Agronome PRO (table_agro_field_assessments).

Isolation stricte par `owner_id` (et `project_id` optionnel) ; RLS activée sur PostgreSQL.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src import db as _db


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_verification_code() -> str:
    year = datetime.now(timezone.utc).year
    token = secrets.token_hex(3).upper()
    return f"FDT-{year}-{token}"


class AgroFieldAssessmentStore:
    """CRUD isolé par `owner_id` pour les diagnostics agronomiques de terrain."""

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
        self.db_path = Path(db_path or os.getenv("FREEDATA_AGRO_DB_PATH", "data/freedata_agro.db"))
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
                CREATE TABLE IF NOT EXISTS table_agro_field_assessments (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    project_id TEXT,
                    province_hub TEXT NOT NULL,
                    gps_lat REAL,
                    gps_lon REAL,
                    area_hectares REAL,
                    lab_soil_inputs TEXT NOT NULL DEFAULT '{}',
                    agronomist_field_notes TEXT NOT NULL DEFAULT '',
                    target_crops TEXT NOT NULL DEFAULT '[]',
                    computed_scores TEXT NOT NULL DEFAULT '{}',
                    report_verification_code TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agro_assess_owner
                    ON table_agro_field_assessments(owner_id, created_at DESC);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        for key, fallback in (("lab_soil_inputs", {}), ("target_crops", []), ("computed_scores", {})):
            raw = d.get(key)
            if isinstance(raw, str):
                try:
                    d[key] = json.loads(raw)
                except ValueError:
                    d[key] = fallback
            elif raw is None:
                d[key] = fallback
        return d

    def create_assessment(
        self,
        owner_id: str,
        *,
        province_hub: str,
        project_id: Optional[str] = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        area_hectares: Optional[float] = None,
        lab_soil_inputs: Optional[dict[str, Any]] = None,
        agronomist_field_notes: str = "",
        target_crops: Optional[list[str]] = None,
        computed_scores: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        aid = f"AG-{uuid.uuid4().hex[:12].upper()}"
        code = _new_verification_code()
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO table_agro_field_assessments (
                    id, owner_id, project_id, province_hub, gps_lat, gps_lon,
                    area_hectares, lab_soil_inputs, agronomist_field_notes,
                    target_crops, computed_scores, report_verification_code, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    aid,
                    owner_id,
                    project_id,
                    province_hub,
                    gps_lat,
                    gps_lon,
                    area_hectares,
                    json.dumps(lab_soil_inputs or {}, ensure_ascii=False),
                    (agronomist_field_notes or "").strip()[:4000],
                    json.dumps(list(target_crops or []), ensure_ascii=False),
                    json.dumps(computed_scores or {}, ensure_ascii=False),
                    code,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM table_agro_field_assessments WHERE id = ? AND owner_id = ?",
                (aid, owner_id),
            ).fetchone()
        return self._row_to_dict(row)

    def get_assessment(self, owner_id: str, assessment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM table_agro_field_assessments WHERE id = ? AND owner_id = ?",
                (assessment_id, owner_id),
            ).fetchone()
        if not row:
            raise KeyError("Diagnostic de terrain introuvable ou accès non autorisé.")
        return self._row_to_dict(row)

    def list_assessments(
        self,
        owner_id: str,
        *,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(100, int(limit)))
        with self._connect() as conn:
            if project_id:
                rows = conn.execute(
                    """
                    SELECT * FROM table_agro_field_assessments
                    WHERE owner_id = ? AND project_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (owner_id, project_id, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM table_agro_field_assessments
                    WHERE owner_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (owner_id, lim),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def purge_owner(self, owner_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM table_agro_field_assessments WHERE owner_id = ?",
                (owner_id,),
            )
        return int(cur.rowcount or 0)


class AgronomistProfileStore:
    """Profil officiel d'agronome / bureau d'études soumis par l'utilisateur et validé par l'admin."""

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
        self.db_path = Path(db_path or os.getenv("FREEDATA_AGRO_DB_PATH", "data/freedata_agro.db"))
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
                CREATE TABLE IF NOT EXISTS table_agro_official_profiles (
                    owner_id TEXT PRIMARY KEY,
                    firm_name TEXT NOT NULL,
                    license_number TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    contact TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    admin_note TEXT NOT NULL DEFAULT '',
                    submitted_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agro_profiles_status
                    ON table_agro_official_profiles(status, submitted_at DESC);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        return {
            "owner_id": d["owner_id"],
            "firm_name": d.get("firm_name") or "",
            "license_number": d.get("license_number") or "",
            "address": d.get("address") or "",
            "contact": d.get("contact") or "",
            "status": d.get("status") or "pending",
            "admin_note": d.get("admin_note") or "",
            "submitted_at": d.get("submitted_at"),
            "reviewed_at": d.get("reviewed_at"),
            "reviewed_by": d.get("reviewed_by"),
        }

    def get_profile(self, owner_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM table_agro_official_profiles WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def submit_profile(
        self,
        owner_id: str,
        *,
        firm_name: str,
        license_number: str,
        address: str = "",
        contact: str = "",
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO table_agro_official_profiles (
                    owner_id, firm_name, license_number, address, contact,
                    status, admin_note, submitted_at, reviewed_at, reviewed_by
                )
                VALUES (?, ?, ?, ?, ?, 'pending', '', ?, NULL, NULL)
                ON CONFLICT(owner_id) DO UPDATE SET
                    firm_name = excluded.firm_name,
                    license_number = excluded.license_number,
                    address = excluded.address,
                    contact = excluded.contact,
                    status = 'pending',
                    admin_note = '',
                    submitted_at = excluded.submitted_at,
                    reviewed_at = NULL,
                    reviewed_by = NULL
                """,
                (
                    owner_id,
                    firm_name.strip()[:120],
                    license_number.strip()[:120],
                    address.strip()[:200],
                    contact.strip()[:160],
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM table_agro_official_profiles WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_profiles(self, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        lim = max(1, min(200, int(limit)))
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM table_agro_official_profiles
                    WHERE status = ?
                    ORDER BY submitted_at DESC LIMIT ?
                    """,
                    (status.strip(), lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM table_agro_official_profiles
                    ORDER BY submitted_at DESC LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def review_profile(
        self,
        owner_id: str,
        *,
        status: str,
        admin_note: str = "",
        reviewed_by: str = "admin",
    ) -> dict[str, Any]:
        if status not in ("approved", "rejected"):
            raise ValueError("Statut invalide : 'approved' ou 'rejected' attendu.")
        now = _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE table_agro_official_profiles
                SET status = ?, admin_note = ?, reviewed_at = ?, reviewed_by = ?
                WHERE owner_id = ?
                """,
                (status, (admin_note or "").strip()[:400], now, reviewed_by[:80], owner_id),
            )
            if (cur.rowcount or 0) == 0:
                raise KeyError("Profil agronome introuvable.")
            row = conn.execute(
                "SELECT * FROM table_agro_official_profiles WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def purge_owner(self, owner_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM table_agro_official_profiles WHERE owner_id = ?",
                (owner_id,),
            )
        return int(cur.rowcount or 0)

