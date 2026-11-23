"""Safety and concurrency tests for the in-process report job manager."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.reports.jobs import ReportJobManager, ReportJobQueueFull


def _wait_for(manager, owner, job_id, status, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = manager.get_status(owner, job_id)
        if current["status"] == status:
            return current
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not reach {status}")


def test_idempotency_key_is_atomic_for_concurrent_submissions():
    manager = ReportJobManager(max_workers=1, max_active_jobs=5)
    gate = threading.Event()
    started = threading.Event()

    def task(progress):
        started.set()
        gate.wait(1)
        return {"pdf_bytes": b"%PDF-test"}

    try:
        with ThreadPoolExecutor(max_workers=8) as callers:
            results = list(callers.map(lambda _: manager.submit("owner-a", task, idempotency_key="same-request"), range(8)))
        assert len({item["job_id"] for item in results}) == 1
        assert started.wait(1)
        gate.set()
        _wait_for(manager, "owner-a", results[0]["job_id"], "completed")
    finally:
        gate.set()
        manager._executor.shutdown(wait=True)


def test_queue_rejects_new_work_when_active_capacity_is_full():
    manager = ReportJobManager(max_workers=1, max_active_jobs=1)
    gate = threading.Event()
    started = threading.Event()

    def blocking_task(progress):
        started.set()
        gate.wait(1)
        return {"pdf_bytes": b"%PDF-test"}

    try:
        first = manager.submit("owner-a", blocking_task)
        assert started.wait(1)
        with pytest.raises(ReportJobQueueFull):
            manager.submit("owner-b", lambda progress: {"pdf_bytes": b"%PDF-other"})
        gate.set()
        _wait_for(manager, "owner-a", first["job_id"], "completed")
    finally:
        gate.set()
        manager._executor.shutdown(wait=True)


def test_pruning_never_removes_active_jobs():
    manager = ReportJobManager(max_workers=1, max_active_jobs=3, max_retained_jobs=3)
    gate = threading.Event()
    started = threading.Event()

    def blocking_task(progress):
        started.set()
        gate.wait(1)
        return {"pdf_bytes": b"%PDF-active"}

    try:
        active = manager.submit("owner-a", blocking_task)
        assert started.wait(1)
        # Seed old terminal records to trigger retention pruning without relying on timing.
        with manager._lock:
            for index in range(4):
                manager._jobs[f"OLD-{index}"] = {
                    "job_id": f"OLD-{index}", "owner_id": "owner-a", "status": "completed",
                    "created_at": f"2000-01-0{index + 1}", "updated_at": f"2000-01-0{index + 1}",
                    "pdf_bytes": b"old", "_fn": lambda progress: {},
                }
        # Trigger pruning with another admitted job.
        other = manager.submit("owner-b", lambda progress: {"pdf_bytes": b"%PDF-other"})
        assert manager.get_status("owner-a", active["job_id"])["status"] in ("queued", "running")
        gate.set()
        _wait_for(manager, "owner-a", active["job_id"], "completed")
        _wait_for(manager, "owner-b", other["job_id"], "completed")
    finally:
        gate.set()
        manager._executor.shutdown(wait=True)


def test_job_status_and_pdf_remain_owner_scoped():
    manager = ReportJobManager(max_workers=1)
    try:
        job = manager.submit("owner-a", lambda progress: {"pdf_bytes": b"%PDF-owner-a"})
        _wait_for(manager, "owner-a", job["job_id"], "completed")
        with pytest.raises(KeyError):
            manager.get_status("owner-b", job["job_id"])
        with pytest.raises(KeyError):
            manager.get_pdf("owner-b", job["job_id"])
        assert manager.get_pdf("owner-a", job["job_id"]) == b"%PDF-owner-a"
    finally:
        manager._executor.shutdown(wait=True)
