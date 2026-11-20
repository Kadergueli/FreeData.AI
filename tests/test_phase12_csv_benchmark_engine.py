from __future__ import annotations

import base64
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from api import server
from src.ml_benchmark import (
    MAX_CSV_BYTES,
    BenchmarkJobManager,
    DatasetSpec,
    parse_and_validate_csv,
    run_csv_benchmark,
)
from src.ml_engine import ModelRegistry, RidgePriceRegressor


def _make_forecasting_csv(n: int = 30) -> bytes:
    lines = ["month,price"]
    for i in range(n):
        ym = f"2024-{(i % 12) + 1:02d}" if i < 12 else (f"2025-{(i % 12) + 1:02d}" if i < 24 else f"2026-{(i % 12) + 1:02d}")
        val = round(300.0 + 3.0 * i + 20.0 * np.sin(2.0 * np.pi * (i % 12) / 12.0), 2)
        lines.append(f"{ym},{val}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_regression_csv(n: int = 40) -> bytes:
    rng = np.random.default_rng(7)
    lines = ["x1,x2,y"]
    for _ in range(n):
        x1 = float(rng.uniform(1, 20))
        x2 = float(rng.uniform(5, 50))
        y = 10.0 + 2.5 * x1 - 0.5 * x2 + float(rng.normal(0, 0.5))
        lines.append(f"{x1:.3f},{x2:.3f},{y:.3f}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_classification_csv(n: int = 40) -> bytes:
    lines = ["cv,drawdown,high_risk"]
    for i in range(n):
        if i % 2 == 0:
            lines.append(f"{5 + (i % 4)},{2 + (i % 3)},0")
        else:
            lines.append(f"{25 + (i % 6)},{18 + (i % 5)},1")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _make_clustering_csv(n: int = 24) -> bytes:
    lines = ["price,volatility"]
    for i in range(n):
        base = 200 if i < 8 else (450 if i < 16 else 700)
        vol = 5 if i < 8 else (15 if i < 16 else 30)
        lines.append(f"{base + (i % 5) * 4},{vol + (i % 3)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_csv_and_dataset_spec_validation_rules():
    # 1. Private dataset scope rejected with PermissionError
    priv_spec = DatasetSpec(
        domain="agriculture",
        task_type="regression",
        target_column="y",
        feature_columns=["x1", "x2"],
        dataset_scope="user_private",
    )
    with pytest.raises(PermissionError):
        parse_and_validate_csv(_make_regression_csv(), priv_spec)

    # 2. Target leakage rejected
    leak_spec = DatasetSpec(
        domain="finance",
        task_type="regression",
        target_column="y",
        feature_columns=["x1", "y"],
    )
    with pytest.raises(ValueError, match="Fuite de cible"):
        parse_and_validate_csv(_make_regression_csv(), leak_spec)

    # 3. Duplicate CSV headers rejected
    dup_csv = b"x1,x1,y\n1,2,3\n4,5,6\n"
    ok_spec = DatasetSpec(domain="finance", task_type="regression", target_column="y", feature_columns=["x1"])
    with pytest.raises(ValueError, match="double"):
        parse_and_validate_csv(dup_csv, ok_spec)

    # 4. Oversized CSV (>5 MB) rejected
    huge = b"x1,y\n" + b"1,2\n" * ((MAX_CSV_BYTES // 4) + 100)
    with pytest.raises(ValueError, match="5 Mo"):
        parse_and_validate_csv(huge, ok_spec)

    # 5. Unknown domain rejected
    bad_dom = DatasetSpec(domain="unknown_domain_xyz", task_type="regression", target_column="y", feature_columns=["x1"])
    with pytest.raises(ValueError, match="Domaine inconnu"):
        parse_and_validate_csv(_make_regression_csv(), bad_dom)


def test_all_four_task_types_benchmark_metrics_artifacts_and_dedup(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))

    # 1. Forecasting (strict chronological split)
    fc_spec = DatasetSpec(
        domain="agriculture",
        task_type="forecasting",
        target_column="price",
        feature_columns=[],
        time_column="month",
        dataset_name="chad_mil.csv",
    )
    fc_res = run_csv_benchmark(_make_forecasting_csv(30), fc_spec, registry=reg)
    fc_algos = {c["algorithm"] for c in fc_res["candidates"]}
    assert {"naive_last", "moving_average_3", "seasonal_naive_12", "ridge_causal_lags_a1", "ridge_causal_lags_a10"}.issubset(fc_algos)
    for c in fc_res["candidates"]:
        assert c["lifecycle_status"] == "EVALUATION"  # NEVER auto-deployed
        assert "mae" in c["metrics"] and "rmse" in c["metrics"]

    # Deduplication on identical CSV + spec
    fc_res_2 = run_csv_benchmark(_make_forecasting_csv(30), fc_spec, registry=reg)
    assert all(c["deduplicated"] is True for c in fc_res_2["candidates"])

    # Verify executable Ridge artifact can be reloaded from durable DB & run predict()
    ridge_cand = next(c for c in fc_res["candidates"] if c["algorithm"] == "ridge_causal_lags_a1")
    loaded = reg.load_version(ridge_cand["model_id"], ridge_cand["version"])
    rebuilt = RidgePriceRegressor.from_dict(loaded["artifact"])
    pred = rebuilt.predict(np.array([[350.0, 345.0, 340.0, 345.0, 0.5, 0.86]]))
    assert pred.shape == (1,) and np.isfinite(pred[0])

    # 2. Regression
    reg_spec = DatasetSpec(domain="business_entrepreneurship", task_type="regression", target_column="y", feature_columns=["x1", "x2"])
    reg_res = run_csv_benchmark(_make_regression_csv(40), reg_spec, registry=reg)
    assert {c["algorithm"] for c in reg_res["candidates"]} == {"naive_mean", "linear_ols", "ridge_l2"}
    ols_cand = next(c for c in reg_res["candidates"] if c["algorithm"] == "linear_ols")
    assert ols_cand["metrics"]["r2"] > 0.90

    # 3. Classification (stratified holdout)
    clf_spec = DatasetSpec(domain="finance", task_type="classification", target_column="high_risk", feature_columns=["cv", "drawdown"])
    clf_res = run_csv_benchmark(_make_classification_csv(40), clf_spec, registry=reg)
    clf_algos = {c["algorithm"] for c in clf_res["candidates"]}
    assert "majority_class" in clf_algos and "logistic_l2" in clf_algos
    log_cand = next(c for c in clf_res["candidates"] if c["algorithm"] == "logistic_l2")
    assert log_cand["metrics"]["f1_score"] >= 0.8

    # 4. Clustering (k=3,4,5 + inertia + silhouette)
    cl_spec = DatasetSpec(domain="data_science", task_type="clustering", feature_columns=["price", "volatility"])
    cl_res = run_csv_benchmark(_make_clustering_csv(24), cl_spec, registry=reg)
    assert {c["algorithm"] for c in cl_res["candidates"]} == {"kmeans_k3", "kmeans_k4", "kmeans_k5"}
    for c in cl_res["candidates"]:
        assert c["metrics"]["inertia"] >= 0
        assert -1.0 <= c["metrics"]["silhouette_score"] <= 1.0

    # Zero candidates were auto-deployed
    for m in reg.list_models():
        assert m["lifecycle_status"] == "EVALUATION"
        assert m["is_active_production"] is False


def test_admin_benchmark_endpoint_rbac_concurrency_and_prod_preservation(monkeypatch, tmp_path: Path):
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))
    # Pre-existing production model must stay untouched
    reg.register_model(
        model_id="ridge_price_regressor",
        model_name="Prod Ridge",
        domain="agriculture",
        algorithm="RidgeRegression_L2_Gold",
        task_type="forecasting",
        version=1,
        lifecycle_status="DEPLOYED",
        set_active=True,
    )
    bench_mgr = BenchmarkJobManager(max_concurrent=1, timeout_seconds=30.0)
    monkeypatch.setattr(server, "_MODEL_REGISTRY", reg)
    monkeypatch.setattr(server, "_BENCHMARK_JOB_MANAGER", bench_mgr)

    csv_b64 = base64.b64encode(_make_regression_csv(32)).decode("ascii")
    req = server.AdminBenchmarkRequest(
        domain="finance",
        task_type="regression",
        target_column="y",
        feature_columns=["x1", "x2"],
        dataset_name="finance_sample.csv",
        dataset_scope="platform_public",
        dataset_provenance={"source": "Jeu de test interne", "license": "CC0"},
        csv_base64=csv_b64,
    )

    # 1. read_only_analyst rejected (403)
    with pytest.raises(HTTPException) as exc_rbac:
        server.admin_ai_launch_benchmark_endpoint(
            req,
            actor_info=("analyst", "read_only_analyst"),
            admin=admin,
        )
    assert exc_rbac.value.status_code == 403

    # 2. Private dataset scope rejected (403)
    priv_req = req.model_copy(update={"dataset_scope": "user_private"})
    with pytest.raises(HTTPException) as exc_priv:
        server.admin_ai_launch_benchmark_endpoint(
            priv_req,
            actor_info=("kader", "super_admin"),
            admin=admin,
        )
    assert exc_priv.value.status_code == 403

    # 3. Authorized super_admin launches background job -> completes -> audit logged
    job = server.admin_ai_launch_benchmark_endpoint(
        req,
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert job["job_id"].startswith("BENCH-")

    # Poll briefly for completion
    for _ in range(50):
        st = server.admin_ai_get_benchmark_endpoint(job["job_id"], actor_info=("kader", "super_admin"), admin=admin)
        if st["status"] in ("completed", "failed", "timed_out"):
            break
        time.sleep(0.03)
    final_st = server.admin_ai_get_benchmark_endpoint(job["job_id"], actor_info=("kader", "super_admin"), admin=admin)
    assert final_st["status"] == "completed"
    assert final_st["result"]["candidates_evaluated"] == 3

    # Audit log recorded & existing production model untouched
    assert any(a["action"] == "launch_ml_benchmark" for a in admin.list_audit_logs(limit=10))
    assert reg.select_model(model_id="ridge_price_regressor")["version"] == 1

    # 4. Concurrent benchmark rejection (max_concurrent=1)
    with bench_mgr._lock:
        bench_mgr._jobs["BENCH-BUSY"] = {
            "job_id": "BENCH-BUSY",
            "status": "running",
            "created_at": "2026-11-19T20:00:00+00:00",
        }
    with pytest.raises(HTTPException) as exc_busy:
        server.admin_ai_launch_benchmark_endpoint(
            req,
            actor_info=("kader", "super_admin"),
            admin=admin,
        )
    assert exc_busy.value.status_code == 429

