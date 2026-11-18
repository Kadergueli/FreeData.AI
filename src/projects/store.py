"""SQLite-backed persistent ProjectStore with strict owner_id isolation and versioned studies."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.study_context import StudyContext


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectStore:
    """Thread-safe persistent store for projects, StudyContext, conversations, and study versions."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        artifacts_dir: Optional[str] = None,
    ) -> None:
        default_db = os.getenv("FREEDATA_PROJECT_DB_PATH", "data/freedata_projects.db")
        default_art = os.getenv("FREEDATA_ARTIFACTS_DIR", "data/artifacts")
        self.db_path = Path(db_path or default_db)
        self.artifacts_dir = Path(artifacts_dir or default_art)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_projects_owner_updated
                    ON projects (owner_id, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_idempotency
                    ON projects (owner_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;

                CREATE TABLE IF NOT EXISTS project_contexts (
                    project_id TEXT PRIMARY KEY REFERENCES projects (project_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    study_context_json TEXT NOT NULL,
                    context_version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proj_conv_project
                    ON project_conversations (project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES project_conversations (conversation_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proj_msg_conv
                    ON project_messages (conversation_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS studies (
                    study_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    commodity TEXT NOT NULL,
                    origin_province TEXT NOT NULL,
                    dest_province TEXT,
                    latest_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studies_project
                    ON studies (project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS study_versions (
                    version_id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL REFERENCES studies (study_id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
                    owner_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    context_snapshot_json TEXT NOT NULL,
                    data_snapshot_json TEXT NOT NULL,
                    generation_params_json TEXT NOT NULL,
                    dossier_json TEXT NOT NULL,
                    validation_result_json TEXT NOT NULL,
                    artifact_path TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (study_id, version_number)
                );
                CREATE INDEX IF NOT EXISTS idx_study_versions_study
                    ON study_versions (study_id, version_number DESC);
                """
            )

    def create_project(
        self,
        owner_id: str,
        name: str,
        description: str = "",
        study_context: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Le nom du projet est requis.")

        with self._connect() as conn:
            if idempotency_key:
                existing = conn.execute(
                    "SELECT project_id FROM projects WHERE owner_id = ? AND idempotency_key = ?",
                    (owner_id, idempotency_key),
                ).fetchone()
                if existing:
                    return self.get_project(owner_id, existing["project_id"])

            project_id = f"PRJ-{uuid.uuid4().hex[:10].upper()}"
            ctx = StudyContext.from_dict(study_context) if study_context else StudyContext()
            conn.execute(
                """
                INSERT INTO projects (project_id, owner_id, name, description, status, idempotency_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (project_id, owner_id, clean_name, description.strip(), idempotency_key, now, now),
            )
            conn.execute(
                """
                INSERT INTO project_contexts (project_id, owner_id, study_context_json, context_version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, owner_id, ctx.to_json(), ctx.context_version, now),
            )
        return self.get_project(owner_id, project_id)

    def list_projects(
        self,
        owner_id: str,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT project_id, owner_id, name, description, status, created_at, updated_at, archived_at "
            "FROM projects WHERE owner_id = ?"
        )
        params: list[Any] = [owner_id]
        if not include_archived:
            query += " AND status = 'active'"
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["studies_count"] = conn.execute(
                    "SELECT COUNT(*) FROM studies WHERE project_id = ? AND owner_id = ?",
                    (d["project_id"], owner_id),
                ).fetchone()[0]
                out.append(d)
            return out

    def get_project(self, owner_id: str, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            proj = conn.execute(
                "SELECT * FROM projects WHERE project_id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
            if not proj:
                raise KeyError(f"Projet introuvable : {project_id}")

            ctx_row = conn.execute(
                "SELECT study_context_json, context_version, updated_at FROM project_contexts WHERE project_id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
            convs = conn.execute(
                "SELECT conversation_id, title, created_at, updated_at FROM project_conversations WHERE project_id = ? AND owner_id = ? ORDER BY updated_at DESC",
                (project_id, owner_id),
            ).fetchall()
            studies = conn.execute(
                "SELECT study_id, title, commodity, origin_province, dest_province, latest_version, created_at, updated_at "
                "FROM studies WHERE project_id = ? AND owner_id = ? ORDER BY updated_at DESC",
                (project_id, owner_id),
            ).fetchall()
            return {
                **dict(proj),
                "study_context": json.loads(ctx_row["study_context_json"]) if ctx_row else StudyContext().to_dict(),
                "conversations": [dict(c) for c in convs],
                "studies": [dict(s) for s in studies],
            }

    def update_project(
        self,
        owner_id: str,
        project_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        study_context: Optional[dict] = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            proj = conn.execute(
                "SELECT * FROM projects WHERE project_id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
            if not proj:
                raise KeyError(f"Projet introuvable : {project_id}")

            new_name = name.strip() if name is not None and name.strip() else proj["name"]
            new_desc = description.strip() if description is not None else proj["description"]
            new_status = status if status in ("active", "archived") else proj["status"]
            archived_at = now if new_status == "archived" and proj["status"] != "archived" else (None if new_status == "active" else proj["archived_at"])

            conn.execute(
                "UPDATE projects SET name = ?, description = ?, status = ?, updated_at = ?, archived_at = ? WHERE project_id = ? AND owner_id = ?",
                (new_name, new_desc, new_status, now, archived_at, project_id, owner_id),
            )
            if study_context is not None:
                ctx = StudyContext.from_dict(study_context)
                conn.execute(
                    """
                    INSERT INTO project_contexts (project_id, owner_id, study_context_json, context_version, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (project_id) DO UPDATE SET
                        study_context_json = excluded.study_context_json,
                        context_version = excluded.context_version,
                        updated_at = excluded.updated_at
                    """,
                    (project_id, owner_id, ctx.to_json(), ctx.context_version, now),
                )
        return self.get_project(owner_id, project_id)

    def delete_project(self, owner_id: str, project_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM projects WHERE project_id = ? AND owner_id = ?",
                (project_id, owner_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Projet introuvable : {project_id}")

    def create_conversation(self, owner_id: str, project_id: str, title: str = "Nouvelle conversation") -> dict[str, Any]:
        self.get_project(owner_id, project_id)
        now = _utc_now()
        conv_id = f"CONV-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO project_conversations (conversation_id, project_id, owner_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (conv_id, project_id, owner_id, title.strip() or "Nouvelle conversation", now, now),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE project_id = ? AND owner_id = ?", (now, project_id, owner_id))
        return {"conversation_id": conv_id, "project_id": project_id, "title": title, "created_at": now, "updated_at": now}

    def add_message(
        self,
        owner_id: str,
        project_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        updated_study_context: Optional[dict] = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        msg_id = f"MSG-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conv = conn.execute(
                "SELECT * FROM project_conversations WHERE conversation_id = ? AND project_id = ? AND owner_id = ?",
                (conversation_id, project_id, owner_id),
            ).fetchone()
            if not conv:
                raise KeyError(f"Conversation introuvable : {conversation_id}")
            conn.execute(
                "INSERT INTO project_messages (message_id, conversation_id, owner_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, conversation_id, owner_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            conn.execute("UPDATE project_conversations SET updated_at = ? WHERE conversation_id = ?", (now, conversation_id))
            conn.execute("UPDATE projects SET updated_at = ? WHERE project_id = ?", (now, project_id))
            if updated_study_context is not None:
                ctx = StudyContext.from_dict(updated_study_context)
                conn.execute(
                    "UPDATE project_contexts SET study_context_json = ?, context_version = ?, updated_at = ? WHERE project_id = ? AND owner_id = ?",
                    (ctx.to_json(), ctx.context_version, now, project_id, owner_id),
                )
        return {"message_id": msg_id, "conversation_id": conversation_id, "role": role, "content": content, "created_at": now}

    def get_conversation_messages(self, owner_id: str, project_id: str, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conv = conn.execute(
                "SELECT conversation_id FROM project_conversations WHERE conversation_id = ? AND project_id = ? AND owner_id = ?",
                (conversation_id, project_id, owner_id),
            ).fetchone()
            if not conv:
                raise KeyError(f"Conversation introuvable : {conversation_id}")
            rows = conn.execute(
                "SELECT message_id, role, content, metadata_json, created_at FROM project_messages WHERE conversation_id = ? AND owner_id = ? ORDER BY created_at ASC",
                (conversation_id, owner_id),
            ).fetchall()
            return [{**dict(r), "metadata": json.loads(r["metadata_json"])} for r in rows]

    def create_study_version(
        self,
        owner_id: str,
        project_id: str,
        *,
        study_id: Optional[str],
        dossier: dict[str, Any],
        generation_params: dict[str, Any],
        pdf_bytes: Optional[bytes] = None,
    ) -> dict[str, Any]:
        self.get_project(owner_id, project_id)
        now = _utc_now()
        comm = str(dossier.get("commodity") or generation_params.get("commodity") or "Commodity")
        comm_fr = str(dossier.get("commodity_fr") or comm)
        orig = str(dossier.get("origin_province") or generation_params.get("origin_province") or "-")
        dest = dossier.get("dest_province")
        title = f"{comm_fr} ({orig} -> {dest})" if dest else f"{comm_fr} ({orig})"

        with self._connect() as conn:
            if study_id:
                st_row = conn.execute(
                    "SELECT * FROM studies WHERE study_id = ? AND project_id = ? AND owner_id = ?",
                    (study_id, project_id, owner_id),
                ).fetchone()
                if not st_row:
                    raise KeyError(f"Etude introuvable : {study_id}")
                version_number = int(st_row["latest_version"]) + 1
                conn.execute(
                    "UPDATE studies SET latest_version = ?, updated_at = ? WHERE study_id = ?",
                    (version_number, now, study_id),
                )
            else:
                study_id = str(dossier.get("study_id") or f"FD-{uuid.uuid4().hex[:8].upper()}")
                version_number = 1
                conn.execute(
                    """
                    INSERT INTO studies (study_id, project_id, owner_id, title, commodity, origin_province, dest_province, latest_version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (study_id, project_id, owner_id, title, comm, orig, dest, now, now),
                )

            artifact_path: Optional[str] = None
            if pdf_bytes is not None:
                owner_hash = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]
                owner_dir = self.artifacts_dir / owner_hash
                owner_dir.mkdir(parents=True, exist_ok=True)
                art_file = owner_dir / f"{study_id}_v{version_number}.pdf"
                art_file.write_bytes(pdf_bytes)
                artifact_path = str(art_file)

            version_id = f"VER-{uuid.uuid4().hex[:10].upper()}"
            conn.execute(
                """
                INSERT INTO study_versions (
                    version_id, study_id, project_id, owner_id, version_number,
                    context_snapshot_json, data_snapshot_json, generation_params_json,
                    dossier_json, validation_result_json, artifact_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    study_id,
                    project_id,
                    owner_id,
                    version_number,
                    json.dumps(dossier.get("study_context") or {}, ensure_ascii=False),
                    json.dumps(dossier.get("data_traceability") or {}, ensure_ascii=False),
                    json.dumps(generation_params, ensure_ascii=False),
                    json.dumps(dossier, ensure_ascii=False),
                    json.dumps(dossier.get("validation") or {}, ensure_ascii=False),
                    artifact_path,
                    now,
                ),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE project_id = ?", (now, project_id))

        return {
            "version_id": version_id,
            "study_id": study_id,
            "project_id": project_id,
            "version_number": version_number,
            "artifact_available": artifact_path is not None,
            "validation": dossier.get("validation") or {},
            "created_at": now,
        }

    def list_study_versions(self, owner_id: str, project_id: str, study_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT version_id, study_id, version_number, generation_params_json, validation_result_json, artifact_path, created_at
                FROM study_versions
                WHERE owner_id = ? AND project_id = ? AND study_id = ?
                ORDER BY version_number DESC
                """,
                (owner_id, project_id, study_id),
            ).fetchall()
            if not rows:
                raise KeyError(f"Aucune version trouvee pour l'etude : {study_id}")
            out = []
            for r in rows:
                art = r["artifact_path"]
                out.append({
                    "version_id": r["version_id"],
                    "study_id": r["study_id"],
                    "version_number": r["version_number"],
                    "generation_params": json.loads(r["generation_params_json"]),
                    "validation": json.loads(r["validation_result_json"]),
                    "artifact_available": bool(art and Path(art).is_file()),
                    "created_at": r["created_at"],
                })
            return out

    def get_study_version_pdf(self, owner_id: str, project_id: str, study_id: str, version_number: int) -> bytes:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT artifact_path FROM study_versions WHERE owner_id = ? AND project_id = ? AND study_id = ? AND version_number = ?",
                (owner_id, project_id, study_id, version_number),
            ).fetchone()
            if not row:
                raise KeyError(f"Version introuvable : {study_id} v{version_number}")
            art = row["artifact_path"]
            if not art or not Path(art).is_file():
                raise FileNotFoundError(f"Artefact PDF manquant ou supprime pour {study_id} v{version_number}.")
            return Path(art).read_bytes()

    def compare_study_versions(self, owner_id: str, project_id: str, study_id: str, v1: int, v2: int) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version_number, dossier_json, validation_result_json, created_at FROM study_versions WHERE owner_id = ? AND project_id = ? AND study_id = ? AND version_number IN (?, ?)",
                (owner_id, project_id, study_id, v1, v2),
            ).fetchall()
        by_v = {int(r["version_number"]): r for r in rows}
        if v1 not in by_v or v2 not in by_v:
            raise KeyError(f"Versions {v1} et/ou {v2} introuvables pour {study_id}.")

        d1 = json.loads(by_v[v1]["dossier_json"])
        d2 = json.loads(by_v[v2]["dossier_json"])
        bp1, bp2 = d1.get("business_plan") or {}, d2.get("business_plan") or {}
        ca1, ca2 = bp1.get("capital_allocation") or {}, bp2.get("capital_allocation") or {}
        ue1, ue2 = bp1.get("unit_economics") or {}, bp2.get("unit_economics") or {}
        val1 = json.loads(by_v[v1]["validation_result_json"])
        val2 = json.loads(by_v[v2]["validation_result_json"])

        return {
            "study_id": study_id,
            "v1": v1,
            "v2": v2,
            "metrics_diff": {
                "capital_xaf": {"v1": ca1.get("total_capital_xaf"), "v2": ca2.get("total_capital_xaf")},
                "net_profit_cycle1_xaf": {"v1": ue1.get("net_profit_cycle1_xaf"), "v2": ue2.get("net_profit_cycle1_xaf")},
                "roi_cycle1_pct": {"v1": ue1.get("roi_cycle1_pct"), "v2": ue2.get("roi_cycle1_pct")},
                "break_even_price_per_kg": {"v1": ue1.get("break_even_price_per_kg"), "v2": ue2.get("break_even_price_per_kg")},
                "profitability_status": {"v1": ue1.get("profitability_status"), "v2": ue2.get("profitability_status")},
            },
            "validation_diff": {"v1": val1.get("overall_status"), "v2": val2.get("overall_status")},
            "instructions_diff": {
                "v1": d1.get("user_instructions") or [],
                "v2": d2.get("user_instructions") or [],
            },
        }

