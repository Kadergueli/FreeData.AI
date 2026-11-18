# ADR-005: Separation of Experimental Research from Production Models

- **Status:** Accepted
- **Evidence in Repo:** `src/research/experiment_tracker.py`, `src/research/benchmarks.py`, `scripts/run_research_experiments.py`

## Context
FreeData.AI uses deterministic statistical/ML baselines (`src/forecasting.py`, `src/ml_engine.py`, `src/rag_engine.py`) in production while exploring improvements (conformal intervals, RAG chunking/weighting, alternative forecasting models).

## Problem
Experimental prototypes can introduce data leakage, break production SLAs, or replace simpler baselines that actually generalize better on short series.

## Options Considered
1. Experiment directly inside production modules (`src/forecasting.py`, `src/rag_engine.py`).
2. Isolate experiments in `src/research/` with SQLite provenance tracking and mandatory baseline comparisons.

## Decision
Keep all research tracking (`ExperimentTracker`, `InnovationBacklog`) and ablation runners (`src/research/benchmarks.py`) isolated in `src/research/`. Require dataset SHA-256 provenance, strict chronological splits, and measurable baseline-vs-candidate deltas before any promotion to production.

## Consequences
- **Positive:** Production stability is preserved; negative experimental results (e.g., Ridge lagging `moving_avg_3` / `naive_last` on short non-stationary series) are caught before deployment.
- **Trade-off:** Promoting a validated model requires an explicit PR and production test update.

