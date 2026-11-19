from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from api import server
from src.ml_engine import ModelRegistry
from src.publication_pipeline import (
    register_forecasting_evaluation_in_registry,
    run_publication_pipeline,
)


def _synthetic_markets_df(n_months: int = 24) -> pd.DataFrame:
    """Builds a realistic 2-series monthly Chad market DataFrame for chronological rolling-origin backtest."""
    periods = pd.period_range("2024-11", periods=n_months, freq="M")
    rows = []
    for m_idx, ym in enumerate(periods):
        seasonal = 25.0 * np.sin(2.0 * np.pi * ym.month / 12.0)
        rows.append({
            "source": "WFP",
            "province": "N'Djamena",
            "market_name": "N'Djamena",
            "commodity_std": "Millet",
            "year_month": ym,
            "value": round(320.0 + 2.5 * m_idx + seasonal, 2),
        })
        rows.append({
            "source": "WFP",
            "province": "Salamat",
            "market_name": "Am Timan",
            "commodity_std": "Sorghum (red)",
            "year_month": ym,
            "value": round(260.0 + 1.8 * m_idx + seasonal * 0.8, 2),
        })
    return pd.DataFrame(rows)


def test_pipeline_to_registry_integration_metrics_and_deduplication(tmp_path: Path):
    df = _synthetic_markets_df(24)
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))

    # Run publication pipeline in dry_run mode with model_registry attached
    rep1 = run_publication_pipeline(
        loader_fn=lambda: df.copy(),
        dry_run=True,
        model_registry=reg,
        allow_auto_deploy=False,
        backtest_origins=4,
    )
    assert rep1["pipeline_status"] == "succeeded"
    assert "forecasts" in rep1["stages_completed"]
    assert "ml_registry_eval" in rep1["stages_completed"]

    ev1 = rep1["ml_registry_evaluation"]
    assert ev1["status"] == "registered"
    assert ev1["deduplicated"] is False
    assert ev1["version"] == 1
    assert ev1["lifecycle_status"] == "EVALUATION"  # never auto-deployed by default

    m = ev1["metrics"]
    assert m["mae_xaf_kg"] >= 0
    assert m["rmse_xaf_kg"] >= 0
    assert m["mape_pct"] >= 0
    assert "baseline_naive_mae_xaf_kg" in m
    assert "vs_naive_pct" in m
    assert m["evaluated_series_count"] == 2
    assert m["evaluated_observations_count"] >= 4
    assert "ic80_coverage_pct" in m

    # Repeated execution on identical dataset MUST deduplicate (no duplicate v2!)
    rep2 = run_publication_pipeline(
        loader_fn=lambda: df.copy(),
        dry_run=True,
        model_registry=reg,
        allow_auto_deploy=False,
        backtest_origins=4,
    )
    ev2 = rep2["ml_registry_evaluation"]
    assert ev2["status"] == "deduplicated"
    assert ev2["deduplicated"] is True
    assert ev2["version"] == 1
    assert len([x for x in reg.list_models() if x["model_id"] == "ridge_price_regressor"]) == 1


def test_production_model_preserved_on_new_version_and_failed_backtest(tmp_path: Path):
    df24 = _synthetic_markets_df(24)
    df25 = _synthetic_markets_df(25)
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))

    # Promote v1 to DEPLOYED (production)
    ev1 = register_forecasting_evaluation_in_registry(df24, pd.DataFrame([{"a": 1}]), registry=reg, n_origins=4)
    reg.transition_status("ridge_price_regressor", ev1["version"], "DEPLOYED", set_active=True)
    assert reg.select_model(model_id="ridge_price_regressor")["version"] == 1

    # New dataset (25 months) -> registers v2 in EVALUATION, NEVER silently overwrites deployed v1 even if allow_auto_deploy=True
    ev2 = register_forecasting_evaluation_in_registry(
        df25, pd.DataFrame([{"a": 1}, {"a": 2}]), registry=reg, n_origins=4, allow_auto_deploy=True
    )
    assert ev2["status"] == "registered"
    assert ev2["version"] == 2
    assert ev2["lifecycle_status"] == "EVALUATION"
    assert reg.select_model(model_id="ridge_price_regressor")["version"] == 1

    # Failed backtest exception preserves production model and does not crash pipeline
    ev_fail = register_forecasting_evaluation_in_registry(
        df25,
        pd.DataFrame([{"a": 1}]),
        registry=reg,
        evaluation_run_key="forced_fail_run",
        backtest_fn=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("backtest boom")),
    )
    assert ev_fail["status"] == "evaluation_failed"
    assert ev_fail["production_preserved"] is True
    assert reg.select_model(model_id="ridge_price_regressor")["version"] == 1


def test_quality_gate_rejection_blocks_auto_deploy(tmp_path: Path):
    df = _synthetic_markets_df(24)
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))

    # Mock a backtest where model MAE is much worse than naive (vs_naive_pct > 0)
    def _bad_model_bt(kg_df, n_origins=4, min_history=12):
        rows = []
        for i in range(4):
            base = {
                "source": "WFP",
                "province": "N'Djamena",
                "market_name": "N'Djamena",
                "commodity_std": "Millet",
                "origin": f"2026-0{i+1}",
                "target": f"2026-0{i+2}",
                "last": 300.0,
                "actual": 305.0,
            }
            rows.append({**base, "method": "naive", "forecast": 300.0, "ci_low": np.nan, "ci_high": np.nan, "abs_err": 5.0, "pct_err": 1.64, "direction_ok": True, "in_ci": False})
            rows.append({**base, "method": "model", "forecast": 380.0, "ci_low": 350.0, "ci_high": 410.0, "abs_err": 75.0, "pct_err": 24.59, "direction_ok": False, "in_ci": False})
        return pd.DataFrame(rows)

    ev = register_forecasting_evaluation_in_registry(
        df,
        pd.DataFrame([{"a": 1}]),
        registry=reg,
        allow_auto_deploy=True,
        backtest_fn=_bad_model_bt,
    )
    assert ev["status"] == "registered"
    assert ev["quality_gate_passed"] is False
    assert ev["lifecycle_status"] == "EVALUATION"


def test_registry_persistence_after_restart_and_admin_visibility(monkeypatch, tmp_path: Path):
    df = _synthetic_markets_df(24)
    db_file = tmp_path / "durable_ml.db"
    m_dir_1 = tmp_path / "ephemeral_1"
    reg1 = ModelRegistry(models_dir=str(m_dir_1), db_path=str(db_file))

    ev = register_forecasting_evaluation_in_registry(df, pd.DataFrame([{"a": 1}]), registry=reg1, n_origins=4)
    assert ev["status"] == "registered"

    # Simulate container restart with ephemeral disk wiped
    shutil.rmtree(m_dir_1)
    reg2 = ModelRegistry(models_dir=str(tmp_path / "ephemeral_2"), db_path=str(db_file))
    versions = reg2.compare_versions("ridge_price_regressor")
    assert len(versions) == 1
    assert versions[0]["evaluation_metrics"]["mae_xaf_kg"] == ev["metrics"]["mae_xaf_kg"]
    assert reg2.load_version("ridge_price_regressor", 1)["artifact"]["model_type"] == "RidgeRegression_L2_Gold"

    # Verify Admin AI Control Center exposes exact metrics and dataset ref
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    monkeypatch.setattr(server, "_MODEL_REGISTRY", reg2)
    adm_models = server.admin_ai_models_endpoint(actor_info=("kader", "super_admin"), admin=admin)
    found = [m for m in adm_models["models"] if m["model_id"] == "ridge_price_regressor"][0]
    assert found["training_dataset_ref"].startswith("table_ml_forecasts:")
    assert found["evaluation_dataset_ref"].startswith("rolling_origin_4m:")
    assert found["evaluation_metrics"]["mae_xaf_kg"] == ev["metrics"]["mae_xaf_kg"]
    assert found["evaluation_metrics"]["rmse_xaf_kg"] == ev["metrics"]["rmse_xaf_kg"]
    assert found["evaluation_metrics"]["mape_pct"] == ev["metrics"]["mape_pct"]

