"""Reproducible Experiment Tracking, Dataset Provenance, and Innovation Backlog."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compute_file_sha256(path: str | Path) -> str:
    """Computes SHA-256 hex digest of a dataset file for provenance tracking."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class DatasetProvenance:
    """Immutable metadata describing a dataset snapshot used in an experiment."""

    dataset_id: str
    source_path: str
    sha256: str
    row_count: int
    date_range: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VALID_EXPERIMENT_STATUSES = {"experimental", "validated", "rejected", "promoted"}
VALID_BACKLOG_STAGES = {
    "proposed",
    "feasibility_checked",
    "prototype",
    "validated",
    "integrated",
    "archived",
}


class ExperimentTracker:
    """SQLite-backed experiment ledger recording baselines, candidate metrics, splits, and decisions."""

    def __init__(self, db_path: str | Path = "data/research/experiments.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    date_range TEXT,
                    notes TEXT,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    split_protocol TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    baseline_metrics_json TEXT NOT NULL,
                    candidate_metrics_json TEXT NOT NULL,
                    delta_metrics_json TEXT NOT NULL,
                    limitations TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(dataset_id) REFERENCES datasets(dataset_id)
                );
                CREATE TABLE IF NOT EXISTS innovation_backlog (
                    idea_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    problem_statement TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    data_available INTEGER NOT NULL,
                    estimated_cost TEXT NOT NULL,
                    linked_experiment_id TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def register_dataset(self, prov: DatasetProvenance) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets (dataset_id, source_path, sha256, row_count, date_range, notes, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    sha256=excluded.sha256,
                    row_count=excluded.row_count,
                    date_range=excluded.date_range,
                    notes=excluded.notes
                """,
                (prov.dataset_id, prov.source_path, prov.sha256, prov.row_count, prov.date_range, prov.notes, _utc_now()),
            )
        return prov.to_dict()

    def log_experiment(
        self,
        *,
        name: str,
        domain: str,
        hypothesis: str,
        dataset_id: str,
        method: str,
        parameters: dict[str, Any],
        split_protocol: str,
        seed: int,
        baseline_metrics: dict[str, float],
        candidate_metrics: dict[str, float],
        limitations: str,
        status: str = "experimental",
    ) -> dict[str, Any]:
        if status not in VALID_EXPERIMENT_STATUSES:
            raise ValueError(f"Invalid experiment status: {status}")

        delta = {
            k: round(float(candidate_metrics[k]) - float(baseline_metrics[k]), 4)
            for k in candidate_metrics
            if k in baseline_metrics and isinstance(candidate_metrics[k], (int, float)) and isinstance(baseline_metrics[k], (int, float))
        }
        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments (
                    experiment_id, name, domain, hypothesis, dataset_id, method,
                    parameters_json, split_protocol, seed,
                    baseline_metrics_json, candidate_metrics_json, delta_metrics_json,
                    limitations, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp_id,
                    name,
                    domain,
                    hypothesis,
                    dataset_id,
                    method,
                    json.dumps(parameters, sort_keys=True),
                    split_protocol,
                    int(seed),
                    json.dumps(baseline_metrics, sort_keys=True),
                    json.dumps(candidate_metrics, sort_keys=True),
                    json.dumps(delta, sort_keys=True),
                    limitations,
                    status,
                    now,
                ),
            )
        return {
            "experiment_id": exp_id,
            "name": name,
            "domain": domain,
            "dataset_id": dataset_id,
            "method": method,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "delta_metrics": delta,
            "status": status,
            "created_at": now,
        }

    def update_experiment_status(self, experiment_id: str, status: str) -> None:
        if status not in VALID_EXPERIMENT_STATUSES:
            raise ValueError(f"Invalid experiment status: {status}")
        with self._connect() as conn:
            cur = conn.execute("UPDATE experiments SET status = ? WHERE experiment_id = ?", (status, experiment_id))
            if cur.rowcount == 0:
                raise KeyError(f"Experiment not found: {experiment_id}")

    def list_experiments(self, domain: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM experiments"
        params: tuple[Any, ...] = ()
        if domain:
            query += " WHERE domain = ?"
            params = (domain,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        out = []
        for r in rows:
            out.append({
                "experiment_id": r["experiment_id"],
                "name": r["name"],
                "domain": r["domain"],
                "hypothesis": r["hypothesis"],
                "dataset_id": r["dataset_id"],
                "method": r["method"],
                "parameters": json.loads(r["parameters_json"]),
                "split_protocol": r["split_protocol"],
                "seed": r["seed"],
                "baseline_metrics": json.loads(r["baseline_metrics_json"]),
                "candidate_metrics": json.loads(r["candidate_metrics_json"]),
                "delta_metrics": json.loads(r["delta_metrics_json"]),
                "limitations": r["limitations"],
                "status": r["status"],
                "created_at": r["created_at"],
            })
        return out


class InnovationBacklog:
    """Manages research ideas from proposal through validation without polluting production."""

    def __init__(self, tracker: ExperimentTracker) -> None:
        self.tracker = tracker

    def add_idea(
        self,
        *,
        title: str,
        domain: str,
        problem_statement: str,
        priority: str = "P2",
        data_available: bool = True,
        estimated_cost: str = "low",
        stage: str = "proposed",
    ) -> dict[str, Any]:
        if stage not in VALID_BACKLOG_STAGES:
            raise ValueError(f"Invalid backlog stage: {stage}")
        idea_id = f"idea_{uuid.uuid4().hex[:10]}"
        now = _utc_now()
        with self.tracker._connect() as conn:
            conn.execute(
                """
                INSERT INTO innovation_backlog (
                    idea_id, title, domain, problem_statement, stage,
                    priority, data_available, estimated_cost, linked_experiment_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (idea_id, title, domain, problem_statement, stage, priority, int(data_available), estimated_cost, now),
            )
        return {"idea_id": idea_id, "title": title, "domain": domain, "stage": stage, "priority": priority}

    def transition_stage(self, idea_id: str, stage: str, linked_experiment_id: Optional[str] = None) -> None:
        if stage not in VALID_BACKLOG_STAGES:
            raise ValueError(f"Invalid backlog stage: {stage}")
        with self.tracker._connect() as conn:
            cur = conn.execute(
                """
                UPDATE innovation_backlog
                SET stage = ?, linked_experiment_id = COALESCE(?, linked_experiment_id), updated_at = ?
                WHERE idea_id = ?
                """,
                (stage, linked_experiment_id, _utc_now(), idea_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Idea not found: {idea_id}")

    def list_ideas(self, stage: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM innovation_backlog"
        params: tuple[Any, ...] = ()
        if stage:
            query += " WHERE stage = ?"
            params = (stage,)
        query += " ORDER BY priority ASC, updated_at DESC"
        with self.tracker._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

