from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.domains import DomainModule, DomainRegistry
from src.entitlements import EntitlementManager
from src.ml_engine import (
    MODEL_LIFECYCLE_STATES,
    KMeansMarketClusterer,
    ModelRegistry,
    RiskGradeClassifier,
    evaluate_ridge_chronological,
)


def test_multi_domain_registry_metadata_and_dynamic_extension():
    domains = DomainRegistry.list_domains(include_inactive=True)
    dom_ids = {d["domain_id"] for d in domains}
    expected = {
        "markets_and_prices",
        "agriculture",
        "economy",
        "health",
        "population",
        "environment",
        "infrastructure",
        "transport",
    }
    assert expected.issubset(dom_ids)
    for d in domains:
        assert d["instructions"]
        assert isinstance(d["allowed_tools"], (list, tuple)) and len(d["allowed_tools"]) > 0
        assert d["execution_pipeline"] in ("chad_agent", "ml_orchestrator", "rag_llm")

    # Dynamically add a new domain without modifying Chat Engine
    new_mod = DomainModule(
        domain_id="energy_climate_test",
        label_fr="Énergie & Climat",
        description="Production solaire au Tchad.",
        instructions="Analyse la production solaire et l'efficience énergétique.",
        allowed_tools=("llm_reasoning", "rag_hybrid"),
        knowledge_sources=("DATA_CATALOG.md",),
        supported_workflows=("solar_sizing",),
        output_formats=("markdown",),
        required_tier="premium",
        ml_models=("solar_yield_v1",),
        rag_collections=("energy_docs",),
        analytical_operations=("yield_estimation",),
        execution_pipeline="rag_llm",
    )
    try:
        DomainRegistry.register_domain(new_mod, pattern=r"\b(?:solaire|photovoltaique|megawatt)\b")
        matched = DomainRegistry.classify_domain("Dimensionnement d'une centrale solaire 2 megawatt")
        assert matched.domain_id == "energy_climate_test"

        # Disabling domain prevents auto-routing to it
        DomainRegistry.set_domain_active("energy_climate_test", False)
        assert DomainRegistry.is_domain_active("energy_climate_test") is False
        fallback = DomainRegistry.classify_domain("Dimensionnement d'une centrale solaire 2 megawatt")
        assert fallback.domain_id != "energy_climate_test"
    finally:
        DomainRegistry.unregister_domain("energy_climate_test")


def test_ml_model_registry_lifecycle_selection_traceability_and_telemetry(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "models"))
    reg.seed_builtin_models(data_ready=False)

    # Built-ins are REGISTERED (not falsely marked DEPLOYED when data_ready=False)
    with pytest.raises(LookupError):
        reg.select_model(domain="markets_and_prices", task_type="forecasting")

    # Register v2 with real evaluation metrics and dataset provenance
    reg.register_model(
        model_id="ridge_price_regressor",
        model_name="Ridge Price Forecaster v2",
        domain="markets_and_prices",
        algorithm="RidgeRegression_L2",
        task_type="forecasting",
        version=2,
        training_dataset_ref="table_ml_forecasts_2026_10",
        evaluation_dataset_ref="holdout_2026_q3",
        dataset_provenance={"rows": 1450, "split": "chronological_70_30"},
        lifecycle_status="TRAINED",
        evaluation_metrics={"mae": 18.4, "rmse": 24.1},
    )
    # Still TRAINED -> not selectable for production
    with pytest.raises(LookupError):
        reg.select_model(domain="markets_and_prices", task_type="forecasting")

    # Transition v1 to DEPLOYED + active
    v1 = reg.transition_status("ridge_price_regressor", 1, "DEPLOYED", set_active=True)
    assert v1["lifecycle_status"] == "DEPLOYED"
    assert v1["is_active_production"] is True
    assert reg.select_model(domain="markets_and_prices", task_type="forecasting")["version"] == 1

    # Promote v2 to DEPLOYED + active -> v1 automatically demoted from active_production
    v2 = reg.transition_status("ridge_price_regressor", 2, "DEPLOYED", set_active=True)
    assert v2["is_active_production"] is True
    selected = reg.select_model(domain="markets_and_prices", task_type="forecasting")
    assert selected["version"] == 2
    assert selected["training_dataset_ref"] == "table_ml_forecasts_2026_10"

    # Record executions & failures
    reg.record_execution("ridge_price_regressor", 2, latency_ms=14.2, success=True)
    reg.record_execution("ridge_price_regressor", 2, latency_ms=25.8, success=False, error="NaN input")

    versions = reg.compare_versions("ridge_price_regressor")
    assert len(versions) == 2
    assert versions[0]["is_active_production"] is False
    assert versions[1]["execution_count"] == 2
    assert versions[1]["failure_count"] == 1
    assert versions[1]["avg_inference_latency_ms"] == 20.0
    # Security: raw artifact weights & filesystem paths never exposed
    raw_dump = json.dumps(versions)
    assert "artifact" not in raw_dump
    assert str(tmp_path) not in raw_dump

    # Invalid lifecycle state rejected
    with pytest.raises(ValueError):
        reg.transition_status("ridge_price_regressor", 2, "MAGIC_STATE")
    assert "DEPLOYED" in MODEL_LIFECYCLE_STATES
    assert "FAILED" in MODEL_LIFECYCLE_STATES

    summary = reg.summary()
    assert summary["total_registered_models"] == 4  # 3 built-ins + v2
    assert summary["total_executions"] == 2
    assert summary["total_failures"] == 1


def test_ml_algorithms_real_execution_and_invalid_input_handling():
    # 1. Ridge chronological evaluation (valid + insufficient history)
    series = np.array([300, 310, 320, 315, 330, 340, 345, 355, 360, 370, 365, 380], dtype=float)
    res_ok = evaluate_ridge_chronological(series)
    assert res_ok["status"] == "evaluated"
    assert "ridge_mae_xaf_kg" in res_ok and "ridge_rmse_xaf_kg" in res_ok

    res_short = evaluate_ridge_chronological(np.array([300.0, 310.0]))
    assert res_short["status"] == "insufficient_history"

    # 2. K-Means clustering (valid + insufficient data)
    df = pd.DataFrame({
        "market": ["M1", "M2", "M3", "M4", "M5", "M6"],
        "price": [250, 260, 400, 410, 600, 620],
        "cv": [5.0, 6.0, 12.0, 13.0, 25.0, 27.0],
    })
    km = KMeansMarketClusterer(k=3, seed=42)
    cl_ok = km.fit_predict(df, ["price", "cv"])
    assert cl_ok["status"] == "clustered"
    assert cl_ok["samples"] == 6
    assert km.fit_predict(df.head(2), ["price", "cv"])["status"] == "insufficient_data"

    # 3. Logistic risk classifier (valid + single-class invalid input)
    X = np.array([[5, 2], [6, 3], [7, 4], [25, 18], [30, 22], [28, 20], [8, 3], [32, 24]], dtype=float)
    y = np.array([0, 0, 0, 1, 1, 1, 0, 1], dtype=int)
    clf = RiskGradeClassifier()
    ev = clf.fit_and_evaluate(X, y)
    assert ev["status"] == "evaluated"
    assert 0.0 <= ev["f1_score"] <= 1.0
    assert clf.fit_and_evaluate(X[:3], np.array([0, 0, 0]))["status"] == "insufficient_data"


def test_admin_ai_control_center_endpoints_rbac_and_audit(monkeypatch, tmp_path: Path):
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    sub_store = server.SubscriptionStore(db_path=tmp_path / "subs.db")
    auth_store = server.AuthStore(db_path=tmp_path / "auth.db")
    registry = server.LicensingRegistry()
    test_ml_reg = ModelRegistry(models_dir=str(tmp_path / "ml_models"))
    test_ml_reg.seed_builtin_models(data_ready=False)
    monkeypatch.setattr(server, "_MODEL_REGISTRY", test_ml_reg)

    state = {
        "mode": "gold_ml",
        "agent": object(),
        "forecast_df": pd.DataFrame([{"commodity_name": "Riz", "forecast_price": 450.0}]),
        "freshness": {"forecasts": {"latest_observation_month": "2026-10", "data_age_months": 1, "freshness_status": "fresh"}},
    }

    # Overview exposes domains_summary, ml_registry_summary, ai_infrastructure
    ov = server.admin_overview_endpoint(
        live_probe=False,
        actor_info=("kader", "super_admin"),
        state=state,
        admin=admin,
        sub_store=sub_store,
        auth_store=auth_store,
        registry=registry,
    )
    assert ov["domains_summary"]["total_domains"] >= 8
    assert ov["ml_registry_summary"]["total_registered_models"] == 3
    assert set(ov["ai_infrastructure"].keys()) >= {
        "ml_engine",
        "rag_engine",
        "llm_provider",
        "embedding_provider",
        "analytics_engine",
        "tool_orchestrator",
        "background_jobs",
        "model_registry",
    }

    # read_only_analyst can read domains & models, but CANNOT mutate status (HTTP 403)
    dom_view = server.admin_ai_domains_endpoint(actor_info=("analyst", "read_only_analyst"), admin=admin)
    assert dom_view["total_domains"] >= 8

    mod_view = server.admin_ai_models_endpoint(actor_info=("analyst", "read_only_analyst"), admin=admin)
    assert len(mod_view["models"]) == 3

    with pytest.raises(HTTPException) as exc_dom:
        server.admin_ai_set_domain_status_endpoint(
            "health",
            server.AdminDomainStatusRequest(active=False, reason="test"),
            actor_info=("analyst", "read_only_analyst"),
            admin=admin,
        )
    assert exc_dom.value.status_code == 403

    with pytest.raises(HTTPException) as exc_mod:
        server.admin_ai_transition_model_endpoint(
            "ridge_price_regressor",
            server.AdminMLModelStatusRequest(version=1, lifecycle_status="DEPLOYED", set_active=True),
            actor_info=("analyst", "read_only_analyst"),
            admin=admin,
        )
    assert exc_mod.value.status_code == 403

    # super_admin can transition model status & audit log is recorded
    updated = server.admin_ai_transition_model_endpoint(
        "ridge_price_regressor",
        server.AdminMLModelStatusRequest(version=1, lifecycle_status="DEPLOYED", set_active=True, reason="release"),
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert updated["lifecycle_status"] == "DEPLOYED"
    assert updated["is_active_production"] is True

    cmp_res = server.admin_ai_compare_model_versions_endpoint(
        "ridge_price_regressor",
        actor_info=("kader", "super_admin"),
        admin=admin,
    )
    assert cmp_res["model_id"] == "ridge_price_regressor"
    assert len(cmp_res["versions"]) == 1

    audits = admin.list_audit_logs(limit=10)
    assert any(a["action"] == "transition_ml_model_status" for a in audits)


def test_concurrent_quota_enforcement_no_bypass():
    ent = EntitlementManager()
    uid = "concurrent_quota_user"
    free_limit = ent.get_entitlements("free", uid)["daily_chat_quota"]

    def _hit(_: int) -> bool:
        try:
            ent.consume_chat_quota("free", uid)
            return True
        except OverflowError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_hit, range(free_limit + 10)))

    assert sum(1 for r in results if r) == free_limit
    assert sum(1 for r in results if not r) == 10
