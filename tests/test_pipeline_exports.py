import json

import numpy as np
import pandas as pd

from scripts.update_predictions import build_exports, _records
from src.freshness import filter_fresh


def test_exports_contain_model_alert_columns(pipeline_outputs):
    _, _, forecast, passport = pipeline_outputs
    fc_export, _ = build_exports(forecast, passport)
    assert {"predicted_price", "deviation_pct", "last_observed_price"} <= set(fc_export.columns)


def test_exported_values_are_the_models_own_outputs(pipeline_outputs):
    """Le script ne recalcule rien : les valeurs publiées sont celles du modèle."""
    _, _, forecast, passport = pipeline_outputs
    fc_export, _ = build_exports(forecast, passport)
    pd.testing.assert_series_equal(fc_export["forecast_t1"], forecast["forecast_t1"])
    pd.testing.assert_series_equal(fc_export["deviation_pct"], forecast["deviation_pct"])


def test_records_are_valid_json_even_with_nan_and_inf():
    df = pd.DataFrame({"a": [1.0, np.nan, np.inf], "b": ["x", "y", "z"]})
    records = _records(df)
    json.dumps(records, allow_nan=False)  # lèverait ValueError si NaN/inf subsistaient
    assert records[1]["a"] is None and records[2]["a"] is None


def test_filter_fresh_drops_stale_series_only(pipeline_outputs):
    _, _, forecast, _ = pipeline_outputs
    fresh, n_excluded = filter_fresh(forecast, "last_observed_month", 3)
    assert n_excluded == 1
    assert not ((fresh["province"] == "Lac") & (fresh["commodity_std"] == "Maize (white)")).any()
    # aucune valeur modifiée
    kept = forecast.loc[fresh.index, "forecast_t1"]
    pd.testing.assert_series_equal(fresh["forecast_t1"], kept)


def test_filter_fresh_disabled_with_zero():
    df = pd.DataFrame({"last_observed_month": ["2020-01", "2025-12"]})
    out, n = filter_fresh(df, "last_observed_month", 0)
    assert n == 0 and len(out) == 2


def test_filter_fresh_accepts_period_column():
    df = pd.DataFrame({"year_month": pd.period_range("2025-01", periods=12, freq="M")})
    out, n = filter_fresh(df, "year_month", 3)
    assert len(out) == 4 and n == 8
