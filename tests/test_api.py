import dataclasses

import pytest
from fastapi.testclient import TestClient

from api import server


@pytest.fixture()
def client(gold_tables):
    fc_gold, cp_gold = gold_tables
    server.STATE.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold))
    yield TestClient(server.app)  # sans "with" : le lifespan (accès Supabase) n'est pas lancé
    server.STATE.clear()


def test_spike_is_flagged_with_stored_model_deviation(client):
    """Régression : en mode production, un pic de +30 % passait sous le seuil de 15 %."""
    body = client.get("/api/v1/alerts", params={"threshold_pct": 15}).json()
    assert body["alerts_source"] == "stored"
    hits = [(i["province"], i["commodity_std"]) for i in body["items"]]
    assert ("Salamat", "Millet") in hits
    spike = next(i for i in body["items"] if i["province"] == "Salamat")
    assert spike["deviation_pct"] > 30


def test_stale_series_not_served(client):
    items = client.get("/api/v1/forecasts", params={"province": "Lac"}).json()["items"]
    assert all(i["commodity_std"] != "Maize (white)" for i in items)
    health = client.get("/api/v1/health").json()
    assert health["stale_series_excluded"] == 1


def test_legacy_gold_without_alert_columns_falls_back_and_says_so(gold_tables):
    fc_gold, cp_gold = gold_tables
    legacy = fc_gold.drop(columns=["predicted_price", "deviation_pct"])
    state = server.build_state_from_gold(legacy, cp_gold)
    assert state["alerts_source"] == "approximated"


def test_credit_passport_carries_disclaimer(client):
    assert "disclaimer" in client.get("/api/v1/credit-passport").json()


def test_503_when_data_not_loaded():
    server.STATE.clear()
    c = TestClient(server.app)
    assert c.get("/api/v1/metadata").status_code == 503
    assert c.get("/api/v1/health").json()["status"] == "degraded"


class TestRefreshProtection:
    def test_disabled_without_admin_token(self, client):
        assert client.post("/api/v1/refresh").status_code == 503

    def test_rejects_missing_or_wrong_token(self, client, monkeypatch):
        monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, admin_token="s3cret"))
        assert client.post("/api/v1/refresh").status_code == 403
        assert client.post("/api/v1/refresh", headers={"X-Admin-Token": "nope"}).status_code == 403

    def test_good_token_reloads(self, client, monkeypatch):
        monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, admin_token="s3cret"))
        calls = []
        monkeypatch.setattr(server, "refresh_engines", lambda: calls.append(1))
        r = client.post("/api/v1/refresh", headers={"X-Admin-Token": "s3cret"})
        assert r.status_code == 200 and calls == [1]

    def test_failed_reload_keeps_previous_state(self, client, monkeypatch):
        monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, admin_token="s3cret"))

        def boom():
            raise RuntimeError("Supabase down")

        monkeypatch.setattr(server, "build_state", boom)
        r = client.post("/api/v1/refresh", headers={"X-Admin-Token": "s3cret"})
        assert r.status_code == 502
        assert "agent" in server.STATE  # l'ancien état est toujours servi
        assert client.get("/api/v1/metadata").status_code == 200
