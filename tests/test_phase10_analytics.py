"""Phase 10 tests: AnalyticsService, profiling, statistics, chronological benchmark, geo, AI queries, and scale."""
import time
from dataclasses import replace

import pandas as pd

from api import server
from src.analytics import AnalyticsService


def _sample_dfs():
    fc = pd.DataFrame([
        {
            "source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 210.0,
            "forecast_month": "2026-11", "forecast_t1": 220.0, "ci_low_80": 195.0, "ci_high_80": 245.0, "hist_mae": 18.0,
        },
        {
            "source": "WFP", "province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 340.0,
            "forecast_month": "2026-11", "forecast_t1": 350.0, "ci_low_80": 315.0, "ci_high_80": 385.0, "hist_mae": 22.0,
        },
        {
            "source": "WFP", "province": "Batha", "market_name": "Ati", "commodity_std": "Sorghum (red)",
            "last_observed_month": "2026-10", "last_observed_price": 240.0,
            "forecast_month": "2026-11", "forecast_t1": 245.0, "ci_low_80": 220.0, "ci_high_80": 270.0, "hist_mae": 15.0,
        },
    ])
    dates = pd.date_range("2025-11-01", periods=12, freq="MS")
    hist_rows = []
    for i, dt in enumerate(dates):
        hist_rows.append({"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "date": dt.strftime("%Y-%m-%d"), "price": 180.0 + i * 5.0})
        hist_rows.append({"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "date": dt.strftime("%Y-%m-%d"), "price": 290.0 + i * 6.0})
    hist = pd.DataFrame(hist_rows)
    cp = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "cv_pct": 12.5, "ltv_ratio": 0.8, "max_drawdown_pct": 6.0},
        {"province": "Batha", "commodity_std": "Sorghum (red)", "credit_score": 76.0, "grade": "B", "cv_pct": 8.0, "ltv_ratio": 0.7, "max_drawdown_pct": 5.0},
    ])
    return fc, hist, cp


def test_profiler_statistics_geospatial_and_trends():
    fc, hist, cp = _sample_dfs()
    svc = AnalyticsService()

    prof = svc.get_profile(fc, hist)
    assert prof["forecast_rows"] == 3
    assert prof["historical_rows"] == 24
    assert prof["forecast_duplicate_rows"] == 0

    summary = svc.get_summary(fc, cp, commodity="Millet")
    assert summary["descriptive"]["count"] == 2
    assert summary["descriptive"]["stats"]["median"] == 275.0
    assert summary["most_volatile_commodities"][0]["commodity"] == "Millet"

    corr = svc.stats.province_correlation(hist, "Millet", "Lac", "N'Djamena")
    assert corr["available"] is True
    assert corr["pearson_r"] > 0.9
    assert "causalité" in corr["methodological_note"]

    geo = svc.get_regional_comparison(fc, commodity="Millet")
    assert geo["highest_province"]["province"] == "N'Djamena"
    assert geo["lowest_province"]["province"] == "Lac"
    assert geo["spatial_spread_xaf_kg"] == 130.0
    assert "Batha" in geo["missing_provinces"]

    trends = svc.get_trends(hist, commodity="Millet", province="Lac")
    assert trends["change_12m_pct"] is not None
    assert trends["unit"] == "XAF/kg"


def test_chronological_forecast_benchmark_and_insufficient_history():
    _, hist, _ = _sample_dfs()
    svc = AnalyticsService()

    res_ok = svc.get_forecast_benchmark(hist, commodity="Millet", province="Lac")
    assert res_ok["status"] == "evaluated"
    assert len(res_ok["models"]) == 3
    assert res_ok["best_model"] in {"naive_last_value", "moving_average_3m", "exponential_smoothing_0.4"}

    res_short = svc.get_forecast_benchmark(hist.head(4), commodity="Millet", province="Lac")
    assert res_short["status"] == "insufficient_history"
    assert res_short["models"] == []


def test_ai_analytical_queries_and_large_dataset_performance(monkeypatch):
    fc, hist, cp = _sample_dfs()
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    st = server.build_state_from_gold(fc, cp)
    agent = st["agent"]
    agent.provider.hist_df = hist

    r_reg = agent.answer_analytical_query("Quelles régions ont les prix les plus élevés ?", commodity="Millet")
    assert "N'Djamena" in r_reg["reply"] and "XAF/kg" in r_reg["reply"]

    r_vol = agent.answer_analytical_query("Quels produits ont la plus grande volatilité ?")
    assert "Mil" in r_vol["reply"] and "CV moyen" in r_vol["reply"]

    r_tr = agent.answer_analytical_query("Comment ont évolué les prix sur les 12 derniers mois ?", commodity="Millet", province="Lac")
    assert "XAF/kg" in r_tr["reply"] and "%" in r_tr["reply"]

    # Larger dataset performance check (5,000 rows)
    big_fc = pd.concat([fc] * 1700, ignore_index=True)
    svc = AnalyticsService()
    t0 = time.perf_counter()
    _ = svc.get_summary(big_fc, cp)
    _ = svc.get_regional_comparison(big_fc, commodity="Millet")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 1000.0

