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


def test_flagged_outliers_are_dropped_before_the_model(monkeypatch):
    import dataclasses
    import pandas as pd
    from src import data_loader

    df = pd.DataFrame({"value": [300.0, 12482.0, 310.0], "is_flagged_outlier": [0, 1, 0]})
    assert data_loader.drop_flagged_outliers(df)["value"].tolist() == [300.0, 310.0]

    monkeypatch.setattr(data_loader, "_load_clean_markets_raw", lambda p=None: df)
    monkeypatch.setattr(data_loader, "settings", dataclasses.replace(data_loader.settings, exclude_flagged_outliers=True))
    assert len(data_loader.load_clean_markets()) == 2
    monkeypatch.setattr(data_loader, "settings", dataclasses.replace(data_loader.settings, exclude_flagged_outliers=False))
    assert len(data_loader.load_clean_markets()) == 3


def test_explicit_csv_path_is_used_even_when_supabase_is_configured(monkeypatch, tmp_path):
    import dataclasses
    from src import data_loader
    monkeypatch.setattr(data_loader, "settings", dataclasses.replace(
        data_loader.settings, supabase_url="https://x.supabase.co", supabase_key="k" * 30))
    monkeypatch.setattr(data_loader, "_fetch_supabase_rest_view", lambda: (_ for _ in ()).throw(AssertionError("Supabase appelé")))
    import pytest
    with pytest.raises(FileNotFoundError):
        data_loader._load_clean_markets_raw(str(tmp_path / "absent.csv"))


def test_unify_commodity_case_merges_variants_and_dedupes():
    import pandas as pd
    from src.data_loader import unify_commodity_case
    ym = pd.Period("2025-01")
    df = pd.DataFrame({
        "source": ["WFP"] * 4, "province": ["Lac"] * 4, "market_name": ["M"] * 4,
        "commodity_std": ["Wheat flour", "Wheat flour", "Wheat Flour", "Wheat Flour"],
        "year_month": [ym, ym + 1, ym, ym + 2], "value": [100.0, 110.0, 120.0, 130.0], "is_flagged_outlier": [0, 0, 0, 0],
    })
    out = unify_commodity_case(df)
    assert set(out["commodity_std"]) == {"Wheat flour"}
    assert len(out) == 3  # le doublon (même marché, même mois) est moyenné
    assert out.loc[out["year_month"] == ym, "value"].iloc[0] == 110.0


def test_unify_commodity_case_leaves_distinct_products_alone():
    import pandas as pd
    from src.data_loader import unify_commodity_case
    df = pd.DataFrame({"source": ["WFP"] * 2, "province": ["Lac"] * 2, "market_name": ["M"] * 2,
                       "commodity_std": ["Onions", "Onions (red)"], "year_month": [pd.Period("2025-01")] * 2, "value": [1.0, 2.0]})
    assert set(unify_commodity_case(df)["commodity_std"]) == {"Onions", "Onions (red)"}
