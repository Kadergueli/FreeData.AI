from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.domains import DomainRegistry
from src.ml_benchmark import (
    BenchmarkJobManager,
    DatasetSpec,
    parse_and_validate_csv,
    reconstruct_and_predict,
    run_csv_benchmark,
)
from src.ml_engine import ModelRegistry


def _reg_csv(n: int = 36) -> bytes:
    rng = np.random.default_rng(123)
    rows = ["x1,x2,y"]
    for _ in range(n):
        x1 = float(rng.uniform(1, 20))
        x2 = float(rng.uniform(2, 30))
        y = 5.0 + 3.0 * x1 - 0.8 * x2 + float(rng.normal(0, 0.2))
        rows.append(f"{x1:.3f},{x2:.3f},{y:.3f}")
    return ("\n".join(rows) + "\n").encode("utf-8-sig")  # UTF-8-SIG BOM verified


def _clf_csv(n: int = 36) -> bytes:
    rows = ["cv,dd,label"]
    for i in range(n):
        rows.append(f"{4 + (i % 3)},{1 + (i % 2)},0" if i % 2 == 0 else f"{24 + (i % 5)},{16 + (i % 4)},1")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _cluster_csv(n: int = 24) -> bytes:
    rows = ["p,v"]
    for i in range(n):
        base = 200 if i < 8 else (450 if i < 16 else 700)
        rows.append(f"{base + (i % 4) * 3},{5 + (i // 8) * 10}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def test_e2e_csv_utf8_sig_invalid_private_and_feature_fingerprint_dedup(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "m"), db_path=str(tmp_path / "m.db"))

    # 1. Valid UTF-8-SIG CSV ingestion & dedup with same vs different feature_columns
    spec_a = DatasetSpec(domain="finance", task_type="regression", target_column="y", feature_columns=["x1", "x2"])
    spec_b = DatasetSpec(domain="finance", task_type="regression", target_column="y", feature_columns=["x1"])
    csv_bytes = _reg_csv()

    r1 = run_csv_benchmark(csv_bytes, spec_a, registry=reg)
    r1_dup = run_csv_benchmark(csv_bytes, spec_a, registry=reg)
    assert all(c["deduplicated"] is True for c in r1_dup["candidates"])

    # Materially different feature_columns on SAME CSV must NOT merge with spec_a!
    r2 = run_csv_benchmark(csv_bytes, spec_b, registry=reg)
    assert all(c["deduplicated"] is False for c in r2["candidates"])
    assert all(c["version"] == 2 for c in r2["candidates"])

    # 2. Invalid CSV & private dataset rejected
    with pytest.raises(PermissionError):
        parse_and_validate_csv(
            csv_bytes,
            DatasetSpec(domain="finance", task_type="regression", target_column="y", feature_columns=["x1"], dataset_scope="user_private"),
        )
    with pytest.raises(ValueError):
        parse_and_validate_csv(b"\xff\xfe\x00invalid", spec_a)


def test_e2e_artifact_reconstruction_across_all_task_types(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "m"), db_path=str(tmp_path / "m.db"))

    # Regression artifact -> reconstruct & predict
    reg_res = run_csv_benchmark(
        _reg_csv(),
        DatasetSpec(domain="business_entrepreneurship", task_type="regression", target_column="y", feature_columns=["x1", "x2"]),
        registry=reg,
    )
    ridge_c = next(c for c in reg_res["candidates"] if c["algorithm"] == "ridge_l2")
    art_reg = reg.load_version(ridge_c["model_id"], ridge_c["version"])["artifact"]
    preds_reg = reconstruct_and_predict(art_reg, np.array([[10.0, 10.0], [5.0, 5.0]]))
    assert preds_reg.shape == (2,) and np.all(np.isfinite(preds_reg))

    # Classification artifact -> reconstruct & predict
    clf_res = run_csv_benchmark(
        _clf_csv(),
        DatasetSpec(domain="finance", task_type="classification", target_column="label", feature_columns=["cv", "dd"]),
        registry=reg,
    )
    log_c = next(c for c in clf_res["candidates"] if c["algorithm"] == "logistic_l2")
    art_clf = reg.load_version(log_c["model_id"], log_c["version"])["artifact"]
    preds_clf = reconstruct_and_predict(art_clf, np.array([[4.0, 1.0], [26.0, 18.0]]))
    assert preds_clf.tolist() == [0, 1]

    # Clustering artifact -> reconstruct & predict
    cl_res = run_csv_benchmark(
        _cluster_csv(),
        DatasetSpec(domain="data_science", task_type="clustering", feature_columns=["p", "v"]),
        registry=reg,
    )
    km_c = next(c for c in cl_res["candidates"] if c["algorithm"] == "kmeans_k3")
    art_km = reg.load_version(km_c["model_id"], km_c["version"])["artifact"]
    preds_km = reconstruct_and_predict(art_km, np.array([[200.0, 5.0], [700.0, 25.0]]))
    assert preds_km.shape == (2,) and preds_km[0] != preds_km[1]

    # Untrusted / unknown artifact type strictly rejected
    with pytest.raises(ValueError, match="non reconnu"):
        reconstruct_and_predict({"model_type": "PickleExecEvil"}, np.array([[1.0]]))


def test_e2e_cooperative_timeout_stops_execution_early(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "m"), db_path=str(tmp_path / "m.db"))
    cancel_evt = threading.Event()
    cancel_evt.set()  # Simulate expired/cancelled job
    with pytest.raises(TimeoutError):
        run_csv_benchmark(
            _reg_csv(),
            DatasetSpec(domain="finance", task_type="regression", target_column="y", feature_columns=["x1", "x2"]),
            registry=reg,
            cancel_event=cancel_evt,
        )
    # Zero partial models registered when cancelled before completion
    assert reg.list_models() == []


def test_e2e_full_lifecycle_approval_deploy_rollback_domain_monitoring_and_rbac(monkeypatch, tmp_path: Path):
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    sub_store = server.SubscriptionStore(db_path=tmp_path / "subs.db")
    auth_store = server.AuthStore(db_path=tmp_path / "auth.db")
    lic_reg = server.LicensingRegistry()
    ml_reg = ModelRegistry(models_dir=str(tmp_path / "ml"), db_path=str(tmp_path / "ml.db"))
    bench_mgr = BenchmarkJobManager(max_concurrent=1, timeout_seconds=30.0)

    monkeypatch.setattr(server, "_MODEL_REGISTRY", ml_reg)
    monkeypatch.setattr(server, "_BENCHMARK_JOB_MANAGER", bench_mgr)

    # 1. Authorized admin launches CSV benchmark
    req = server.AdminBenchmarkRequest(
        domain="finance",
        task_type="regression",
        target_column="y",
        feature_columns=["x1", "x2"],
        dataset_name="e2e_fin.csv",
        dataset_scope="platform_public",
        csv_base64=base64.b64encode(_reg_csv(32)).decode("ascii"),
    )
    job = server.admin_ai_launch_benchmark_endpoint(req, actor_info=("kader", "super_admin"), admin=admin)
    for _ in range(50):
        st = server.admin_ai_get_benchmark_endpoint(job["job_id"], actor_info=("kader", "super_admin"), admin=admin)
        if st["status"] in ("completed", "failed", "timed_out"):
            break
        time.sleep(0.03)
    assert st["status"] == "completed"
    ridge_id = next(c["model_id"] for c in st["result"]["candidates"] if c["algorithm"] == "ridge_l2")

    # 2. Candidate stays in EVALUATION (no automatic deployment)
    with pytest.raises(LookupError):
        ml_reg.select_model(model_id=ridge_id)

    # 3. Read-only analyst CANNOT deploy, rollback, or toggle domain (403)
    with pytest.raises(HTTPException) as e_dep:
        server.admin_ai_transition_model_endpoint(
            ridge_id,
            server.AdminMLModelStatusRequest(version=1, lifecycle_status="DEPLOYED", set_active=True),
            actor_info=("amina", "read_only_analyst"),
            admin=admin,
        )
    assert e_dep.value.status_code == 403

    with pytest.raises(HTTPException) as e_dom:
        server.admin_ai_set_domain_status_endpoint(
            "education",
            server.AdminDomainStatusRequest(active=False, reason="test"),
            actor_info=("amina", "read_only_analyst"),
            admin=admin,
        )
    assert e_dom.value.status_code == 403

    # 4. Super admin approves & deploys v1 -> then registers & deploys v2 -> then rolls back to v1
    dep1 = server.admin_ai_transition_model_endpoint(
        ridge_id,
        server.AdminMLModelStatusRequest(version=1, lifecycle_status="DEPLOYED", set_active=True, reason="approve v1"),
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert dep1["lifecycle_status"] == "DEPLOYED" and dep1["is_active_production"] is True

    ml_reg.register_model(
        model_id=ridge_id,
        model_name="v2 candidate",
        domain="finance",
        algorithm="ridge_l2",
        task_type="regression",
        version=2,
        lifecycle_status="EVALUATION",
    )
    server.admin_ai_transition_model_endpoint(
        ridge_id,
        server.AdminMLModelStatusRequest(version=2, lifecycle_status="DEPLOYED", set_active=True, reason="approve v2"),
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert ml_reg.select_model(model_id=ridge_id)["version"] == 2

    rolled = server.admin_ai_rollback_model_endpoint(
        ridge_id,
        server.AdminMLRollbackRequest(target_version=1, reason="rollback test"),
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert rolled["version"] == 1 and rolled["is_active_production"] is True
    assert ml_reg.select_model(model_id=ridge_id)["version"] == 1

    # 5. Domain toggle + restore & Admin Overview AI Monitoring consistency
    try:
        server.admin_ai_set_domain_status_endpoint(
            "productivity",
            server.AdminDomainStatusRequest(active=False, reason="maintenance"),
            actor_info=("kader", "super_admin"),
            admin=admin,
        )
        assert DomainRegistry.is_domain_active("productivity") is False
    finally:
        DomainRegistry.set_domain_active("productivity", True)

    state = {
        "mode": "gold_fast_read",
        "agent": object(),
        "forecast_df": pd.DataFrame([{"commodity_name": "Millet", "forecast_price": 380.0}]),
        "freshness": {"forecasts": {"latest_observation_month": "2026-10", "data_age_months": 1, "freshness_status": "fresh"}},
    }
    ov = server.admin_overview_endpoint(
        live_probe=False,
        actor_info=("kader", "super_admin"),
        state=state,
        admin=admin,
        sub_store=sub_store,
        auth_store=auth_store,
        registry=lic_reg,
    )
    assert ov["api_health"]["engine_mode"] == "gold_fast_read"
    assert ov["ai_infrastructure"]["model_registry"] == "CONNECTED"
    assert ov["ai_infrastructure"]["ml_engine"] == "CONNECTED"
    assert ov["ml_registry_summary"]["total_registered_models"] >= 4

    # 6. Audit logs capture benchmark, deploy, rollback, domain toggle without leaking raw CSV
    audits = admin.list_audit_logs(limit=20)
    actions = {a["action"] for a in audits}
    assert {"launch_ml_benchmark", "transition_ml_model_status", "rollback_ml_model", "set_domain_active"}.issubset(actions)
    assert all("x1,x2,y" not in str(a) for a in audits)

