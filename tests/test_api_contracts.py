"""Tests de contrat d'intégration API <-> Frontend, sécurité client et validité des configs."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from api import server

ROOT = Path(__file__).resolve().parents[1]


def test_api_contracts_match_flutter_requirements(gold_tables):
    fc_gold, cp_gold = gold_tables
    server.STATE.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold))
    try:
        c = TestClient(server.app)

        r_health = c.get("/api/v1/health")
        assert r_health.status_code == 200
        h = r_health.json()
        for k in ("status", "backend", "engine_mode", "freshness_status", "series_count"):
            assert k in h

        r_meta = c.get("/api/v1/metadata")
        assert r_meta.status_code == 200
        m = r_meta.json()
        for k in ("products", "provinces", "markets", "periods_covered", "track_records"):
            assert k in m

        r_fc = c.get("/api/v1/forecasts")
        assert r_fc.status_code == 200
        fc_items = r_fc.json()["items"]
        assert fc_items
        for k in ("province", "market_name", "commodity_std", "forecast_t1", "ci_low_80", "ci_high_80", "interval_status"):
            assert k in fc_items[0]

        r_cp = c.get("/api/v1/credit-passport", params={"collateral_value_xaf": 1_000_000})
        assert r_cp.status_code == 200
        cp = r_cp.json()
        assert "index_name" in cp and "disclaimer" in cp and cp["items"]
        for k in ("province", "commodity_std", "credit_score", "grade", "ltv_ratio", "recommended_max_loan_xaf"):
            assert k in cp["items"][0]

        r_chat = c.post("/api/v1/chat", json={"message": "Bonjour"})
        assert r_chat.status_code == 200
        ch = r_chat.json()
        for k in ("reply", "intent", "entities", "sources", "follow_ups"):
            assert k in ch
    finally:
        server.STATE.clear()


def test_health_returns_503_when_engine_is_not_loaded():
    previous_state = dict(server.STATE)
    server.STATE.clear()
    try:
        response = TestClient(server.app).get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
    finally:
        server.STATE.clear()
        server.STATE.update(previous_state)


def test_frontend_contains_no_server_side_secrets():
    secret_patterns = [
        re.compile(r"gsk_[A-Za-z0-9]{12,}"),
        re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}"),
        re.compile(r"SUPABASE_SERVICE_ROLE_KEY\s*[:=]\s*['\"][^'\"]+['\"]"),
        re.compile(r"ADMIN_TOKEN\s*[:=]\s*['\"][^'\"]+['\"]"),
        re.compile(r"PREMIUM_API_KEYS\s*[:=]\s*['\"][^'\"]+['\"]"),
    ]
    for folder in (ROOT / "frontend_flutter" / "lib", ROOT / "frontend_flutter" / "web"):
        for path in folder.rglob("*"):
            if path.suffix in (".dart", ".html", ".json", ".js"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pat in secret_patterns:
                    assert not pat.search(text), f"Secret pattern found in {path}"


def test_configuration_json_files_are_valid():
    for rel in (
        "frontend_flutter/firebase.json",
        "frontend_flutter/web/manifest.json",
        "docs/manifest.json",
    ):
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert data

