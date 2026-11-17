"""Tests de contrôle d'accès serveur PRO (anomalies, études saisonnières, clés privilégiées)."""
from dataclasses import replace
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from api import server


def _setup_state(monkeypatch, premium_keys: str = "valid-pro-key"):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys=premium_keys))
    fc = pd.DataFrame([{
        "source": "WFP", "province": "Salamat", "market_name": "Am Timan", "commodity_std": "Millet",
        "last_observed_month": "2026-10", "last_observed_price": 250.0, "forecast_month": "2026-11",
        "forecast_t1": 265.0, "ci_low_80": 230.0, "ci_high_80": 300.0, "hist_mae": 20.0,
    }])
    cp = pd.DataFrame([{
        "province": "Salamat", "commodity_std": "Millet", "credit_score": 82.0,
        "grade": "A", "ltv_ratio": 0.7, "cv_pct": 8.0, "max_drawdown_pct": 6.0,
    }])
    anoms = [{
        "source": "WFP", "province": "Salamat", "market_name": "Am Timan", "commodity_std": "Millet",
        "kind": "jump", "severity": "forte", "month": "2026-10", "value": 400.0,
        "reference": 250.0, "change_pct": 60.0, "score": 4.2,
    }]
    studies = [{
        "kind": "seasonality", "commodity_std": "Millet", "province": "",
        "payload": {"status": "ok", "commodity": "Millet", "buy_months": [1], "sell_months": [7]},
    }]
    server.STATE.clear()
    server.STATE.update(server.build_state_from_gold(fc, cp, study_rows=studies, anomaly_rows=anoms))


def test_premium_endpoints_reject_missing_invalid_and_unconfigured_keys(monkeypatch):
    try:
        # 1. Configuration absente -> 503 sans fuite de nom de variable ou de secret
        _setup_state(monkeypatch, premium_keys="")
        c = TestClient(server.app)
        for path in ("/api/v1/anomalies", "/api/v1/studies/seasonality?commodity=Millet"):
            r503 = c.get(path)
            assert r503.status_code == 503
            detail = r503.json()["detail"]
            assert "PREMIUM_API_KEYS" not in detail
            assert "SUPABASE" not in detail

        # 2. Clé absente ou invalide/révoquée -> 403
        _setup_state(monkeypatch, premium_keys="active-key-1")
        for path in ("/api/v1/anomalies", "/api/v1/studies/seasonality?commodity=Millet"):
            assert c.get(path).status_code == 403
            assert c.get(path, headers={"X-Premium-Key": "revoked-or-wrong"}).status_code == 403

        # 3. Clé valide -> 200
        hdr = {"X-Premium-Key": "active-key-1"}
        r_anom = c.get("/api/v1/anomalies", headers=hdr)
        assert r_anom.status_code == 200 and r_anom.json()["count"] == 1
        r_stud = c.get("/api/v1/studies/seasonality?commodity=Millet", headers=hdr)
        assert r_stud.status_code == 200
    finally:
        server.STATE.clear()


def test_fetch_gold_table_uses_service_role_for_privileged_tables(monkeypatch):
    monkeypatch.setattr(
        server,
        "settings",
        replace(
            server.settings,
            supabase_url="https://example.supabase.co",
            supabase_key="anon-public-key",
            supabase_service_key="service-role-secret",
        ),
    )
    seen_auth: list[str] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        seen_auth.append(headers["apikey"])
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = []
        return resp

    monkeypatch.setattr(server.requests, "get", fake_get)
    server._fetch_gold_table("table_ml_forecasts", privileged=False)
    server._fetch_gold_table("table_ml_anomalies", privileged=True)
    assert seen_auth == ["anon-public-key", "service-role-secret"]

