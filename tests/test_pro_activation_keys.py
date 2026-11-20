"""Clés d'activation PRO : usage unique, hachées, liées au compte, révocables, anti-force brute."""
import threading
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server
from src.monetization import SubscriptionStore

TOK_SUP = "support-token-" + "s" * 12
TOK_ANA = "analyst-token-" + "a" * 12
TOK_SUPER = "super-token--" + "z" * 12


@pytest.fixture
def store(tmp_path):
    return SubscriptionStore(db_path=str(tmp_path / "s.db"))


def test_key_is_single_use_and_hashed(store):
    k = store.create_pro_key(actor="omar", duration_days=30, note="client A")
    assert k["activation_key"].startswith("FDPRO-") and k["status"] == "unused"
    listing = store.list_pro_keys()
    assert "activation_key" not in listing[0] and "key_hash" not in listing[0]
    with store._connect() as conn:
        dump = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM pro_activation_keys").fetchall())
    assert k["activation_key"] not in dump  # seul le hash est stocké

    res = store.redeem_pro_key("user:" + "a" * 32, k["activation_key"].lower().replace("-", " "))
    assert res["is_pro"] is True and res["duration_days"] == 30
    assert store.get_subscription("user:" + "a" * 32)["effective_plan_id"] == "premium"
    with pytest.raises(ValueError):
        store.redeem_pro_key("user:" + "b" * 32, k["activation_key"])
    assert store.list_pro_keys()[0]["status"] == "redeemed"


def test_concurrent_redeem_only_one_wins(store):
    k = store.create_pro_key(actor="omar")
    wins, errs = [], []

    def go(i):
        try:
            wins.append(store.redeem_pro_key(f"user:race{i:028d}", k["activation_key"]))
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(wins) == 1 and len(errs) == 5


def test_revoked_and_expired_keys_rejected(store):
    k = store.create_pro_key(actor="omar")
    store.revoke_pro_key(k["key_id"], actor="omar")
    with pytest.raises(ValueError):
        store.redeem_pro_key("user:" + "c" * 32, k["activation_key"])
    with pytest.raises(ValueError):
        store.revoke_pro_key(k["key_id"], actor="omar")
    k2 = store.create_pro_key(actor="omar")
    with store._connect() as conn:
        conn.execute("UPDATE pro_activation_keys SET expires_at = '2000-01-01T00:00:00+00:00' WHERE key_id = ?", (k2["key_id"],))
    with pytest.raises(ValueError):
        store.redeem_pro_key("user:" + "c" * 32, k2["activation_key"])
    with pytest.raises(KeyError):
        store.revoke_pro_key("KEY-NOPE", actor="omar")


def test_bruteforce_is_throttled(store):
    uid = "user:" + "d" * 32
    for _ in range(5):
        with pytest.raises(ValueError):
            store.redeem_pro_key(uid, "FDPRO-AAAA-BBBB-CCCC-DDDD")
    k = store.create_pro_key(actor="omar")
    with pytest.raises(PermissionError):  # même la bonne clé est refusée pendant le blocage
        store.redeem_pro_key(uid, k["activation_key"])


def test_redeem_extends_existing_subscription(store):
    uid = "user:" + "e" * 32
    store.redeem_pro_key(uid, store.create_pro_key(actor="o", duration_days=30)["activation_key"])
    store.redeem_pro_key(uid, store.create_pro_key(actor="o", duration_days=30)["activation_key"])
    from datetime import datetime, timezone
    end = datetime.fromisoformat(store.get_subscription(uid)["current_period_end"])
    assert 55 <= (end - datetime.now(timezone.utc)).days <= 61


def test_only_premium_and_valid_duration(store):
    with pytest.raises(ValueError):
        store.create_pro_key(actor="o", plan_id="top")
    with pytest.raises(ValueError):
        store.create_pro_key(actor="o", duration_days=0)


def test_purge_user_anonymises_redeemed_key(store):
    uid = "user:" + "f" * 32
    store.redeem_pro_key(uid, store.create_pro_key(actor="o")["activation_key"])
    store.purge_user(uid)
    row = store.list_pro_keys()[0]
    assert row["status"] == "redeemed" and row["redeemed_by_user_id"] == "deleted"


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(
        server, "settings",
        replace(server.settings, admin_token="", admin_tokens=f"amina:read_only_analyst:{TOK_ANA};moussa:support_admin:{TOK_SUP};omar:super_admin:{TOK_SUPER}"),
    )


def test_endpoints_permissions_and_flow(store, creds):
    with pytest.raises(HTTPException) as e:  # analyste lecture seule : refusé
        server.admin_create_pro_key_endpoint(server.ProKeyCreate(), x_admin_token=TOK_ANA, sub_store=store)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        server.admin_list_pro_keys_endpoint(status=None, limit=10, x_admin_token=None, sub_store=store)
    assert e.value.status_code in (403, 503)

    created = server.admin_create_pro_key_endpoint(server.ProKeyCreate(duration_days=15, note="n"), x_admin_token=TOK_SUPER, sub_store=store)
    listed = server.admin_list_pro_keys_endpoint(status="unused", limit=10, x_admin_token=TOK_SUPER, sub_store=store)
    assert listed["count"] == 1 and "activation_key" not in listed["keys"][0]

    uid = "user:" + "9" * 32
    out = server.redeem_pro_key_endpoint(server.ProKeyRedeem(activation_key=created["activation_key"]), owner_id=uid, sub_store=store)
    assert out["is_pro"] is True and out["duration_days"] == 15

    with pytest.raises(HTTPException) as e:  # anonyme : refusé
        server.redeem_pro_key_endpoint(server.ProKeyRedeem(activation_key="FDPRO-AAAA-BBBB-CCCC-DDDD"), owner_id="anon:" + "1" * 32, sub_store=store)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:  # réutilisation
        server.redeem_pro_key_endpoint(server.ProKeyRedeem(activation_key=created["activation_key"]), owner_id="user:" + "8" * 32, sub_store=store)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        server.admin_revoke_pro_key_endpoint(created["key_id"], x_admin_token=TOK_SUPER, sub_store=store)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        server.admin_revoke_pro_key_endpoint("KEY-NOPE", x_admin_token=TOK_SUPER, sub_store=store)
    assert e.value.status_code == 404
