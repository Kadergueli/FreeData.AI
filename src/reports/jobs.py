"""Lightweight asynchronous background job manager for long PDF report generation."""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReportJobManager:
    """Thread-pool background job runner with owner-scoped status, idempotency deduplication,
    timeout tracking, retry policies, and operational visibility.
    """

    def __init__(self, max_workers: int = 2, default_timeout_seconds: float = 120.0) -> None:
        self.max_workers = max(1, int(max_workers))
        self.default_timeout_seconds = max(1.0, float(default_timeout_seconds))
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="fd-pdf-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def submit(
        self,
        owner_id: str,
        fn: Callable[[Callable[[int], None]], dict[str, Any]],
        *,
        max_retries: int = 1,
        idempotency_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        # Duplicate execution prevention: reuse active queued/running job with same (owner_id, idempotency_key)
        if idempotency_key:
            with self._lock:
                for existing in self._jobs.values():
                    if (
                        existing["owner_id"] == owner_id
                        and existing.get("idempotency_key") == idempotency_key
                        and existing["status"] in ("queued", "running")
                    ):
                        return {k: v for k, v in existing.items() if k not in ("pdf_bytes", "owner_id", "_fn")}

        job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"
        now = _utc_now()
        eff_timeout = float(timeout_seconds) if timeout_seconds is not None else self.default_timeout_seconds
        record = {
            "job_id": job_id,
            "owner_id": owner_id,
            "idempotency_key": idempotency_key,
            "status": "queued",
            "progress_pct": 0,
            "attempts": 0,
            "max_retries": max_retries,
            "timeout_seconds": eff_timeout,
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
        self._dispatch(job_id, fn, eff_timeout)
        return self.get_status(owner_id, job_id)

    def _dispatch(
        self,
        job_id: str,
        fn: Callable[[Callable[[int], None]], dict[str, Any]],
        timeout_seconds: float,
    ) -> None:
        def _update_progress(pct: int) -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "running"
                    self._jobs[job_id]["progress_pct"] = max(0, min(99, int(pct)))
                    self._jobs[job_id]["updated_at"] = _utc_now()

        def _run() -> None:
            t0 = time.monotonic()
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["attempts"] += 1
                    self._jobs[job_id]["error"] = None
            _update_progress(15)
            try:
                res = fn(_update_progress)
                elapsed = time.monotonic() - t0
                if elapsed > timeout_seconds:
                    raise TimeoutError(f"Job dépassé ({elapsed:.1f}s > {timeout_seconds:.1f}s).")
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
            eff_timeout = float(rec.get("timeout_seconds", self.default_timeout_seconds))
        self._dispatch(job_id, fn, eff_timeout)
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

    def summary(self) -> dict[str, Any]:
        """Non-PII operational summary for the Admin Control Center."""
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        with self._lock:
            for rec in self._jobs.values():
                st = rec.get("status", "failed")
                counts[st] = counts.get(st, 0) + 1
            total = len(self._jobs)
        return {
            "max_workers": self.max_workers,
            "default_timeout_seconds": self.default_timeout_seconds,
            "total_tracked_jobs": total,
            "by_status": counts,
        }
