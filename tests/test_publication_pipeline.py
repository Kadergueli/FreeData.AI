"""Tests pour le pipeline de publication observable (`src/publication_pipeline.py`)."""
from unittest.mock import MagicMock

import pandas as pd

from src.publication_pipeline import run_publication_pipeline


def _valid_df() -> pd.DataFrame:
    months = pd.period_range("2025-01", periods=14, freq="M")
    rows = []
    for prov, base in [("Lac", 220.0), ("Salamat", 260.0)]:
        for m in months:
            rows.append({
                "source": "WFP",
                "province": prov,
                "market_name": f"{prov} m",
                "commodity_std": "Millet",
                "year_month": m,
                "value": base,
            })
    return pd.DataFrame(rows)


def test_successful_pipeline_and_observability(monkeypatch):
    published_calls = []
    purged_calls = []

    def fake_pub(fc, cp, anom, studies, run_ts):
        published_calls.append(run_ts)
        return {"table_ml_forecasts": len(fc), "table_ml_credit_passport": len(cp)}

    def fake_post(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        return resp

    def fake_get(url, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"status": "ok", "series_count": 2}
        return resp

    monkeypatch.setattr("src.publication_pipeline.requests.post", fake_post)
    monkeypatch.setattr("src.publication_pipeline.requests.get", fake_get)

    rep = run_publication_pipeline(
        loader_fn=_valid_df,
        publish_fn=fake_pub,
        purge_fn=lambda ts: purged_calls.append(ts),
        api_base_url="https://api.example.com",
        admin_token="super-secret-admin",
        retry_delay_s=0.0,
    )
    assert rep["pipeline_status"] == "succeeded"
    assert rep["API_refresh_status"] == "verified"
    assert rep["last_successful_publication"] is not None
    assert rep["rows_published"]["table_ml_forecasts"] == 2
    assert len(published_calls) == 1 and len(purged_calls) == 1
    assert "execution_id" in rep and "start_time" in rep and "end_time" in rep


def test_validation_failure_stops_before_publication():
    pub_called = False

    def fake_pub(*args):
        nonlocal pub_called
        pub_called = True
        return {}

    rep = run_publication_pipeline(
        loader_fn=lambda: pd.DataFrame(),
        publish_fn=fake_pub,
    )
    assert rep["pipeline_status"] == "failed"
    assert pub_called is False
    assert rep["rows_published"] == {}
    assert len(rep["validation_errors"]) >= 1


def test_publication_failure_stops_before_purge_and_refresh(monkeypatch):
    purged = False
    refreshed = False

    def fail_pub(*args):
        raise RuntimeError("supabase 500")

    monkeypatch.setattr("src.publication_pipeline.requests.post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not refresh")))
    rep = run_publication_pipeline(
        loader_fn=_valid_df,
        publish_fn=fail_pub,
        purge_fn=lambda ts: None,
        api_base_url="https://api.example.com",
        admin_token="tok",
    )
    assert rep["pipeline_status"] == "failed"
    assert rep["API_refresh_status"] == "skipped"
    assert not purged and not refreshed


def test_partial_publication_integrity_failure_prevents_purge():
    purged = []
    rep = run_publication_pipeline(
        loader_fn=_valid_df,
        publish_fn=lambda fc, cp, a, s, ts: {"table_ml_forecasts": 2, "table_ml_credit_passport": 0},
        purge_fn=lambda ts: purged.append(ts),
    )
    assert rep["pipeline_status"] == "failed"
    assert purged == []
    assert rep["last_successful_publication"] is None


def test_api_refresh_failure_and_retry_behavior(monkeypatch, caplog):
    attempts = {"n": 0}

    def flaky_post(url, headers=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("api restarting")
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        return resp

    def ok_get(url, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"status": "ok", "series_count": 2}
        return resp

    monkeypatch.setattr("src.publication_pipeline.requests.post", flaky_post)
    monkeypatch.setattr("src.publication_pipeline.requests.get", ok_get)

    rep_retry = run_publication_pipeline(
        loader_fn=_valid_df,
        publish_fn=lambda fc, cp, a, s, ts: {"table_ml_forecasts": len(fc), "table_ml_credit_passport": len(cp)},
        purge_fn=lambda ts: None,
        api_base_url="https://api.example.com",
        admin_token="secret-admin-token-xyz",
        max_refresh_retries=3,
        retry_delay_s=0.0,
    )
    assert attempts["n"] == 3
    assert rep_retry["pipeline_status"] == "succeeded"
    assert rep_retry["API_refresh_status"] == "verified"

    # Échec définitif -> conserve last_successful_publication + aucun secret dans les logs
    monkeypatch.setattr("src.publication_pipeline.requests.post", MagicMock(side_effect=ConnectionError("down")))
    rep_fail = run_publication_pipeline(
        loader_fn=_valid_df,
        publish_fn=lambda fc, cp, a, s, ts: {"table_ml_forecasts": len(fc), "table_ml_credit_passport": len(cp)},
        purge_fn=lambda ts: None,
        api_base_url="https://api.example.com",
        admin_token="secret-admin-token-xyz",
        max_refresh_retries=2,
        retry_delay_s=0.0,
    )
    assert rep_fail["pipeline_status"] == "partial_refresh_pending"
    assert rep_fail["API_refresh_status"] == "failed"
    assert rep_fail["last_successful_publication"] is not None
    assert "secret-admin-token-xyz" not in caplog.text


def test_duplicate_execution_is_idempotent():
    r1 = run_publication_pipeline(loader_fn=_valid_df, dry_run=True)
    r2 = run_publication_pipeline(loader_fn=_valid_df, dry_run=True)
    assert r1["execution_id"] != r2["execution_id"]
    assert r1["rows_processed"] == r2["rows_processed"]
    assert r1["pipeline_status"] == "succeeded" and r2["pipeline_status"] == "succeeded"

