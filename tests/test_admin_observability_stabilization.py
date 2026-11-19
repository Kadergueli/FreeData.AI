from __future__ import annotations

import dataclasses
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server


class _DummyResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _healthy_state() -> dict:
    return {
        "mode": "gold_ml",
        "agent": object(),
        "forecast_df": pd.DataFrame([{"commodity_name": "Riz", "forecast_price": 450.0}]),
        "freshness": {
            "forecasts": {
                "latest_observation_month": "2026-10",
                "data_age_months": 1,
                "freshness_status": "fresh",
            }
        },
    }


def test_probe_providers_passive_not_configured_and_configured(monkeypatch):
    monkeypatch.setattr(
        server,
        "settings",
        dataclasses.replace(server.settings, llm_api_key="", embed_api_key=""),
    )
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    res_empty = server._probe_providers_health(_healthy_state(), live_probe=False)
    assert res_empty["live_probe_executed"] is False
    assert res_empty["checked_at_utc"]
    assert res_empty["services"]["supabase"] == "NOT_CONFIGURED"
    assert res_empty["services"]["groq"] == "NOT_CONFIGURED"
    assert res_empty["services"]["jina"] == "NOT_CONFIGURED"
    assert res_empty["services"]["ml_engine"] == "CONNECTED"
    assert res_empty["services"]["rag_engine"] == "CONNECTED"
    assert res_empty["services"]["document_indexing"] == "DEGRADED"
    assert res_empty["services"]["background_jobs"] == "CONNECTED"

    monkeypatch.setattr(
        server,
        "settings",
        dataclasses.replace(
            server.settings,
            llm_api_key="gsk_secret_live_key_12345",
            embed_api_key="jina_secret_live_key_98765",
        ),
    )
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://user:supersecret@db.example.com:5432/postgres")

    with patch.object(server.requests, "get", side_effect=AssertionError("passive must not call network")), \
         patch.object(server.requests, "post", side_effect=AssertionError("passive must not call network")):
        res_cfg = server._probe_providers_health(_healthy_state(), live_probe=False)

    assert res_cfg["services"]["supabase"] == "CONFIGURED"
    assert res_cfg["services"]["groq"] == "CONFIGURED"
    assert res_cfg["services"]["jina"] == "CONFIGURED"
    assert res_cfg["services"]["document_indexing"] == "CONNECTED"

    serialized = json.dumps(res_cfg)
    assert "gsk_secret_live_key_12345" not in serialized
    assert "jina_secret_live_key_98765" not in serialized
    assert "supersecret" not in serialized


def test_probe_providers_live_states_connected_degraded_error_unavailable(monkeypatch):
    monkeypatch.setattr(
        server,
        "settings",
        dataclasses.replace(
            server.settings,
            llm_api_key="gsk_test_key_abc",
            embed_api_key="jina_test_key_xyz",
        ),
    )
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@host/db")

    # 1. All connected
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.fetchone.return_value = (1,)

    with patch("src.db.pg_connect", return_value=fake_conn), \
         patch.object(server.requests, "get", return_value=_DummyResp(200)), \
         patch.object(server.requests, "post", return_value=_DummyResp(200)):
        res_ok = server._probe_providers_health(_healthy_state(), live_probe=True)

    assert res_ok["live_probe_executed"] is True
    assert res_ok["services"]["supabase"] == "CONNECTED"
    assert res_ok["services"]["groq"] == "CONNECTED"
    assert res_ok["services"]["jina"] == "CONNECTED"

    # 2. Degraded (429) & Error (401) & DB failure (Unavailable)
    with patch("src.db.pg_connect", side_effect=RuntimeError("pg down")), \
         patch.object(server.requests, "get", return_value=_DummyResp(429)), \
         patch.object(server.requests, "post", return_value=_DummyResp(401)):
        res_mixed = server._probe_providers_health(_healthy_state(), live_probe=True)

    assert res_mixed["services"]["supabase"] == "UNAVAILABLE"
    assert res_mixed["services"]["groq"] == "DEGRADED"
    assert res_mixed["services"]["jina"] == "ERROR"
    assert res_mixed["services"]["document_indexing"] == "DEGRADED"

    # 3. Network timeout -> Unavailable (never raises)
    with patch("src.db.pg_connect", side_effect=TimeoutError("timeout")), \
         patch.object(server.requests, "get", side_effect=TimeoutError("groq timeout")), \
         patch.object(server.requests, "post", side_effect=ConnectionError("jina down")):
        res_down = server._probe_providers_health({}, live_probe=True)

    assert res_down["services"]["supabase"] == "UNAVAILABLE"
    assert res_down["services"]["groq"] == "UNAVAILABLE"
    assert res_down["services"]["jina"] == "UNAVAILABLE"
    assert res_down["services"]["ml_engine"] == "UNAVAILABLE"
    assert res_down["services"]["rag_engine"] == "DEGRADED"


def test_operational_warnings_generation_and_clean_state(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    clean_ph = {
        "services": {
            "supabase": "CONNECTED",
            "groq": "CONNECTED",
            "jina": "CONNECTED",
            "ml_engine": "CONNECTED",
            "rag_engine": "CONNECTED",
            "document_indexing": "CONNECTED",
            "background_jobs": "CONNECTED",
        },
        "require_signed_user_auth": True,
    }
    clean_metrics = {"total_requests": 100, "error_5xx": 1, "avg_latency_ms": 120.0}
    clean_fresh = {"freshness_status": "fresh"}
    assert server._build_operational_warnings(clean_ph, clean_metrics, clean_fresh) == []

    monkeypatch.setenv("RENDER", "true")
    bad_ph = {
        "services": {
            "supabase": "UNAVAILABLE",
            "groq": "ERROR",
            "jina": "DEGRADED",
        },
        "require_signed_user_auth": False,
    }
    bad_metrics = {"total_requests": 20, "error_5xx": 3, "avg_latency_ms": 3500.0}
    bad_fresh = {"freshness_status": "stale"}
    warnings = server._build_operational_warnings(bad_ph, bad_metrics, bad_fresh)
    codes = {w["code"] for w in warnings}
    assert "SUPABASE_UNAVAILABLE" in codes
    assert "GROQ_UNAVAILABLE" in codes
    assert "JINA_DEGRADED" in codes
    assert "HIGH_5XX_RATE" in codes
    assert "HIGH_LATENCY" in codes
    assert "STALE_MARKET_DATA" in codes
    assert "UNSIGNED_AUTH_ENABLED" in codes


def test_http_error_classification_categories():
    assert server._classify_http_error(200) is None
    assert server._classify_http_error(401) == "auth_failure"
    assert server._classify_http_error(403) == "authorization_failure"
    assert server._classify_http_error(429) == "quota_violation"
    assert server._classify_http_error(422) == "validation_error"
    assert server._classify_http_error(400) == "validation_error"
    assert server._classify_http_error(500) == "server_error"
    assert server._classify_http_error(503) == "server_error"


def test_admin_overview_rbac_and_probe_resilience(monkeypatch, tmp_path):
    admin = server.AdminService(db_path=tmp_path / "admin.db")
    sub_store = server.SubscriptionStore(db_path=tmp_path / "subs.db")
    auth_store = server.AuthStore(db_path=tmp_path / "auth.db")
    registry = server.LicensingRegistry()

    # Unauthorized role rejected with 403
    with pytest.raises(HTTPException) as exc:
        server.admin_overview_endpoint(
            live_probe=False,
            actor_info=("intruder", "unknown_role"),
            state=_healthy_state(),
            admin=admin,
            sub_store=sub_store,
            auth_store=auth_store,
            registry=registry,
        )
    assert exc.value.status_code == 403

    # Authorized super_admin succeeds even when external live probes fail
    monkeypatch.setattr(
        server,
        "settings",
        dataclasses.replace(
            server.settings,
            llm_api_key="gsk_never_expose_me",
            embed_api_key="jina_never_expose_me",
        ),
    )
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with patch.object(server.requests, "get", side_effect=RuntimeError("network down")), \
         patch.object(server.requests, "post", side_effect=RuntimeError("network down")):
        payload = server.admin_overview_endpoint(
            live_probe=True,
            actor_info=("kader", "super_admin"),
            state=_healthy_state(),
            admin=admin,
            sub_store=sub_store,
            auth_store=auth_store,
            registry=registry,
        )

    assert payload["api_health"]["status"] == "ok"
    assert "error_categories" in payload["api_metrics"]
    assert "recent_errors" in payload["api_metrics"]
    assert payload["providers_health"]["services"]["groq"] == "UNAVAILABLE"
    assert payload["providers_health"]["services"]["jina"] == "UNAVAILABLE"
    assert any(w["code"] == "GROQ_UNAVAILABLE" for w in payload["operational_warnings"])

    raw = json.dumps(payload, default=str)
    assert "gsk_never_expose_me" not in raw
    assert "jina_never_expose_me" not in raw
