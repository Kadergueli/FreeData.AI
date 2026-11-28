"""Regression tests for strict CSV validation and leakage-safe chronological evaluation."""
import numpy as np
import pandas as pd
import pytest

from src.ml_benchmark import DatasetSpec, _benchmark_regression, parse_and_validate_csv
from src.ml_engine import evaluate_ridge_chronological


def _spec(task_type="forecasting", *, time_column="month", target="price", features=None):
    return DatasetSpec(
        domain="economy",
        task_type=task_type,
        feature_columns=features or (["feature"] if task_type != "forecasting" else []),
        target_column=target,
        time_column=time_column,
        dataset_provenance={"source": "test fixture", "license": "CC0"},
    )


def test_csv_rejects_infinite_numeric_values():
    spec = _spec(features=["x"])
    raw = b"month,x,y\n2025-01,1,10\n2025-02,inf,11\n2025-03,3,12\n2025-04,4,13\n2025-05,5,14\n2025-06,6,15\n2025-07,7,16\n2025-08,8,17\n2025-09,9,18\n2025-10,10,19\n"
    with pytest.raises(ValueError, match="infinie ou non finie"):
        parse_and_validate_csv(raw, spec)


def test_csv_rejects_invalid_timestamps():
    spec = _spec()
    raw = b"month,price\n2025-01,10\n2025-02,11\n2025-03,12\n2025-04,13\n2025-05,14\n2025-06,15\n2025-07,16\n2025-08,17\n2025-09,18\nnot-a-date,19\n"
    with pytest.raises(ValueError, match="date.*invalide"):
        parse_and_validate_csv(raw, spec)


def test_csv_rejects_duplicate_timestamps_for_forecasting():
    spec = _spec()
    raw = b"month,price\n2025-01,10\n2025-02,11\n2025-03,12\n2025-04,13\n2025-05,14\n2025-06,15\n2025-07,16\n2025-08,17\n2025-09,18\n2025-09,19\n"
    with pytest.raises(ValueError, match="date dupliquée"):
        parse_and_validate_csv(raw, spec)


def test_classification_rejects_fractional_labels():
    spec = _spec(task_type="classification", time_column=None, target="label", features=["x"])
    raw = b"x,label\n1,0\n2,1\n3,0\n4,1\n5,0\n6,1\n7,0\n8,1\n9,0\n10,0.5\n"
    with pytest.raises(ValueError, match="classes entières"):
        parse_and_validate_csv(raw, spec)


def test_regression_with_time_column_uses_chronological_holdout():
    dates = pd.date_range("2024-01-01", periods=40, freq="MS", tz="UTC")
    frame = pd.DataFrame({
        "month": dates,
        "x": np.arange(40, dtype=float),
        "y": 100.0 + np.arange(40, dtype=float) * 2.0,
    })
    spec = _spec(task_type="regression", features=["x"], target="y")
    candidates = _benchmark_regression(frame, spec)
    assert candidates
    assert all(candidate["protocol"].startswith("chronological_75_25") for candidate in candidates)


def test_ridge_alpha_selection_is_independent_of_final_test_tail():
    prices = 250.0 + np.arange(72, dtype=float) * 1.7 + 12.0 * np.sin(np.arange(72) * 2.0 * np.pi / 12.0)
    baseline = evaluate_ridge_chronological(prices)
    changed_test = prices.copy()
    changed_test[-1] += 5000.0
    changed = evaluate_ridge_chronological(changed_test)

    assert baseline["status"] == changed["status"] == "evaluated"
    assert baseline["best_alpha"] == changed["best_alpha"]
    assert baseline["validation_ridge_mae_xaf_kg"] == changed["validation_ridge_mae_xaf_kg"]
    assert baseline["evaluation_protocol"] == "chronological_train_validation_test_60_20_20"
    assert baseline["test_samples"] > 0
    assert baseline["ridge_mae_xaf_kg"] != changed["ridge_mae_xaf_kg"]
