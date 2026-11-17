"""Tests pour Agricultural Market Risk & Stability Index (`src/credit_passport.py` et API)."""
import numpy as np
import pandas as pd
import pytest

from src.credit_passport import (
    compute_credit_passport,
    compute_recommended_max_loan,
)


def _panel(n_months: int = 24, noise: float = 0.02, prov: str = "Lac", comm: str = "Millet") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    months = pd.period_range("2024-01", periods=n_months, freq="M")
    return pd.DataFrame({
        "province": prov,
        "commodity_std": comm,
        "year_month": months,
        "value": [250.0 * (1.0 + rng.normal(0, noise)) for _ in range(n_months)],
    })


def test_minimum_coverage_and_missing_observations():
    assert compute_credit_passport(pd.DataFrame()).empty
    short = _panel(n_months=5)
    assert compute_credit_passport(short).empty

    with_nans = _panel(n_months=12)
    with_nans.loc[:2, "value"] = np.nan
    out = compute_credit_passport(with_nans)
    assert len(out) == 1
    assert out.iloc[0]["obs_months"] == 9


def test_grade_boundaries_and_volatility_drawdown():
    stable = _panel(n_months=36, noise=0.01, prov="Lac")
    volatile = _panel(n_months=10, noise=0.35, prov="Borkou")
    df = pd.concat([stable, volatile], ignore_index=True)
    out = compute_credit_passport(df).set_index("province")

    assert out.loc["Lac", "credit_score"] >= 70
    assert out.loc["Lac", "grade"].startswith("A")
    assert out.loc["Lac", "ltv_ratio"] == 0.80
    assert out.loc["Lac", "market_stability_index"] == out.loc["Lac", "credit_score"]
    assert out.loc["Borkou", "credit_score"] < out.loc["Lac", "credit_score"]


def test_ltv_calculation_and_collateral_bounds():
    assert compute_recommended_max_loan(1_000_000, 0.80) == 800_000
    assert compute_recommended_max_loan(0, 0.80) == 0
    with pytest.raises(ValueError):
        compute_recommended_max_loan(-100, 0.80)
