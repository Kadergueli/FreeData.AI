"""Run reproducible ML & RAG baseline-vs-candidate experiments and log them to ExperimentTracker."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.research import (
    DatasetProvenance,
    ExperimentTracker,
    InnovationBacklog,
    compute_file_sha256,
    run_ml_forecasting_ablation,
    run_rag_retrieval_ablation,
)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    csv_path = repo_root / "freedatatd-markets-full.csv"
    tracker = ExperimentTracker(repo_root / "data" / "research" / "experiments.db")
    backlog = InnovationBacklog(tracker)

    # 1. Register dataset provenance
    if csv_path.is_file():
        prov = DatasetProvenance(
            dataset_id="freedatatd_markets_full_v1",
            source_path="freedatatd-markets-full.csv",
            sha256=compute_file_sha256(csv_path),
            row_count=sum(1 for _ in csv_path.open("r", encoding="utf-8")) - 1,
            date_range="historical_wfp_fewsnet",
            notes="Cleaned via _load_clean_markets_raw (xaf/kg standardized, flagged outliers excluded).",
        )
        tracker.register_dataset(prov)

    # 2. Run ML Forecasting Ablation
    ml_res = run_ml_forecasting_ablation(str(csv_path))
    if ml_res.get("status") == "completed":
        models = ml_res["models"]
        exp_ml = tracker.log_experiment(
            name="ml_forecasting_lag_ridge_vs_naive",
            domain="agriculture",
            hypothesis="Causal lag+seasonal Ridge Regression reduces MAE vs Naive t-1 on >=24m Chad market series.",
            dataset_id="freedatatd_markets_full_v1",
            method="ridge_causal_lags",
            parameters={"alphas": [0.1, 1.0, 10.0, 50.0], "series_evaluated": ml_res["series_evaluated"]},
            split_protocol=ml_res["split_protocol"],
            seed=42,
            baseline_metrics={
                "mean_mae": models["naive_last"]["mean_mae"],
                "mean_rmse": models["naive_last"]["mean_rmse"],
            },
            candidate_metrics={
                "mean_mae": models["ridge_causal_lags"]["mean_mae"],
                "mean_rmse": models["ridge_causal_lags"]["mean_rmse"],
                "win_rate_vs_naive_pct": models["ridge_causal_lags"]["win_rate_vs_naive_pct"],
            },
            limitations="Evaluated on series with >=24 months only; does not replace production src/forecasting.py without broader rolling-origin backtest.",
            status="experimental",
        )
    else:
        exp_ml = ml_res

    # 3. Run RAG Retrieval Ablation
    rag_res = run_rag_retrieval_ablation(repo_root)
    if rag_res.get("status") == "completed":
        cfgs = rag_res["configs"]
        tracker.register_dataset(
            DatasetProvenance(
                dataset_id="repo_policy_docs_v1",
                source_path="METHODOLOGY.md + governance/policy markdowns",
                sha256="repo_markdown_snapshot",
                row_count=rag_res["documents"],
                notes="6 bilingual FR/EN retrieval benchmark cases.",
            )
        )
        exp_rag = tracker.log_experiment(
            name="rag_chunking_and_hybrid_weight_ablation",
            domain="general_ai",
            hypothesis="Hybrid BM25+vector retrieval outperforms vector-only hashed embeddings on bilingual domain queries.",
            dataset_id="repo_policy_docs_v1",
            method="hybrid_bm25_hashed_ablation",
            parameters={"top_k": 3, "configs_tested": list(cfgs.keys())},
            split_protocol="fixed_6_case_bilingual_benchmark",
            seed=42,
            baseline_metrics={
                "precision_at_3": cfgs["vector_only_900"]["precision_at_3"],
                "mrr": cfgs["vector_only_900"]["mrr"],
            },
            candidate_metrics={
                "precision_at_3": cfgs["prod_hybrid_65_35_900"]["precision_at_3"],
                "mrr": cfgs["prod_hybrid_65_35_900"]["mrr"],
            },
            limitations="Small 6-query synthetic benchmark with hashed embeddings; external semantic embeddings (e.g., Jina v3) not tested offline.",
            status="experimental",
        )
    else:
        exp_rag = rag_res

    # 4. Seed initial research backlog if empty
    if not backlog.list_ideas():
        backlog.add_idea(
            title="Adaptive Conformal Prediction for Volatile Series (e.g., Fish dry)",
            domain="agriculture",
            problem_statement="80% conformal interval coverage drops to 49.4% on Fish (dry); test Mondrian/adaptive conformal intervals.",
            priority="P1",
            data_available=True,
            estimated_cost="low",
            stage="feasibility_checked",
        )
        backlog.add_idea(
            title="Cross-Lingual FR/EN/Arabic Agricultural Query Expansion Benchmark",
            domain="chad_intelligence",
            problem_statement="Evaluate synonym/query rewriting impact on larger bilingual RAG test sets.",
            priority="P1",
            data_available=True,
            estimated_cost="low",
            stage="prototype",
        )
        backlog.add_idea(
            title="Quantile Gradient Boosting vs Ridge for Non-Linear Price Shocks",
            domain="data_science",
            problem_statement="Compare lightweight gradient-boosted quantile models against Ridge on >=36m series.",
            priority="P2",
            data_available=True,
            estimated_cost="low",
            stage="proposed",
        )

    print(json.dumps({"ml_ablation": ml_res, "rag_ablation": rag_res, "logged_ml": exp_ml, "logged_rag": exp_rag}, indent=2))


if __name__ == "__main__":
    main()

