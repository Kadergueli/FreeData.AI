"""Chantier 1 tests: User account registration, login, Bearer sessions, revocation, and automatic PRO entitlement."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server
from src.auth import AuthStore
from src.monetization import SubscriptionStore


def test_register_login_me_and_logout_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "super-secret-auth-key-for-tests-123456")
    monkeypatch.setenv("REQUIRE_SIGNED_USER_AUTH", "1")
    auth_store = AuthStore(db_path=str(tmp_path / "auth.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr(server, "_AUTH_STORE", auth_store)

    # Register
    reg = server.auth_register_endpoint(
        server.AuthRegisterRequest(email="Amina@Example.td", password="StrongPassword123!", display_name="Amina"),
        auth_store=auth_store,
    )
    assert reg["token"]
    assert reg["user"]["email"] == "amina@example.td"
    assert reg["user"]["display_name"] == "Amina"
    assert len(reg["user"]["user_id"]) >= 32

    # Duplicate email -> 409
    with pytest.raises(HTTPException) as exc_dup:
        server.auth_register_endpoint(
            server.AuthRegisterRequest(email="amina@example.td", password="AnotherPassword123!"),
            auth_store=auth_store,
        )
    assert exc_dup.value.status_code == 409

    # Wrong password -> 401
    with pytest.raises(HTTPException) as exc_bad:
        server.auth_login_endpoint(
            server.AuthLoginRequest(email="amina@example.td", password="wrong"),
            auth_store=auth_store,
        )
    assert exc_bad.value.status_code == 401

    # Valid login
    login = server.auth_login_endpoint(
        server.AuthLoginRequest(email="amina@example.td", password="StrongPassword123!"),
        auth_store=auth_store,
    )
    tok = login["token"]
    bearer = f"Bearer {tok}"

    # Works with REQUIRE_SIGNED_USER_AUTH=1
    owner_id = server._require_project_owner(x_user_id=None, x_premium_key=None, authorization=bearer)
    assert owner_id == f"user:{reg['user']['user_id']}"

    # /auth/me reflects free plan initially
    me = server.auth_me_endpoint(authorization=bearer, x_premium_key=None, auth_store=auth_store, sub_store=sub_store)
    assert me["user"]["email"] == "amina@example.td"
    assert me["is_pro"] is False

    # Logout revokes session
    out = server.auth_logout_endpoint(authorization=bearer, auth_store=auth_store)
    assert out["logged_out"] is True

    with pytest.raises(HTTPException) as exc_revoked:
        server.auth_me_endpoint(authorization=bearer, x_premium_key=None, auth_store=auth_store, sub_store=sub_store)
    assert exc_revoked.value.status_code == 401

    with pytest.raises(HTTPException) as exc_owner_revoked:
        server._require_project_owner(x_user_id=None, x_premium_key=None, authorization=bearer)
    assert exc_owner_revoked.value.status_code == 401


def test_active_pro_subscription_grants_pro_access_without_premium_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "super-secret-auth-key-for-tests-123456")
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys=""))
    auth_store = AuthStore(db_path=str(tmp_path / "auth.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr(server, "_AUTH_STORE", auth_store)

    reg = server.auth_register_endpoint(
        server.AuthRegisterRequest(email="pro@example.td", password="StrongPassword123!"),
        auth_store=auth_store,
    )
    owner_id = f"user:{reg['user']['user_id']}"
    bearer = f"Bearer {reg['token']}"

    # Initially free -> blocked on PRO route
    assert server._has_pro_access(owner_id, None, sub_store) is False

    # Activate PRO subscription in store (e.g. via Mobile Money approval or Stripe webhook)
    sub_store.admin_update_subscription(
        actor="super_admin",
        target_user_id=owner_id,
        plan_id="premium",
        status="active",
        period_days=30,
        provider="airtel_money",
        reason="Paiement validé",
    )

    # Now PRO access works WITHOUT X-Premium-Key!
    assert server._has_pro_access(owner_id, None, sub_store) is True
    server._require_pro_access(owner_id, None, sub_store, "Test PRO")

    me = server.auth_me_endpoint(authorization=bearer, x_premium_key=None, auth_store=auth_store, sub_store=sub_store)
    assert me["is_pro"] is True
    assert me["subscription"]["effective_plan_id"] == "premium"

    billing = server.get_my_billing_endpoint(owner_id=owner_id, x_premium_key=None, sub_store=sub_store)
    assert billing["is_pro"] is True
    assert billing["quotas"]["monthly_pdf"]["limit"] == 50

