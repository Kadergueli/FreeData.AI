"""Reproducible ML and RAG Benchmark Runners (Zero Data Leakage, Baseline vs Candidate)."""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.data_loader import _load_clean_markets_raw
from src.ml_engine import RidgePriceRegressor, build_lag_features
from src.rag_engine import HybridRAGEngine, _hashed_embedding, _norm_tokens, rewrite_query


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err ** 2)))
    denom = np.where(np.abs(y_true) > 1e-8, np.abs(y_true), 1.0)
    mape = float(np.mean(np.abs(err) / denom) * 100.0)
    return {"mae": round(mae, 3), "rmse": round(rmse, 3), "mape_pct": round(mape, 3)}


def run_ml_forecasting_ablation(
    csv_path: Optional[str] = "freedatatd-markets-full.csv",
    *,
    min_months: int = 24,
    max_series: int = 40,
    train_ratio: float = 0.7,
) -> dict[str, Any]:
    """
    Compares Naive (t-1), Moving Average (3m), Seasonal Naive (t-12), and causal Ridge Regression
    on real Chad market series using strict chronological train/test splits (zero future leakage).
    """
    df = _load_clean_markets_raw(csv_path=csv_path)
    df = df[df["is_flagged_outlier"] == False].copy() if "is_flagged_outlier" in df.columns else df.copy()
    agg = (
        df.groupby(["province", "commodity_std", "year_month"], as_index=False)["value"]
        .median()
        .sort_values(["province", "commodity_std", "year_month"])
    )

    series_evaluated = 0
    naive_maes, ma3_maes, seas_maes, ridge_maes = [], [], [], []
    naive_rmses, ma3_rmses, seas_rmses, ridge_rmses = [], [], [], []
    ridge_wins_vs_naive = 0
    ma3_wins_vs_naive = 0
    seas_wins_vs_naive = 0

    for (_, _), grp in agg.groupby(["province", "commodity_std"]):
        if len(grp) < min_months:
            continue
        prices = grp["value"].to_numpy(dtype=float)
        months = grp["year_month"].dt.month.to_numpy(dtype=int)
        X, y = build_lag_features(prices, months=months)
        if len(X) < 12:
            continue

        split = max(6, int(len(X) * train_ratio))
        if len(X) - split < 4:
            continue

        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split:], y[split:]

        # 1. Baselines computed strictly from causal features / past observations
        pred_naive = X_test[:, 0]  # lag_1
        pred_ma3 = X_test[:, 3]    # ma_3

        # Seasonal naive (t - 12) on aligned target indices (offset +3 from build_lag_features)
        test_orig_idx = np.arange(3 + split, 3 + len(X))
        pred_seas = np.array([prices[idx - 12] if idx >= 12 else prices[idx - 1] for idx in test_orig_idx], dtype=float)

        # 2. Candidate: Ridge Regression tuned strictly on chronological validation tail of X_train
        val_cut = max(4, int(len(X_train) * 0.75))
        best_alpha = 1.0
        if len(X_train) - val_cut >= 2:
            best_val_mae = float("inf")
            for alpha in (0.1, 1.0, 10.0, 50.0):
                m_val = RidgePriceRegressor(alpha=alpha).fit(X_train[:val_cut], y_train[:val_cut])
                val_mae = float(np.mean(np.abs(y_train[val_cut:] - m_val.predict(X_train[val_cut:]))))
                if val_mae < best_val_mae:
                    best_val_mae = val_mae
                    best_alpha = alpha

        model = RidgePriceRegressor(alpha=best_alpha).fit(X_train, y_train)
        pred_ridge = np.maximum(0.0, model.predict(X_test))

        m_naive = _regression_metrics(y_test, pred_naive)
        m_ma3 = _regression_metrics(y_test, pred_ma3)
        m_seas = _regression_metrics(y_test, pred_seas)
        m_ridge = _regression_metrics(y_test, pred_ridge)

        naive_maes.append(m_naive["mae"])
        ma3_maes.append(m_ma3["mae"])
        seas_maes.append(m_seas["mae"])
        ridge_maes.append(m_ridge["mae"])

        naive_rmses.append(m_naive["rmse"])
        ma3_rmses.append(m_ma3["rmse"])
        seas_rmses.append(m_seas["rmse"])
        ridge_rmses.append(m_ridge["rmse"])

        if m_ridge["mae"] < m_naive["mae"]:
            ridge_wins_vs_naive += 1
        if m_ma3["mae"] < m_naive["mae"]:
            ma3_wins_vs_naive += 1
        if m_seas["mae"] < m_naive["mae"]:
            seas_wins_vs_naive += 1

        series_evaluated += 1
        if series_evaluated >= max_series:
            break

    if series_evaluated == 0:
        return {"status": "no_eligible_series", "series_evaluated": 0}

    return {
        "status": "completed",
        "series_evaluated": series_evaluated,
        "split_protocol": f"chronological_{int(train_ratio * 100)}_{int((1 - train_ratio) * 100)}_nested_val",
        "models": {
            "naive_last": {
                "mean_mae": round(float(np.mean(naive_maes)), 3),
                "mean_rmse": round(float(np.mean(naive_rmses)), 3),
            },
            "moving_avg_3": {
                "mean_mae": round(float(np.mean(ma3_maes)), 3),
                "mean_rmse": round(float(np.mean(ma3_rmses)), 3),
                "win_rate_vs_naive_pct": round((ma3_wins_vs_naive / series_evaluated) * 100.0, 1),
            },
            "seasonal_naive_12": {
                "mean_mae": round(float(np.mean(seas_maes)), 3),
                "mean_rmse": round(float(np.mean(seas_rmses)), 3),
                "win_rate_vs_naive_pct": round((seas_wins_vs_naive / series_evaluated) * 100.0, 1),
            },
            "ridge_causal_lags": {
                "mean_mae": round(float(np.mean(ridge_maes)), 3),
                "mean_rmse": round(float(np.mean(ridge_rmses)), 3),
                "win_rate_vs_naive_pct": round((ridge_wins_vs_naive / series_evaluated) * 100.0, 1),
            },
        },
    }


DEFAULT_RAG_BENCHMARK_CASES: list[dict[str, Any]] = [
    {"query": "intervalle de confiance conforme calibration backtest", "expected_title": "METHODOLOGY"},
    {"query": "regle zero fabrication source traçabilite", "expected_title": "DATA_GOVERNANCE"},
    {"query": "redistribution_allowed unclear_licensing attribution", "expected_title": "DATA_LICENSING_POLICY"},
    {"query": "supprimer mes donnees personnelles privacy", "expected_title": "PRIVACY_POLICY"},
    {"query": "moteur financier 80 8 12 point mort tresorerie", "expected_title": "METHODOLOGY"},
    {"query": "utilisation responsable IA limites decision credit", "expected_title": "RESPONSIBLE_AI_POLICY"},
]


def _score_rag_config(
    docs: list[tuple[str, str]],
    cases: list[dict[str, Any]],
    *,
    chunk_size: int,
    overlap: int,
    bm25_weight: float,
    top_k: int = 3,
) -> dict[str, Any]:
    engine = HybridRAGEngine()
    for title, text in docs:
        engine.add_text_document(
            doc_id=title.lower(),
            text=text,
            title=title,
            source=f"{title}.md",
            chunk_size=chunk_size,
            overlap=overlap,
        )

    t0 = time.perf_counter()
    prec_sum = 0.0
    rr_sum = 0.0
    for case in cases:
        rewritten = rewrite_query(case["query"])
        q_tokens = _norm_tokens(rewritten)
        q_vec = _hashed_embedding(rewritten)
        scored = []
        for ch in engine.chunks:
            bm25 = engine._bm25_score(q_tokens, ch)
            cos = float(np.dot(q_vec, ch.embedding))
            bm25_norm = bm25 / (1.0 + bm25)
            score = bm25_weight * bm25_norm + (1.0 - bm25_weight) * max(0.0, cos)
            if score > 0.0:
                scored.append((score, ch.title))
        scored.sort(key=lambda x: x[0], reverse=True)
        hit_titles = [t.lower() for _, t in scored[:top_k]]
        expected = case["expected_title"].lower()
        if expected in hit_titles:
            rank = hit_titles.index(expected) + 1
            rr_sum += 1.0 / rank
            prec_sum += 1.0 / max(1, len(hit_titles))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    n = max(1, len(cases))
    return {
        "chunk_size": chunk_size,
        "overlap": overlap,
        "bm25_weight": bm25_weight,
        "num_chunks": len(engine.chunks),
        "precision_at_3": round(prec_sum / n, 3),
        "mrr": round(rr_sum / n, 3),
        "eval_ms": round(elapsed_ms, 2),
    }


def run_rag_retrieval_ablation(repo_root: str | Path = ".") -> dict[str, Any]:
    """Benchmarks chunking and hybrid retrieval weights on the repository's markdown knowledge base."""
    root = Path(repo_root)
    doc_names = ["METHODOLOGY", "DATA_GOVERNANCE", "DATA_LICENSING_POLICY", "PRIVACY_POLICY", "RESPONSIBLE_AI_POLICY"]
    docs: list[tuple[str, str]] = []
    for name in doc_names:
        p = root / f"{name}.md"
        if p.is_file():
            docs.append((name, p.read_text(encoding="utf-8")))
    if not docs:
        return {"status": "no_documents_found"}

    configs = [
        {"name": "bm25_only_900", "chunk_size": 900, "overlap": 150, "bm25_weight": 1.0},
        {"name": "vector_only_900", "chunk_size": 900, "overlap": 150, "bm25_weight": 0.0},
        {"name": "prod_hybrid_65_35_900", "chunk_size": 900, "overlap": 150, "bm25_weight": 0.65},
        {"name": "hybrid_50_50_600", "chunk_size": 600, "overlap": 120, "bm25_weight": 0.50},
        {"name": "hybrid_70_30_1200", "chunk_size": 1200, "overlap": 200, "bm25_weight": 0.70},
    ]
    results = {}
    for cfg in configs:
        results[cfg["name"]] = _score_rag_config(
            docs,
            DEFAULT_RAG_BENCHMARK_CASES,
            chunk_size=cfg["chunk_size"],
            overlap=cfg["overlap"],
            bm25_weight=cfg["bm25_weight"],
        )
    return {"status": "completed", "documents": len(docs), "cases": len(DEFAULT_RAG_BENCHMARK_CASES), "configs": results}

