from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.backup import (
    backup_model_artifacts,
    backup_sqlite_file,
    prune_old_backups,
    restore_sqlite_file,
    verify_sqlite_integrity,
)
from src.ml_engine import ModelRegistry
from src.reports.jobs import ReportJobManager


def test_ml_lazy_lru_loading_and_missing_artifact_handling(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), max_loaded_models=2)
    reg.save_model("m_a", {"weights": [1.0]}, {"mae": 10.0})
    reg.save_model("m_b", {"weights": [2.0]}, {"mae": 11.0})
    reg.save_model("m_c", {"weights": [3.0]}, {"mae": 12.0})

    # Nothing loaded into RAM until explicitly requested
    assert reg.loaded_models() == []

    reg.load_version("m_a", 1)
    reg.load_version("m_b", 1)
    assert len(reg.loaded_models()) == 2

    # Loading a 3rd model evicts the least-recently-used model (m_a)
    reg.load_version("m_c", 1)
    loaded_ids = [m["model_id"] for m in reg.loaded_models()]
    assert loaded_ids == ["m_b", "m_c"]

    assert reg.unload_model("m_b", 1) is True
    assert [m["model_id"] for m in reg.loaded_models()] == ["m_c"]

    # Missing artifact fails cleanly without crashing registry
    with pytest.raises(FileNotFoundError):
        reg.load_version("nonexistent_model", 99)

    summary = reg.summary()
    assert summary["stored_artifacts_count"] == 3
    assert summary["loaded_count"] == 1
    assert summary["max_loaded_models"] == 2


def test_ml_model_rollback_and_admin_endpoint(monkeypatch, tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "models"))
    reg.register_model(
        model_id="price_model",
        model_name="Price Model v1",
        domain="agriculture",
        algorithm="Ridge",
        task_type="forecasting",
        version=1,
        lifecycle_status="DEPLOYED",
        set_active=True,
    )
    reg.register_model(
        model_id="price_model",
        model_name="Price Model v2",
        domain="agriculture",
        algorithm="Ridge",
        task_type="forecasting",
        version=2,
        lifecycle_status="DEPLOYED",
        set_active=True,
    )
    reg.register_model(
        model_id="price_model",
        model_name="Price Model v3",
        domain="agriculture",
        algorithm="Ridge",
        task_type="forecasting",
        version=3,
        lifecycle_status="FAILED",
    )

    assert reg.select_model(model_id="price_model")["version"] == 2

    # Cannot rollback to a FAILED version
    with pytest.raises(ValueError):
        reg.rollback_model("price_model", 3)

    # Admin RBAC check + rollback to v1
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    monkeypatch.setattr(server, "_MODEL_REGISTRY", reg)

    with pytest.raises(HTTPException) as exc:
        server.admin_ai_rollback_model_endpoint(
            "price_model",
            server.AdminMLRollbackRequest(target_version=1, reason="latency spike"),
            actor_info=("analyst", "read_only_analyst"),
            admin=admin,
        )
    assert exc.value.status_code == 403

    rolled = server.admin_ai_rollback_model_endpoint(
        "price_model",
        server.AdminMLRollbackRequest(target_version=1, reason="latency spike"),
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert rolled["version"] == 1
    assert rolled["is_active_production"] is True
    assert reg.select_model(model_id="price_model")["version"] == 1

    versions = reg.compare_versions("price_model")
    v2 = [v for v in versions if v["version"] == 2][0]
    assert v2["lifecycle_status"] == "DEPRECATED"
    assert v2["is_active_production"] is False
    assert any(a["action"] == "rollback_ml_model" for a in admin.list_audit_logs(limit=10))


def test_background_jobs_idempotency_timeout_retry_and_summary():
    mgr = ReportJobManager(max_workers=2, default_timeout_seconds=5.0)

    # 1. Idempotency deduplication prevents duplicate concurrent execution
    def _slow_ok(progress):
        progress(50)
        time.sleep(0.15)
        return {"pdf_bytes": b"%PDF-1.4 ok", "study_id": "S1", "version_number": 1}

    j1 = mgr.submit("u1", _slow_ok, idempotency_key="study-S1")
    j2 = mgr.submit("u1", _slow_ok, idempotency_key="study-S1")
    assert j1["job_id"] == j2["job_id"]

    # Wait for completion
    for _ in range(30):
        st = mgr.get_status("u1", j1["job_id"])
        if st["status"] == "completed":
            break
        time.sleep(0.03)
    assert mgr.get_status("u1", j1["job_id"])["status"] == "completed"
    assert mgr.get_pdf("u1", j1["job_id"]) == b"%PDF-1.4 ok"

    # 2. Timeout enforcement marks job failed, and retry succeeds
    attempts = {"n": 0}

    def _flaky(progress):
        attempts["n"] += 1
        if attempts["n"] == 1:
            time.sleep(0.08)
        return {"pdf_bytes": b"%PDF-1.4 retry"}

    jf = mgr.submit("u1", _flaky, max_retries=1, timeout_seconds=0.02)
    for _ in range(30):
        if mgr.get_status("u1", jf["job_id"])["status"] == "failed":
            break
        time.sleep(0.02)
    assert mgr.get_status("u1", jf["job_id"])["status"] == "failed"

    summary = mgr.summary()
    assert summary["max_workers"] == 2
    assert summary["by_status"]["completed"] >= 1
    assert summary["by_status"]["failed"] >= 1


def test_backup_restore_integrity_retention_and_model_artifacts(tmp_path: Path):
    src_db = tmp_path / "app.db"
    with sqlite3.connect(str(src_db)) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO items (val) VALUES ('preserved_row')")
        conn.commit()

    b_dir = tmp_path / "backups"
    res = backup_sqlite_file(src_db, b_dir)
    assert res["status"] == "verified"
    assert res["integrity_ok"] is True

    # Restore onto a fresh target and verify data survived intact
    restored_db = tmp_path / "restored.db"
    r_res = restore_sqlite_file(Path(res["backup_path"]), restored_db)
    assert r_res["status"] == "restored"
    with sqlite3.connect(str(restored_db)) as conn:
        row = conn.execute("SELECT val FROM items").fetchone()
        assert row == ("preserved_row",)

    # Corrupted backup must be rejected before touching target
    corrupt = b_dir / "corrupt.db"
    corrupt.write_bytes(b"not a valid sqlite database file")
    assert verify_sqlite_integrity(corrupt) is False
    with pytest.raises(ValueError):
        restore_sqlite_file(corrupt, tmp_path / "never_written.db")

    # Retention pruning keeps only the newest N backups
    for i in range(5):
        p = b_dir / f"old_{i}.db"
        p.write_bytes(b"x")
    removed = prune_old_backups(b_dir, keep_last=2)
    assert len(removed) >= 4

    # Model artifact backup creates SHA-256 manifest
    m_dir = tmp_path / "models"
    reg = ModelRegistry(models_dir=str(m_dir))
    reg.save_model("ridge", {"weights": [0.5]}, {"mae": 12.0})
    m_bak = backup_model_artifacts(m_dir, tmp_path / "model_backups")
    assert m_bak["status"] == "verified"
    assert m_bak["files_backed_up"] >= 2
    assert (Path(m_bak["snapshot_dir"]) / "manifest.sha256.json").is_file()


def test_admin_overview_operational_visibility_and_env_config(tmp_path: Path):
    cfg = server.settings
    assert cfg.global_rate_limit_per_min > 0
    assert cfg.chat_max_concurrency > 0

    admin = server.AdminService(db_path=tmp_path / "admin.db")
    sub_store = server.SubscriptionStore(db_path=tmp_path / "subs.db")
    auth_store = server.AuthStore(db_path=tmp_path / "auth.db")
    registry = server.LicensingRegistry()
    state = {
        "mode": "gold_ml",
        "agent": object(),
        "forecast_df": pd.DataFrame([{"commodity_name": "Riz", "forecast_price": 450.0}]),
        "freshness": {"forecasts": {"latest_observation_month": "2026-10", "data_age_months": 1, "freshness_status": "fresh"}},
    }
    ov = server.admin_overview_endpoint(
        live_probe=False,
        actor_info=("kader", "super_admin"),
        state=state,
        admin=admin,
        sub_store=sub_store,
        auth_store=auth_store,
        registry=registry,
    )
    assert "deployment_info" in ov and ov["deployment_info"]["started_at_utc"]
    assert "background_jobs_summary" in ov
    assert "storage_summary" in ov and ov["storage_summary"]["persistence_backend"] in ("supabase_postgresql", "local_sqlite")
    assert "currently_loaded_models" in ov["ml_registry_summary"]
