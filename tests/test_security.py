"""Durcissement de l'API : IP client, limites, niveau premium, saturation, configuration."""
import dataclasses
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(gold_tables):
    fc_gold, cp_gold = gold_tables
    server.STATE.clear()
    server._RATE_LIMIT_BUCKET.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold))
    yield TestClient(server.app)
    server.STATE.clear()
    server._RATE_LIMIT_BUCKET.clear()


def _req(xff=None, peer="10.0.0.9"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def _with(monkeypatch, **changes):
    monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, **changes))


# --- IP du client -------------------------------------------------------------------------------------------------

def test_client_ip_falls_back_safely_when_hops_not_configured(monkeypatch):
    _with(monkeypatch, trusted_proxy_hops=None, trusted_proxy_cidrs="")
    assert server._client_ip(_req("1.1.1.1, 2.2.2.2", peer="10.0.0.9")) == "10.0.0.9"
    assert server._client_ip(_req(None, peer="10.0.0.9")) == "10.0.0.9"


def test_client_ip_ignores_values_the_client_can_forge(monkeypatch):
    _with(monkeypatch, trusted_proxy_hops=1, trusted_proxy_cidrs="10.0.0.0/8")
    # le client a ajouté « 6.6.6.6 » à gauche ; notre proxy a ajouté l'IP réelle à droite
    assert server._client_ip(_req("6.6.6.6, 203.0.113.7", peer="10.0.0.9")) == "203.0.113.7"
    _with(monkeypatch, trusted_proxy_hops=2, trusted_proxy_cidrs="10.0.0.0/8")
    assert server._client_ip(_req("6.6.6.6, 203.0.113.7, 172.16.0.1", peer="10.0.0.9")) == "203.0.113.7"
    assert server._client_ip(_req("203.0.113.7", peer="10.0.0.9")) == "203.0.113.7"
    _with(monkeypatch, trusted_proxy_hops=0)
    assert server._client_ip(_req("6.6.6.6", peer="10.0.0.9")) == "10.0.0.9"


def test_untrusted_peer_and_invalid_xff_fall_back_to_peer(monkeypatch):
    _with(monkeypatch, trusted_proxy_hops=1, trusted_proxy_cidrs="10.0.0.0/8")
    # Peer hors CIDR de confiance -> X-Forwarded-For ignoré
    assert server._client_ip(_req("203.0.113.7", peer="198.51.100.4")) == "198.51.100.4"
    # En-tête X-Forwarded-For invalide -> repli sur peer
    assert server._client_ip(_req("not-an-ip, 999.999.999.999", peer="10.0.0.9")) == "10.0.0.9"


def test_trusted_proxy_hops_validation():
    from src.config import _parse_trusted_proxy_hops
    assert _parse_trusted_proxy_hops("") is None
    assert _parse_trusted_proxy_hops("-2") is None
    assert _parse_trusted_proxy_hops("abc") is None
    assert _parse_trusted_proxy_hops("1") == 1


def test_spoofing_x_forwarded_for_cannot_evade_the_chat_limit(client, monkeypatch):
    _with(monkeypatch, trusted_proxy_hops=1, trusted_proxy_cidrs="")
    statuses = []
    for i in range(22):
        r = client.post("/api/v1/chat", json={"message": "bonjour"},
                        headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"})
        statuses.append(r.status_code)
    assert statuses[:20] == [200] * 20 and statuses[20:] == [429, 429]


def test_missing_proxy_config_still_enforces_rate_limit(client, monkeypatch):
    """Sans TRUSTED_PROXY_HOPS, le repli sur peer empêche tout contournement par X-Forwarded-For."""
    _with(monkeypatch, trusted_proxy_hops=None, trusted_proxy_cidrs="")
    statuses = [
        client.post("/api/v1/chat", json={"message": "bonjour"}, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code
        for i in range(22)
    ]
    assert statuses[:20] == [200] * 20 and statuses[20:] == [429, 429]


def test_shared_redis_backend_and_failure_fallback(client, monkeypatch):
    from unittest.mock import MagicMock

    _with(
        monkeypatch,
        trusted_proxy_hops=None,
        rate_limit_redis_rest_url="https://redis.example.com",
        rate_limit_redis_rest_token="tok",
    )
    # 1. Réponse Redis > limite -> 429 immédiat
    ok_resp = MagicMock()
    ok_resp.raise_for_status = lambda: None
    ok_resp.json.return_value = [{"result": 1}, {"result": 1}]
    over_resp = MagicMock()
    over_resp.raise_for_status = lambda: None
    over_resp.json.return_value = [{"result": 25}, {"result": 1}]

    calls = iter([ok_resp, over_resp])
    monkeypatch.setattr(server.requests, "post", lambda *a, **kw: next(calls))
    assert client.post("/api/v1/chat", json={"message": "bonjour"}).status_code == 429

    # 2. Panne Redis -> repli silencieux sur le compteur mémoire (ne contourne pas la limite)
    server._RATE_LIMIT_BUCKET.clear()
    monkeypatch.setattr(server.requests, "post", MagicMock(side_effect=RuntimeError("redis down")))
    statuses = [client.post("/api/v1/chat", json={"message": "bonjour"}).status_code for _ in range(22)]
    assert statuses[:20] == [200] * 20 and statuses[20:] == [429, 429]


def test_global_cap_does_not_depend_on_the_ip(client, monkeypatch):
    _with(monkeypatch, global_rate_limit_per_min=3, trusted_proxy_hops=None)
    codes = [client.get("/api/v1/metadata", headers={"X-Forwarded-For": f"8.8.8.{i}"}).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_data_endpoints_are_rate_limited(client):
    server._RATE_LIMIT_BUCKET["data:testclient"] = [time.time()] * 120
    for path in ("/api/v1/forecasts", "/api/v1/alerts", "/api/v1/anomalies", "/api/v1/credit-passport", "/api/v1/metadata"):
        r = client.get(path)
        assert r.status_code == 429 and r.headers.get("retry-after") == "30", path


def test_refresh_is_rate_limited_against_token_guessing(client, monkeypatch):
    _with(monkeypatch, admin_token="s3cret-" + "x" * 20, trusted_proxy_hops=None)
    codes = [client.post("/api/v1/refresh", headers={"X-Admin-Token": f"guess{i}"}).status_code for i in range(12)]
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


# --- Niveau premium ----------------------------------------------------------------------------------------------

def test_admin_token_is_never_a_premium_key(monkeypatch):
    _with(monkeypatch, premium_api_keys="k" * 20, admin_token="a" * 20)
    assert server._premium_key_ok("k" * 20) and not server._premium_key_ok("a" * 20)


def _settings_in_subprocess(env_extra: dict, code: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PREMIUM", "FREEDATA_PREMIUM", "X_PREMIUM"))}
    for name in ("PREMIUM_API_KEYS", "PREMIUM_API_KEY", "FREEDATA_PREMIUM_KEY", "FREEDATA_PREMIUM_KEYS", "PREMIUM_KEY",
                 "PREMIUM_KEYS", "X_PREMIUM_KEY", "FREEDATA_API_KEY", "ADMIN_TOKEN", "TRUSTED_PROXY_HOPS", "ALLOW_LOCALHOST_CORS"):
        env[name] = ""          # une valeur vide empêche python-dotenv d'importer un .env local
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); {code}"],
                         capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.strip()


def test_premium_keys_never_fall_back_to_admin_token_or_generic_keys():
    out = _settings_in_subprocess({"ADMIN_TOKEN": "a" * 24, "FREEDATA_API_KEY": "g" * 24},
                                  "from src.config import settings; print(settings.premium_keys)")
    assert out == "()"
    out = _settings_in_subprocess({"ADMIN_TOKEN": "a" * 24, "PREMIUM_API_KEYS": "k" * 20 + ";" + "m" * 20},
                                  "from src.config import settings; print(len(settings.premium_keys))")
    assert out == "2"


def test_trusted_proxy_hops_and_localhost_cors_settings():
    out = _settings_in_subprocess({"TRUSTED_PROXY_HOPS": "2", "ALLOW_LOCALHOST_CORS": "0"},
                                  "from api import server; from src.config import settings; "
                                  "print(settings.trusted_proxy_hops, server.app.user_middleware[0].kwargs['allow_origin_regex'])")
    assert out == "2 None"
    out = _settings_in_subprocess({}, "from api import server; from src.config import settings; "
                                      "print(settings.trusted_proxy_hops, bool(server.app.user_middleware[0].kwargs['allow_origin_regex']))")
    assert out == "None True"


# --- Saturation du chat -------------------------------------------------------------------------------------------

def test_chat_answers_503_when_all_slots_are_busy(client, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()                                         # le seul créneau est pris par un appel lent
    monkeypatch.setattr(server, "_CHAT_SLOTS", slots)
    monkeypatch.setattr(server, "_CHAT_WAIT_S", 0.05)
    r = client.post("/api/v1/chat", json={"message": "bonjour"})
    assert r.status_code == 503 and r.headers.get("retry-after") == "5"
    slots.release()
    assert client.post("/api/v1/chat", json={"message": "bonjour"}).status_code == 200


def test_chat_slot_is_released_after_an_error(client, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(server, "_CHAT_SLOTS", slots)
    agent = server.STATE["agent"]
    monkeypatch.setattr(agent, "answer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        client.post("/api/v1/chat", json={"message": "bonjour"})
    assert slots.acquire(blocking=False)                    # le créneau a bien été rendu


# --- Diagnostic IP et bornes d'entrée ------------------------------------------------------------------------------

def test_client_ip_diagnostic_is_admin_only(client, monkeypatch):
    _with(monkeypatch, admin_token="", trusted_proxy_hops=None)
    assert client.get("/api/v1/diag/client-ip").status_code == 503
    _with(monkeypatch, admin_token="t" * 24, trusted_proxy_hops=1)
    assert client.get("/api/v1/diag/client-ip").status_code == 403
    r = client.get("/api/v1/diag/client-ip", headers={"X-Admin-Token": "t" * 24, "X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    body = r.json()
    assert r.status_code == 200 and body["client_ip_used"] == "203.0.113.7" and body["trusted_proxy_hops"] == 1


def test_loan_amount_has_an_upper_bound(client):
    assert client.get("/api/v1/credit-passport", params={"loan_amount": 10 ** 30}).status_code == 422
    assert client.get("/api/v1/credit-passport", params={"loan_amount": 5_000_000}).status_code == 200


# --- Scripts Gold : purge des anciennes lignes --------------------------------------------------------------------

@pytest.mark.parametrize("module_name", ["scripts.update_anomalies", "scripts.update_seasonality"])
def test_gold_scripts_purge_old_rows_only_after_a_successful_push(monkeypatch, module_name):
    import importlib
    mod = importlib.import_module(module_name)
    calls = []
    monkeypatch.setattr(mod, "settings", dataclasses.replace(mod.settings, supabase_url="https://x.supabase.co",
                                                             supabase_service_key="s" * 30, supabase_key="a" * 30))

    class Ok:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "post", lambda url, **kw: calls.append(("post", url)) or Ok())
    monkeypatch.setattr(mod.requests, "delete", lambda url, **kw: calls.append(("delete", kw["params"])) or Ok())

    mod.push([{"generated_at": "2026-11-17T10:00:00+00:00"}])
    mod.purge_stale("2026-11-17T10:00:00+00:00")
    assert [c[0] for c in calls] == ["post", "delete"]
    assert calls[1][1] == {"generated_at": "lt.2026-11-17T10:00:00+00:00"}   # seules les lignes plus anciennes


def test_anomalies_script_does_not_purge_when_the_run_is_empty(monkeypatch, tmp_path):
    import pandas as pd
    from scripts import update_anomalies as mod
    deleted = []
    monkeypatch.setattr(mod, "settings", dataclasses.replace(mod.settings, supabase_url="https://x.supabase.co",
                                                             supabase_service_key="s" * 30, supabase_key="a" * 30))
    monkeypatch.setattr(mod, "load_clean_markets", lambda csv=None: pd.DataFrame())
    monkeypatch.setattr(mod, "detect_anomalies", lambda kg: pd.DataFrame(columns=mod.FIELDS))
    monkeypatch.setattr(mod, "recent_anomalies", lambda df, months=6: df)
    monkeypatch.setattr(mod, "push", lambda rows: None)
    monkeypatch.setattr(mod, "purge_stale", lambda ts: deleted.append(ts))
    assert mod.main(["--apply"]) == 0 and deleted == []
