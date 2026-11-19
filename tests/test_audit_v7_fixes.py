"""Correctifs de l'audit v6 : usurpation par X-User-Id, suspension après redémarrage, webhook Stripe, paiements."""
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from api import server
from src.admin import AdminService
from src.auth import AuthStore
from src.monetization import StripeWebhookAdapter, SubscriptionStore

SECRET = "super-secret-auth-key-for-tests-123456"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    monkeypatch.setenv("REQUIRE_SIGNED_USER_AUTH", "0")
    auth = AuthStore(db_path=str(tmp_path / "auth.db"))
    admin = AdminService(db_path=str(tmp_path / "admin.db"))
    monkeypatch.setattr(server, "_AUTH_STORE", auth)
    monkeypatch.setattr(server, "_ADMIN_SERVICE", admin)
    return auth, admin


def _register(auth, email="a@example.td"):
    return server.auth_register_endpoint(
        server.AuthRegisterRequest(email=email, password="Password123!"), auth_store=auth
    )


def test_account_id_in_x_user_id_does_not_grant_account_space(stores):
    auth, _ = stores
    reg = _register(auth)
    uid = reg["user"]["user_id"]
    assert server._resolve_owner_id_optional(x_user_id=uid) == f"anon:{uid}"
    # Avec le jeton Bearer : espace du compte
    assert server._resolve_owner_id_optional(authorization=f"Bearer {reg['token']}") == f"user:{uid}"
    # Un identifiant anonyme non enregistré garde son espace
    anon = "a" * 40
    assert server._resolve_owner_id_optional(x_user_id=anon) == f"user:{anon}"


def test_deleted_account_token_is_rejected(stores):
    auth, _ = stores
    reg = _register(auth)
    auth.delete_account(reg["user"]["user_id"], password="Password123!")
    with pytest.raises(HTTPException) as exc:
        server._resolve_owner_id_optional(authorization=f"Bearer {reg['token']}")
    assert exc.value.status_code == 401


def test_suspension_enforced_even_if_admin_service_not_yet_instantiated(stores, monkeypatch, tmp_path):
    auth, admin = stores
    target = "user:" + "x" * 40
    admin.set_user_status(actor="a", actor_role="super_admin", target_user_id=target, status="suspended")
    monkeypatch.setattr(server, "_ADMIN_SERVICE", None)  # état après redémarrage du process
    monkeypatch.setattr(server, "AdminService", lambda: AdminService(db_path=str(tmp_path / "admin.db")))
    with pytest.raises(HTTPException) as exc:
        server._resolve_owner_id_optional(x_user_id="x" * 40)
    assert exc.value.status_code == 403


def _stripe_event(secret, event_type, uid, event_id=None, **obj):
    body = json.dumps({
        "id": event_id or f"evt_{event_type}",
        "type": event_type,
        "data": {"object": {"metadata": {"user_id": uid}, **obj}},
    }).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def test_stripe_non_payment_events_do_not_activate_premium(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "s.db"))
    secret = "whsec_test_secret_123456"
    for et in ("invoice.payment_failed", "checkout.session.expired", "customer.created"):
        body, sig = _stripe_event(secret, et, "user:" + "u" * 40)
        out = store.process_webhook_idempotent(StripeWebhookAdapter(), body, sig, secret)
        assert out["status"] == "ignored"
    assert store.get_subscription("user:" + "u" * 40)["effective_plan_id"] == "free"


def test_stripe_paid_checkout_activates_and_unpaid_does_not(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "s.db"))
    secret = "whsec_test_secret_123456"
    uid = "user:" + "p" * 40
    body, sig = _stripe_event(secret, "checkout.session.completed", uid, event_id="evt_unpaid", payment_status="unpaid")
    assert store.process_webhook_idempotent(StripeWebhookAdapter(), body, sig, secret)["status"] == "ignored"
    body, sig = _stripe_event(secret, "checkout.session.completed", uid, event_id="evt_paid", payment_status="paid")
    assert store.process_webhook_idempotent(StripeWebhookAdapter(), body, sig, secret)["status"] == "processed"
    assert store.get_subscription(uid)["effective_plan_id"] == "premium"
    # rejeu : doublon ignoré
    assert store.process_webhook_idempotent(StripeWebhookAdapter(), body, sig, secret)["status"] == "duplicate_ignored"
    # résiliation
    body, sig = _stripe_event(secret, "customer.subscription.deleted", uid, event_id="evt_del")
    store.process_webhook_idempotent(StripeWebhookAdapter(), body, sig, secret)
    assert store.get_subscription(uid)["effective_plan_id"] == "free"


def test_payment_request_duplicate_reference_and_pending_cap(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "s.db"))
    kw = dict(provider="airtel_money", phone_or_ref="+23566000000")
    store.create_payment_request("user:" + "a" * 40, transaction_ref="TX-0001", **kw)
    with pytest.raises(ValueError):
        store.create_payment_request("user:" + "b" * 40, transaction_ref="TX-0001", **kw)
    for i in range(2, 6):
        store.create_payment_request("user:" + "a" * 40, transaction_ref=f"TX-000{i}", **kw)
    with pytest.raises(ValueError):
        store.create_payment_request("user:" + "a" * 40, transaction_ref="TX-9999", **kw)


def test_register_unique_violation_maps_to_conflict(stores):
    auth, _ = stores
    _register(auth, "dup@example.td")
    with pytest.raises(HTTPException) as exc:
        _register(auth, "DUP@example.td")
    assert exc.value.status_code == 409


def test_password_change_invalidates_old_tokens_and_returns_fresh_session(stores):
    auth, _ = stores
    reg = _register(auth, "pw@example.td")
    old = f"Bearer {reg['token']}"
    assert server._resolve_owner_id_optional(authorization=old)
    time.sleep(1.1)  # iat a une granularité d'une seconde
    out = server.auth_change_password_endpoint(
        server.AuthChangePasswordRequest(current_password="Password123!", new_password="NewPassword456!"),
        authorization=old,
        auth_store=auth,
    )
    with pytest.raises(HTTPException) as exc:
        server._resolve_owner_id_optional(authorization=old)
    assert exc.value.status_code == 401
    new = f"Bearer {out['session']['token']}"
    assert server._resolve_owner_id_optional(authorization=new) == f"user:{reg['user']['user_id']}"


def test_refresh_is_bounded_by_original_login_date(stores, monkeypatch):
    from src.security import issue_signed_user_token
    auth, _ = stores
    reg = _register(auth, "rf@example.td")
    uid = reg["user"]["user_id"]
    # Session ouverte il y a 31 jours puis renouvelée : le renouvellement doit être refusé.
    ancient = int(time.time()) - 31 * 24 * 3600
    tok = issue_signed_user_token(uid, SECRET, ttl_seconds=3600, original_iat=ancient)
    with pytest.raises(HTTPException) as exc:
        server.auth_refresh_endpoint(authorization=f"Bearer {tok}", auth_store=auth)
    assert exc.value.status_code == 401
    # Renouvellement normal : conserve la date d'origine
    fresh = server.auth_refresh_endpoint(authorization=f"Bearer {reg['token']}", auth_store=auth)
    from src.security import token_claims
    assert token_claims(fresh["token"])["oiat"] == token_claims(reg["token"])["oiat"]


def test_delete_account_purges_subscription_payments_and_tickets(stores, tmp_path, monkeypatch):
    from src.conversations import ConversationStore
    from src.projects import ProjectStore
    from src.support_feedback import SupportFeedbackStore
    from src.user_documents import UserDocumentStore
    auth, _ = stores
    reg = _register(auth, "del@example.td")
    uid = reg["user"]["user_id"]
    owner = f"user:{uid}"
    subs = SubscriptionStore(db_path=str(tmp_path / "s.db"))
    sup = SupportFeedbackStore(db_path=str(tmp_path / "sup.db"))
    subs.create_payment_request(owner, provider="airtel_money", phone_or_ref="+23566000000", transaction_ref="TX-DEL-1")
    sup.create_ticket(owner, category="technical_bug", subject="Bug", description="Description du bug")
    monkeypatch.setattr(server, "_SUPPORT_STORE", sup)
    server.auth_delete_account_endpoint(
        server.AuthDeleteAccountRequest(password="Password123!"),
        authorization=f"Bearer {reg['token']}",
        auth_store=auth,
        conv_store=ConversationStore(db_path=str(tmp_path / "c.db")),
        project_store=ProjectStore(db_path=str(tmp_path / "p.db"), artifacts_dir=str(tmp_path / "art")),
        doc_store=UserDocumentStore(db_path=str(tmp_path / "d.db")),
        sub_store=subs,
    )
    assert subs.list_payment_requests(user_id=owner) == []
    assert sup.list_user_tickets(owner) == []
