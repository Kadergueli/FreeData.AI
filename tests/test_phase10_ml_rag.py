"""Tests for Phase 10B: ML Engine, ModelRegistry, HybridRAGEngine, and IntelligenceOrchestrator."""
import json

import numpy as np
import pandas as pd

from src.ml_engine import (
    KMeansMarketClusterer,
    ModelRegistry,
    RidgePriceRegressor,
    RiskGradeClassifier,
    build_lag_features,
    evaluate_ridge_chronological,
)
from src.orchestrator_ml_rag import IntelligenceOrchestrator
from src.rag_engine import HybridRAGEngine


def test_ridge_regression_chronological_no_leakage_and_registry(tmp_path):
    # Linear + seasonal trend over 18 months
    prices = np.array([200.0 + 4.0 * t + 10.0 * np.sin(2 * np.pi * t / 12.0) for t in range(18)])
    X, y = build_lag_features(prices)
    assert X.shape == (15, 6)
    # Verify causal lag_1 == prices[t-1]
    assert X[0, 0] == prices[2] and y[0] == prices[3]

    ev = evaluate_ridge_chronological(prices)
    assert ev["status"] == "evaluated"
    assert ev["ridge_mae_xaf_kg"] < ev["naive_mae_xaf_kg"]
    assert ev["beats_baseline"] is True

    # Insufficient history refused
    short_ev = evaluate_ridge_chronological(prices[:5])
    assert short_ev["status"] == "insufficient_history"

    # Model persistence & versioning
    reg = ModelRegistry(models_dir=str(tmp_path / "models"))
    saved1 = reg.save_model("ridge_millet", ev["model"].to_dict(), {"mae": ev["ridge_mae_xaf_kg"]})
    saved2 = reg.save_model("ridge_millet", ev["model"].to_dict(), {"mae": ev["ridge_mae_xaf_kg"]})
    assert saved1["version"] == 1 and saved2["version"] == 2
    loaded = reg.load_latest("ridge_millet")
    restored = RidgePriceRegressor.from_dict(loaded["artifact"])
    assert np.allclose(restored.predict(X[:2]), ev["model"].predict(X[:2]))


def test_kmeans_clustering_and_logistic_risk_classifier():
    df = pd.DataFrame([
        {"province": "Lac", "cv_pct": 8.0, "credit_score": 85.0},
        {"province": "Batha", "cv_pct": 9.0, "credit_score": 82.0},
        {"province": "Kanem", "cv_pct": 28.0, "credit_score": 45.0},
        {"province": "Wadi Fira", "cv_pct": 31.0, "credit_score": 40.0},
        {"province": "N'Djamena", "cv_pct": 15.0, "credit_score": 68.0},
        {"province": "Moyen-Chari", "cv_pct": 16.0, "credit_score": 65.0},
    ])
    km = KMeansMarketClusterer(k=3).fit_predict(df, ["cv_pct", "credit_score"])
    assert km["status"] == "clustered"
    assert km["samples"] == 6

    X = np.array([[8.0, 4.0], [9.0, 5.0], [10.0, 6.0], [25.0, 18.0], [28.0, 22.0], [32.0, 25.0]])
    y = np.array([0, 0, 0, 1, 1, 1])
    clf_res = RiskGradeClassifier().fit_and_evaluate(X, y)
    assert clf_res["status"] == "evaluated"
    assert clf_res["f1_score"] >= 0.8


def test_hybrid_rag_ingestion_filtering_and_evaluation(tmp_path):
    rag = HybridRAGEngine()
    md_file = tmp_path / "methodo.md"
    md_file.write_text("Le point mort est calcule avec 5 XAF/kg de sacherie et 25 XAF/kg de fret.", encoding="utf-8")
    json_file = tmp_path / "prices.json"
    json_file.write_text(json.dumps({"province": "Lac", "commodity": "Millet", "price": 210}), encoding="utf-8")
    csv_file = tmp_path / "markets.csv"
    csv_file.write_text("province,commodity,price\nBatha,Sorghum,240\n", encoding="utf-8")

    assert rag.ingest_file(md_file, metadata={"doc_type": "methodo"}) >= 1
    assert rag.ingest_file(json_file, metadata={"province": "Lac", "commodity": "Millet"}) >= 1
    assert rag.ingest_file(csv_file, metadata={"province": "Batha"}) >= 1

    hits = rag.search("point mort sacherie", top_k=2)
    assert len(hits) >= 1
    assert hits[0]["title"] == "methodo"
    assert hits[0]["verified_fact"] is False

    # Metadata filter
    lac_hits = rag.search("millet", top_k=2, filters={"province": "Lac"})
    assert len(lac_hits) == 1 and lac_hits[0]["title"] == "prices"

    eval_res = rag.evaluate_retrieval([
        {"query": "point mort sacherie", "expected_title": "methodo"},
        {"query": "mil Lac", "expected_title": "prices", "filters": {"province": "Lac"}},
    ])
    assert eval_res["mrr"] == 1.0


def test_intelligence_orchestrator_tool_selection_and_execution():
    rag = HybridRAGEngine()
    rag.add_text_document("gov", "La licence de table_public est en cours de verification.", title="gov", source="DATA_LICENSING_POLICY.md")
    orch = IntelligenceOrchestrator(rag=rag)

    assert orch.select_tool("Quelles anomalies de prix ont été détectées ?") == "ml_anomaly"
    assert orch.select_tool("Segmente les marchés par clustering K-Means") == "ml_cluster"
    assert orch.select_tool("Quelle est la prévision et le backtest du mil ?") == "ml_forecast"
    assert orch.select_tool("Que dit la documentation de gouvernance et licence ?") == "rag_hybrid"
    assert orch.select_tool("Quelles provinces ont les prix les plus élevés ?") == "analytics_query"

    fc = pd.DataFrame([
        {"source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "last_observed_month": "2026-10", "last_observed_price": 210.0, "forecast_t1": 220.0},
        {"source": "WFP", "province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "last_observed_month": "2026-10", "last_observed_price": 340.0, "forecast_t1": 350.0},
    ])
    res_rag = orch.handle("Que dit le document sur la licence ?", forecast_df=fc, hist_df=pd.DataFrame(), passport_df=pd.DataFrame(), anomalies_df=pd.DataFrame())
    assert res_rag["tool_used"] == "rag_hybrid"
    assert len(res_rag["result"]["hits"]) == 1

    res_geo = orch.handle("Quelles provinces ont les prix les plus élevés ?", forecast_df=fc, hist_df=pd.DataFrame(), passport_df=pd.DataFrame(), anomalies_df=pd.DataFrame(), commodity="Millet")
    assert res_geo["tool_used"] == "analytics_query"
    assert res_geo["result"]["highest_province"]["province"] == "N'Djamena"

