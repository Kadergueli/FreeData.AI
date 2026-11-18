"""Lightweight asynchronous background job manager for long PDF report generation."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReportJobManager:
    """Thread-pool background job runner with owner-scoped status, progress, and artifact storage."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fd-pdf-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def submit(
        self,
        owner_id: str,
        fn: Callable[[Callable[[int], None]], dict[str, Any]],
        *,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"
        now = _utc_now()
        record = {
            "job_id": job_id,
            "owner_id": owner_id,
            "status": "queued",
            "progress_pct": 0,
            "attempts": 0,
            "max_retries": max_retries,
            "error": None,
            "validation": None,
            "pdf_bytes": None,
            "study_id": None,
            "version_number": None,
            "created_at": now,
            "updated_at": now,
            "_fn": fn,
        }
        with self._lock:
            if len(self._jobs) > 200:
                oldest = sorted(self._jobs.items(), key=lambda kv: kv[1]["created_at"])[:50]
                for k, _ in oldest:
                    self._jobs.pop(k, None)
            self._jobs[job_id] = record
        self._dispatch(job_id, fn)
        return self.get_status(owner_id, job_id)

    def _dispatch(self, job_id: str, fn: Callable[[Callable[[int], None]], dict[str, Any]]) -> None:
        def _update_progress(pct: int) -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "running"
                    self._jobs[job_id]["progress_pct"] = max(0, min(99, int(pct)))
                    self._jobs[job_id]["updated_at"] = _utc_now()

        def _run() -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["attempts"] += 1
                    self._jobs[job_id]["error"] = None
            _update_progress(15)
            try:
                res = fn(_update_progress)
                with self._lock:
                    if job_id in self._jobs:
                        self._jobs[job_id]["status"] = "completed"
                        self._jobs[job_id]["progress_pct"] = 100
                        self._jobs[job_id]["pdf_bytes"] = res.get("pdf_bytes")
                        self._jobs[job_id]["validation"] = res.get("validation")
                        self._jobs[job_id]["study_id"] = res.get("study_id")
                        self._jobs[job_id]["version_number"] = res.get("version_number")
                        self._jobs[job_id]["updated_at"] = _utc_now()
            except Exception as exc:
                with self._lock:
                    if job_id in self._jobs:
                        self._jobs[job_id]["status"] = "failed"
                        self._jobs[job_id]["error"] = str(exc)
                        self._jobs[job_id]["updated_at"] = _utc_now()

        self._executor.submit(_run)

    def retry_job(self, owner_id: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec or rec["owner_id"] != owner_id:
                raise KeyError(f"Job introuvable : {job_id}")
            if rec["status"] != "failed":
                raise ValueError("Seul un job en échec peut être relancé.")
            if rec["attempts"] > rec["max_retries"]:
                raise OverflowError("Nombre maximal de tentatives atteint.")
            rec["status"] = "queued"
            rec["progress_pct"] = 0
            rec["updated_at"] = _utc_now()
            fn = rec["_fn"]
        self._dispatch(job_id, fn)
        return self.get_status(owner_id, job_id)

    def get_status(self, owner_id: str, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec or rec["owner_id"] != owner_id:
                raise KeyError(f"Job introuvable : {job_id}")
            return {k: v for k, v in rec.items() if k not in ("pdf_bytes", "owner_id", "_fn")}

    def get_pdf(self, owner_id: str, job_id: str) -> bytes:
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec or rec["owner_id"] != owner_id:
                raise KeyError(f"Job introuvable : {job_id}")
            if rec["status"] != "completed" or not rec.get("pdf_bytes"):
                raise ValueError(f"PDF non disponible (statut: {rec['status']}).")
            return bytes(rec["pdf_bytes"])

