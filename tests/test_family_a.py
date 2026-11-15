"""Famille A : saisonnalité + backtest (données synthétiques à saisonnalité connue)."""
import numpy as np
import pandas as pd
import pytest

from src.backtest import run_backtest, summarize, report_markdown
from src.seasonality import (seasonal_calendar, seasonal_drift_forecast, seasonal_drift_table,
                             seasonal_profile)


def seasonal_panel(n_months=60, amp=0.20, noise=0.02, seed=1, provinces=("Lac", "Salamat", "Logone")):
    """Prix = niveau × (1 + amp·cos) : creux en octobre (récolte), pic en juillet (soudure)."""
    rng = np.random.default_rng(seed)
    months = pd.period_range("2020-01", periods=n_months, freq="M")
    rows = []
    for prov in provinces:
        base = 300 + rng.integers(0, 80)
        for m in months:
            season = amp * np.cos(2 * np.pi * (m.month - 7) / 12)  # max en juillet, min en janvier
            rows.append(("WFP", prov, f"{prov} marche", "Millet", m,
                         base * (1 + season) * (1 + rng.normal(0, noise))))
    return pd.DataFrame(rows, columns=["source", "province", "market_name", "commodity_std", "year_month", "value"])


def test_profile_recovers_known_peak_and_trough():
    prof = seasonal_profile(seasonal_panel(), "Millet")
    assert prof.loc[prof["index"].idxmax(), "month"] == 7
    assert prof.loc[prof["index"].idxmin(), "month"] == 1
    assert prof["index"].mean() == pytest.approx(1.0, abs=0.02)


def test_calendar_reliable_on_clear_seasonality():
    cal = seasonal_calendar(seasonal_panel(), "Millet")
    assert cal["status"] == "ok" and cal["reliable"]
    assert 1 in cal["buy_months"] and 7 in cal["sell_months"]
    assert cal["buy_discount_pct"] < 0 < cal["sell_premium_pct"]


def test_calendar_not_reliable_on_pure_noise():
    flat = seasonal_panel(amp=0.0, noise=0.05)
    cal = seasonal_calendar(flat, "Millet")
    assert cal["status"] != "ok" or not cal["reliable"]


def test_calendar_insufficient_data():
    short = seasonal_panel(n_months=10)
    assert seasonal_calendar(short, "Millet")["status"] == "insufficient_data"
    assert seasonal_calendar(seasonal_panel(), "Inconnu")["status"] == "insufficient_data"


def test_seasonal_drift_goes_up_before_peak():
    df = seasonal_panel()
    table = seasonal_drift_table(df)
    up = seasonal_drift_forecast(100.0, 4, table, "Millet", "Lac")   # avril : on monte vers juillet
    down = seasonal_drift_forecast(100.0, 9, table, "Millet", "Lac")  # septembre : on descend
    assert up > 100.0 > down


def test_drift_ignores_gaps():
    df = seasonal_panel()
    df = df[df["year_month"].dt.month != 5]  # plus aucun mois consécutif avril->mai / mai->juin
    table = seasonal_drift_table(df)
    assert np.isfinite(table["global"]).all()


def test_backtest_no_leakage_and_beats_naive_on_seasonal_data():
    df = seasonal_panel()
    res = run_backtest(df, n_origins=12, model_fn=None)
    assert not res.empty
    # chaque prévision doit viser le mois qui suit l'origine
    assert (pd.PeriodIndex(res["target"], freq="M") == pd.PeriodIndex(res["origin"], freq="M") + 1).all()
    s = summarize(res)
    m = s["methods"].set_index("method")
    assert m.loc["seasonal_drift", "MAE_xaf_kg"] < m.loc["naive", "MAE_xaf_kg"]


def test_backtest_changing_future_does_not_change_forecast():
    df = seasonal_panel()
    a = run_backtest(df, n_origins=6, model_fn=None)
    df2 = df.copy()
    last = df2["year_month"].max()
    df2.loc[df2["year_month"] == last, "value"] *= 10  # on corrompt le tout dernier mois
    b = run_backtest(df2, n_origins=6, model_fn=None)
    first_origin = a["origin"].min()  # son mois cible n'est pas le dernier mois
    fa = a[(a["origin"] == first_origin) & (a["method"] == "seasonal_drift")].sort_values("province")["forecast"].to_numpy()
    fb = b[(b["origin"] == first_origin) & (b["method"] == "seasonal_drift")].sort_values("province")["forecast"].to_numpy()
    assert np.allclose(fa, fb)


def test_backtest_with_existing_model_and_report():
    df = seasonal_panel(n_months=48)
    res = run_backtest(df, n_origins=6)
    assert (res["method"] == "model").any()
    s = summarize(res)
    assert 0.0 <= s["coverage_model"] <= 1.0
    md = report_markdown(s, 6)
    assert "Verdict" in md and "Modèle FreeData" in md


def test_backtest_empty_is_safe():
    tiny = seasonal_panel(n_months=5)
    res = run_backtest(tiny, n_origins=3, model_fn=None)
    s = summarize(res)
    assert s["n_points"] == 0
    assert "Pas assez" in report_markdown(s, 3)


# ---------------------------------------------------------------- agent : intention « timing »
def _agent_with_season():
    from src.ai_agent import FreeDataAIAgent
    from src.forecasting import run_forecasting_pipeline
    from src.credit_passport import compute_credit_passport
    kg = seasonal_panel(n_months=60)
    hist, forecast = run_forecasting_pipeline(kg)
    return FreeDataAIAgent(hist, forecast, compute_credit_passport(kg))


@pytest.mark.parametrize("q", [
    "Quand acheter du mil ?", "Quel est le meilleur moment pour vendre mon mil ?",
    "Quand stocker le mil à Lac ?", "Quelle est la période de soudure pour le mil ?",
    "quel mois le mil est le moins cher pour acheter",
])
def test_timing_intent_and_grounded_calendar(q):
    r = _agent_with_season().answer(q)
    assert r["intent"] == "timing"
    assert "janvier" in r["reply"] and "juillet" in r["reply"]
    assert "garantit" in r["reply"] or "tendances passées" in r["reply"]


def test_timing_without_history_is_honest():
    a = _agent_with_season()
    r = a.answer("Quand acheter du sorgho ?")
    assert r["intent"] == "timing"
    assert "pas assez" in r["reply"].lower()


def test_prices_questions_not_hijacked_by_timing():
    a = _agent_with_season()
    assert a.answer("Quel est le prix du mil à Lac ?")["intent"] == "forecast"
    assert a.answer("Où acheter du mil moins cher ?")["intent"] == "opportunity"
