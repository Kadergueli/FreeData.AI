"""Tests pour la validation réelle de fraîcheur des données (`src/freshness.py` et `/api/v1/health`)."""
from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from api import server
from src.freshness import assess_dataset_freshness


def test_freshness_current_month_is_fresh():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({"year_month": ["2026-09", "2026-11"]})
    res = assess_dataset_freshness(
        df, "year_month", max_staleness_months=3, now_utc=now, last_successful_computation_at=now
    )
    assert res["latest_observation_month"] == "2026-11"
    assert res["data_age_months"] == 0
    assert res["freshness_status"] == "fresh"
    assert res["last_successful_computation_at"] == "2026-11-17T12:00:00+00:00"


def test_freshness_three_months_ago_is_aging():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({"year_month": ["2026-07", "2026-08"]})
    res = assess_dataset_freshness(df, "year_month", max_staleness_months=3, now_utc=now)
    assert res["latest_observation_month"] == "2026-08"
    assert res["data_age_months"] == 3
    assert res["freshness_status"] == "aging"


def test_freshness_twelve_months_ago_is_stale():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({"year_month": ["2025-11"]})
    res = assess_dataset_freshness(df, "year_month", max_staleness_months=3, now_utc=now)
    assert res["latest_observation_month"] == "2025-11"
    assert res["data_age_months"] == 12
    assert res["freshness_status"] == "stale"


def test_freshness_empty_and_missing_dates_are_unavailable():
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    empty_res = assess_dataset_freshness(pd.DataFrame(), "year_month", now_utc=now)
    assert empty_res["freshness_status"] == "unavailable"
    assert empty_res["data_age_months"] is None

    missing_res = assess_dataset_freshness(
        pd.DataFrame({"year_month": [None, "", "invalid"]}), "year_month", now_utc=now
    )
    assert missing_res["freshness_status"] == "unavailable"
    assert missing_res["latest_observation_month"] is None


def test_freshness_year_boundary_calculation():
    now = datetime(2026, 2, 10, 8, 30, tzinfo=timezone.utc)
    df = pd.DataFrame({"last_observed_month": ["2025-12"]})
    res = assess_dataset_freshness(df, "last_observed_month", max_staleness_months=3, now_utc=now)
    assert res["data_age_months"] == 2
    assert res["freshness_status"] == "fresh"




def test_series_freshness_report_keeps_stale_series_and_quality_labels():
    from src.freshness import build_series_freshness_report

    now = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "source": ["WFP"] * 4,
        "commodity_std": ["Millet"] * 4,
        "province": ["Salamat"] * 4,
        "market_name": ["Bol", "Bol", "Bol", "Bol"],
        "last_observed_month": ["2026-11", "2026-08", "2026-07", "invalid"],
        "forecast_quality": ["standard", "standard", "reduced", "reduced"],
        "interval_status": ["calibrated_80", "calibrated_80", "wide_reduced", "uncalibrated"],
    })
    report = build_series_freshness_report(df, max_staleness_months=3, now_utc=now)
    assert report["freshness_status"].tolist() == ["fresh", "aging", "stale", "unavailable"]
    assert report.loc[2, "forecast_quality"] == "reduced"
    assert report.loc[2, "interval_status"] == "wide_reduced"
    assert len(report) == 4



def test_gold_freshness_uses_persisted_calculation_timestamp(monkeypatch):
    monkeypatch.setattr(server, "FreeDataAIAgent", lambda *args, **kwargs: object())
    now_month = pd.Period(datetime.now(timezone.utc).strftime("%Y-%m"), freq="M")
    obs_month = str(now_month)
    forecasts = pd.DataFrame({
        "source": ["WFP"],
        "province": ["Salamat"],
        "market_name": ["Bol"],
        "commodity_std": ["Millet"],
        "last_observed_month": [obs_month],
        "forecast_month": [str(now_month + 1)],
        "forecast_t1": [510.0],
        "date_calcul": ["2026-11-15 20:39:25"],
    })
    historical = pd.DataFrame({"year_month": [obs_month]})
    state = server._finalize_state(
        historical, forecasts, pd.DataFrame(), "gold_fast_read", "stored"
    )
    freshness = state["freshness"]["forecasts"]
    assert freshness["last_successful_computation_at"] == "2026-11-15T20:39:25+00:00"
    assert freshness["last_publication_at"] is None
    assert len(state["series_freshness"]) == 1


def test_market_freshness_endpoint_filters_and_summarizes_series():
    report = pd.DataFrame({
        "source": ["WFP", "FEWS NET"],
        "commodity_std": ["Millet", "Millet"],
        "province": ["Salamat", "Salamat"],
        "market_name": ["Bol", "Am-Timan"],
        "last_observed_month": ["2026-10", "2026-06"],
        "data_age_months": [1, 5],
        "freshness_status": ["fresh", "stale"],
        "forecast_quality": ["standard", "reduced"],
        "interval_status": ["calibrated_80", "wide_reduced"],
        "date_calcul": ["2026-11-15", "2026-11-15"],
    })
    payload = server.market_data_freshness_endpoint(
        commodity="Millet", province="Salamat", market=None, source=None,
        status="stale", limit=100, state={"series_freshness": report},
    )
    assert payload["summary"] == {"fresh": 1, "stale": 1}
    assert payload["count"] == 1
    assert payload["items"][0]["market_name"] == "Am-Timan"
    assert payload["items"][0]["forecast_quality"] == "reduced"
