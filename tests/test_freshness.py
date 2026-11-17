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

