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


class ReportJobQueueFull(RuntimeError):
    """Raised when the bounded report-job queue has no remaining capacity."""


class ReportJobManager:
    """Thread-pool background job runner with bounded admission and owner-scoped status."""

    def __init__(
        self,
        max_workers: int = 2,
        default_timeout_seconds: float = 120.0,
        max_active_jobs: int = 50,
        max_retained_jobs: int = 200,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.default_timeout_seconds = max(1.0, float(default_timeout_seconds))
        self.max_active_jobs = max(self.max_workers, int(max_active_jobs))
        self.max_retained_jobs = max(self.max_active_jobs, int(max_retained_jobs))
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="fd-pdf-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in record.items() if k not in ("pdf_bytes", "owner_id", "_fn")}

    def _prune_terminal_jobs_locked(self) -> None:
        """Prune only completed/failed records; never evict a queued or running job."""
        terminal = [
            (job_id, record)
            for job_id, record in self._jobs.items()
            if record.get("status") in ("completed", "failed")
        ]
        excess = len(self._jobs) - self.max_retained_jobs
        if excess <= 0:
            return
        terminal.sort(key=lambda item: item[1].get("updated_at", item[1].get("created_at", "")))
        for job_id, _ in terminal[:excess]:
            self._jobs.pop(job_id, None)

    def _ensure_capacity_locked(self) -> None:
        active = sum(1 for record in self._jobs.values() if record.get("status") in ("queued", "running"))
        if active >= self.max_active_jobs:
            raise ReportJobQueueFull("La file de génération PDF est temporairement saturée. Réessayez plus tard.")

    def submit(
        self,
        owner_id: str,
        fn: Callable[[Callable[[int], None]], dict[str, Any]],
        *,
        max_retries: int = 1,
        idempotency_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
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
            "max_retries": max(0, int(max_retries)),
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
            # Deduplication and insertion share one critical section: concurrent submits cannot race.
            if idempotency_key:
                for existing in self._jobs.values():
                    if (
                        existing["owner_id"] == owner_id
                        and existing.get("idempotency_key") == idempotency_key
                        and existing["status"] in ("queued", "running")
                    ):
                        return self._public_record(existing)
            self._prune_terminal_jobs_locked()
            self._ensure_capacity_locked()
            self._jobs[job_id] = record

        try:
            self._dispatch(job_id, fn, eff_timeout)
        except Exception as exc:
            with self._lock:
                current = self._jobs.get(job_id)
                if current:
                    current["status"] = "failed"
                    current["error"] = f"Impossible de planifier le job : {exc}"
                    current["updated_at"] = _utc_now()
            raise
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
            self._ensure_capacity_locked()
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
            return self._public_record(rec)

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
            "max_active_jobs": self.max_active_jobs,
            "default_timeout_seconds": self.default_timeout_seconds,
            "total_tracked_jobs": total,
            "by_status": counts,
        }
