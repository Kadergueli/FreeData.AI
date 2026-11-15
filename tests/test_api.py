import dataclasses
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import server


@pytest.fixture()
def client(gold_tables):
    fc_gold, cp_gold = gold_tables
    server.STATE.clear()
    server._RATE_LIMIT_BUCKET.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold))
    yield TestClient(server.app)  # sans "with" : le lifespan (accès Supabase) n'est pas lancé
    server.STATE.clear()
    server._RATE_LIMIT_BUCKET.clear()


def test_spike_is_flagged_with_stored_model_deviation(client):
    """Régression : en mode production, un pic de +30 % passait sous le seuil de 15 %."""
    body = client.get("/api/v1/alerts", params={"threshold_pct": 15}).json()
    assert body["alerts_source"] == "stored"
    hits = [(i["province"], i["commodity_std"]) for i in body["items"]]
    assert ("Salamat", "Millet") in hits
    spike = next(i for i in body["items"] if i["province"] == "Salamat")
    assert spike["deviation_pct"] > 30


def test_metadata_exposes_market_catalog_dimensions(client):
    metadata = client.get("/api/v1/metadata").json()
    assert metadata["active_domain"]["slug"] == "markets_and_prices"
    for key in ["products", "cereals", "markets", "provinces", "sources", "periods_covered", "last_updated"]:
        assert key in metadata
    assert metadata["products"]
    assert metadata["provinces"]
    assert metadata["markets"]
    assert metadata["sources"]
    assert metadata["periods_covered"]["start"]
    assert metadata["periods_covered"]["end"]


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


class TestChatRateLimit:
    def test_blocks_21st_request_within_one_minute_and_resets_after_window(self, client, monkeypatch):
        fake_now = [1_700_000_000.0]
        monkeypatch.setattr(server.time, "time", lambda: fake_now[0])

        for idx in range(20):
            resp = client.post("/api/v1/chat", json={"message": f"Prix du mil à N'Djamena ({idx})"})
            assert resp.status_code == 200

        blocked = client.post(
            "/api/v1/chat",
            params={"max_per_minute": 100},
            json={"message": "Prix du mil à N'Djamena (21)"},
        )
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "Trop de requêtes. Réessayez dans une minute."

        # Après 60 secondes, la fenêtre glissante repart à zéro.
        fake_now[0] += 61.0
        recovered = client.post("/api/v1/chat", json={"message": "Prix du mil à N'Djamena"})
        assert recovered.status_code == 200

    def test_rate_limit_isolated_per_client_ip(self, monkeypatch):
        server._RATE_LIMIT_BUCKET.clear()
        fake_now = [1_700_000_000.0]
        monkeypatch.setattr(server.time, "time", lambda: fake_now[0])

        req_ip_a = SimpleNamespace(client=SimpleNamespace(host="198.51.100.10"))
        req_ip_b = SimpleNamespace(client=SimpleNamespace(host="198.51.100.20"))
        req_unknown = SimpleNamespace(client=None)

        for _ in range(20):
            server.enforce_rate_limit(req_ip_a)

        with pytest.raises(server.HTTPException) as exc_info:
            server.enforce_rate_limit(req_ip_a)
        assert exc_info.value.status_code == 429

        # Une autre IP et le fallback "unknown" ne sont pas affectés.
        server.check_rate_limit(req_ip_b)
        server.check_rate_limit(req_unknown)
        server._RATE_LIMIT_BUCKET.clear()

    def test_chat_accepts_single_char_and_returns_sources_field(self, client):
        resp_short = client.post("/api/v1/chat", json={"message": "?"})
        assert resp_short.status_code == 200
        body = resp_short.json()
        assert body["sources"] == []

        resp_greeting = client.post("/api/v1/chat", json={"message": "Salut"})
        assert resp_greeting.status_code == 200
        assert resp_greeting.json()["intent"] == "greeting"
        assert resp_greeting.json()["sources"] == []

        resp_empty = client.post("/api/v1/chat", json={"message": ""})
        assert resp_empty.status_code == 422

    def test_chat_accepts_optional_history_for_followup(self, client):
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "Et le risque de crédit ?",
                "history": [
                    {"role": "user", "content": "Quel est le prix du mil au Salamat ?"},
                    {"role": "assistant", "content": "Voici l'analyse pour le Mil au Salamat."},
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "credit_passport"
        assert body["entities"]["province"] == "Salamat"
        assert body["entities"]["commodity"] == "Millet"

    def test_chat_defaults_to_free_tier_and_accepts_premium(self, client, monkeypatch):
        from src import ai_agent

        monkeypatch.setattr(
            ai_agent,
            "settings",
            dataclasses.replace(
                ai_agent.settings,
                llm_api_key="gsk_should_not_be_called_by_default",
                embed_api_key="",
                llm_routing=False,  # ce test compte les appels de synthèse ; le routage a ses propres tests
            ),
        )

        llm_urls = []

        def fake_post(url, *args, **kwargs):
            llm_urls.append(url)
            raise AssertionError("Le tier='free' par défaut ne doit pas déclencher d'appel LLM.")

        monkeypatch.setattr(ai_agent.requests, "post", fake_post)
        resp = client.post("/api/v1/chat", json={"message": "Quel est le prix du mil au Salamat ?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "forecast"
        assert body["sources"] == []
        assert llm_urls == []

        # Valeur tier='premium' acceptée et transmise au module d'analyse avancée
        def fake_premium_post(url, *args, **kwargs):
            llm_urls.append(url)

            class Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"choices": [{"message": {"content": "Synthèse premium Salamat : Mil vérifié."}}]}

            return Resp()

        monkeypatch.setattr(ai_agent.requests, "post", fake_premium_post)
        prem = client.post(
            "/api/v1/chat",
            json={"message": "Quel est le prix du mil au Salamat ?", "tier": "premium"},
        )
        assert prem.status_code == 200
        assert len(llm_urls) == 1
        assert "Synthèse premium Salamat" in prem.json()["reply"]

        # Valeur de tier invalide rejetée par Pydantic (422)
        bad = client.post("/api/v1/chat", json={"message": "Prix du mil", "tier": "enterprise"})
        assert bad.status_code == 422

        # La réponse expose le champ optionnel `chart` sans erreur de schéma
        assert "chart" in resp.json()




class TestChatPayloadRobustness:
    """Aucune entrée client, même absurde, ne doit produire une erreur 500."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"message": "salut"},
            {"message": "salut", "history": []},
            {"message": "salut", "tier": "premium"},
            {"message": "x" * 1000},
            {"message": "  "},
            {"message": "😀🌾"},
            {"message": "السلام عليكم"},
            {"message": "prix du mil", "history": [{"role": "user", "content": "x" * 50000}]},
            {"message": "prix du mil", "history": [{"role": "bot", "content": "?"}, {"nimporte": "quoi"}, {}]},
            {"message": "prix du mil", "history": [{"role": "user", "content": "prix du mil à Lac"}] * 40},
            {"message": "salut", "inconnu": "champ en trop"},
        ],
    )
    def test_accepted_payloads_return_a_reply(self, client, payload):
        resp = client.post("/api/v1/chat", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reply"].strip() and "Traceback" not in body["reply"]

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"message": ""},
            {"message": "x" * 1001},
            {"message": 123},
            {"message": None},
            {"message": "salut", "tier": "gold"},
            {"message": "salut", "history": "pas une liste"},
            {"message": "salut", "history": [{"role": "user", "content": "a"}] * 41},
            [],
            "texte brut",
        ],
    )
    def test_invalid_payloads_are_rejected_with_422_not_500(self, client, payload):
        assert client.post("/api/v1/chat", json=payload).status_code == 422

    def test_malformed_json_body_is_rejected_cleanly(self, client):
        resp = client.post("/api/v1/chat", content="{pas du json", headers={"Content-Type": "application/json"})
        assert resp.status_code in (400, 422)

    def test_wrong_content_type_is_rejected_cleanly(self, client):
        resp = client.post("/api/v1/chat", content="message=salut", headers={"Content-Type": "text/plain"})
        assert resp.status_code in (415, 422)

    def test_chat_does_not_expose_secrets_or_internal_paths_on_error(self, client, monkeypatch):
        from src import ai_agent

        def boom(*a, **k):
            raise RuntimeError("clé gsk_SECRET at /home/app/src/ai_agent.py")

        monkeypatch.setattr(ai_agent.FreeDataAIAgent, "answer_with_metadata", boom)
        resp = client.post("/api/v1/chat", json={"message": "prix du mil"})
        assert "gsk_SECRET" not in resp.text and "/home/app" not in resp.text
