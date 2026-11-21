"""Tests des clés d'activation PRO uniques (usage unique, strictement liées au compte connecté)."""
from datetime import datetime

import pytest
from fastapi import HTTPException

from api import server
from src.auth import AuthStore
from src.monetization import SubscriptionStore


def test_pro_activation_key_single_use_and_strict_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "unit-test-secret-pro-keys-123456")
    auth_store = AuthStore(str(tmp_path / "auth.db"))
    sub_store = SubscriptionStore(str(tmp_path / "billing.db"))

    # 1. Création de deux utilisateurs distincts
    u_a = auth_store.register("alice@tchad.td", "Password123!", "Alice")
    u_b = auth_store.register("bob@tchad.td", "Password123!", "Bob")
    tok_a = auth_store.issue_session(u_a)["token"]
    tok_b = auth_store.issue_session(u_b)["token"]

    # 2. Génération d'une clé PRO unique (30 jours)
    created = sub_store.create_activation_key(actor="kader", duration_days=30, note="Client N'Djamena")
    plain_key = created["activation_key"]
    assert plain_key.startswith("FDPRO-")
    assert created["status"] == "unused"

    # Le listing ne doit jamais exposer le hash ni la clé en clair
    listed = sub_store.list_activation_keys()
    assert len(listed) == 1
    assert "key_hash" not in listed[0]
    assert "activation_key" not in listed[0]
    assert listed[0]["status"] == "unused"

    # 3. Un invité sans jeton Bearer ne peut PAS activer une clé
    with pytest.raises(HTTPException) as exc_guest:
        server.redeem_pro_key_endpoint(
            server.RedeemProKeyRequest(activation_key=plain_key),
            authorization=None,
            auth_store=auth_store,
            sub_store=sub_store,
        )
    assert exc_guest.value.status_code == 401

    # 4. Alice (connectée) active la clé -> son compte devient PRO
    res = server.redeem_pro_key_endpoint(
        server.RedeemProKeyRequest(activation_key=plain_key.lower()),
        authorization=f"Bearer {tok_a}",
        auth_store=auth_store,
        sub_store=sub_store,
    )
    assert res["redeemed"] is True
    assert res["is_pro"] is True
    assert res["subscription"]["effective_plan_id"] == "premium"

    # 5. Bob tente de réutiliser la même clé -> 409 Conflict, Bob reste gratuit
    with pytest.raises(HTTPException) as exc_dup:
        server.redeem_pro_key_endpoint(
            server.RedeemProKeyRequest(activation_key=plain_key),
            authorization=f"Bearer {tok_b}",
            auth_store=auth_store,
            sub_store=sub_store,
        )
    assert exc_dup.value.status_code == 409
    assert sub_store.get_subscription(f"user:{u_b['user_id']}")["effective_plan_id"] == "free"

    # 6. Extension cumulée : une 2e clé ajoute 60 jours à l'échéance existante d'Alice
    end_before = datetime.fromisoformat(res["subscription"]["current_period_end"])
    created2 = sub_store.create_activation_key(actor="kader", duration_days=60)
    res2 = server.redeem_pro_key_endpoint(
        server.RedeemProKeyRequest(activation_key=created2["activation_key"]),
        authorization=f"Bearer {tok_a}",
        auth_store=auth_store,
        sub_store=sub_store,
    )
    end_after = datetime.fromisoformat(res2["subscription"]["current_period_end"])
    assert (end_after - end_before).days >= 59


def test_pro_activation_key_revocation(tmp_path):
    sub_store = SubscriptionStore(str(tmp_path / "billing.db"))
    created = sub_store.create_activation_key(actor="kader", duration_days=30)
    revoked = sub_store.revoke_activation_key(created["key_id"], actor="kader")
    assert revoked["status"] == "revoked"

    with pytest.raises(ValueError):
        sub_store.redeem_activation_key("user:u1234567890abcdef1234567890abcdef", created["activation_key"])
