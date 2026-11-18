"""Tests for the continuous research & experimentation framework."""
from __future__ import annotations

import pandas as pd
import pytest

from src.research.benchmarks import run_rag_retrieval_ablation
from src.research.experiment_tracker import (
    DatasetProvenance,
    ExperimentTracker,
    InnovationBacklog,
    compute_file_sha256,
)


def test_experiment_tracker_logs_provenance_and_deltas(tmp_path):
    sample_csv = tmp_path / "sample.csv"
    sample_csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    tracker = ExperimentTracker(tmp_path / "exp.db")
    sha = compute_file_sha256(sample_csv)
    assert len(sha) == 64

    tracker.register_dataset(
        DatasetProvenance(
            dataset_id="ds_test",
            source_path=str(sample_csv),
            sha256=sha,
            row_count=2,
            date_range="2025-01..2025-02",
        )
    )

    logged = tracker.log_experiment(
        name="ridge_vs_naive",
        domain="agriculture",
        hypothesis="Ridge improves MAE",
        dataset_id="ds_test",
        method="ridge",
        parameters={"alpha": 1.0},
        split_protocol="chronological_70_30",
        seed=42,
        baseline_metrics={"mae": 25.0, "rmse": 30.0},
        candidate_metrics={"mae": 21.5, "rmse": 27.0},
        limitations="Small test sample",
        status="experimental",
    )
    assert logged["delta_metrics"]["mae"] == -3.5
    assert logged["delta_metrics"]["rmse"] == -3.0

    exps = tracker.list_experiments(domain="agriculture")
    assert len(exps) == 1
    assert exps[0]["status"] == "experimental"

    tracker.update_experiment_status(logged["experiment_id"], "validated")
    assert tracker.list_experiments()[0]["status"] == "validated"

    with pytest.raises(ValueError):
        tracker.update_experiment_status(logged["experiment_id"], "invalid_status")


def test_innovation_backlog_stage_transitions(tmp_path):
    tracker = ExperimentTracker(tmp_path / "exp.db")
    backlog = InnovationBacklog(tracker)

    idea = backlog.add_idea(
        title="Mondrian conformal intervals",
        domain="agriculture",
        problem_statement="Improve Fish (dry) coverage",
        priority="P1",
    )
    assert idea["stage"] == "proposed"

    backlog.transition_stage(idea["idea_id"], "prototype", linked_experiment_id="exp_123")
    items = backlog.list_ideas(stage="prototype")
    assert len(items) == 1
    assert items[0]["linked_experiment_id"] == "exp_123"


def test_rag_ablation_runs_on_repo_docs():
    res = run_rag_retrieval_ablation(".")
    assert res["status"] == "completed"
    cfgs = res["configs"]
    assert "prod_hybrid_65_35_900" in cfgs
    assert cfgs["prod_hybrid_65_35_900"]["mrr"] >= cfgs["vector_only_900"]["mrr"]

