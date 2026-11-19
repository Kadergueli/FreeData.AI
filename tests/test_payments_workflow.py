"""Chantier 3 tests: Mobile Money payment requests, admin approval/rejection, env pricing, and Stripe HMAC webhooks."""
import hashlib
import hmac
import json
import time
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server
from src.monetization import StripeWebhookAdapter, SubscriptionStore, get_configured_plans, get_payment_methods


def test_mobile_money_payment_request_and_admin_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="admin-secret-token-123456"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    owner = "user:u" + "a" * 32

    created = server.create_payment_request_endpoint(
        server.PaymentRequestCreate(
            provider="airtel_money",
            plan_id="premium",
            phone_or_ref="+23566001122",
            transaction_ref="AM-20261119-9988",
            amount_xaf=15000,
            note="Paiement mensuel PRO",
        ),
        owner_id=owner,
        sub_store=sub_store,
    )
    assert created["status"] == "pending"
    assert created["provider"] == "airtel_money"

    mine = server.list_my_payment_requests_endpoint(owner_id=owner, sub_store=sub_store)
    assert mine["count"] == 1
    assert mine["requests"][0]["transaction_ref"] == "AM-20261119-9988"

    pending = server.admin_list_payment_requests_endpoint(
        status="pending",
        limit=50,
        x_admin_token="admin-secret-token-123456",
        sub_store=sub_store,
    )
    assert pending["count"] == 1

    reviewed = server.admin_review_payment_request_endpoint(
        created["request_id"],
        server.PaymentRequestReview(decision="approved", period_days=30, note="Reçu Airtel Money"),
        x_admin_token="admin-secret-token-123456",
        sub_store=sub_store,
    )
    assert reviewed["request"]["status"] == "approved"
    assert reviewed["subscription"]["effective_plan_id"] == "premium"

    # Re-reviewing an already processed request fails with 409
    with pytest.raises(HTTPException) as exc_409:
        server.admin_review_payment_request_endpoint(
            created["request_id"],
            server.PaymentRequestReview(decision="rejected", period_days=30),
            x_admin_token="admin-secret-token-123456",
            sub_store=sub_store,
        )
    assert exc_409.value.status_code == 409

    # User now has PRO quotas in /billing/me
    billing = server.get_my_billing_endpoint(owner_id=owner, x_premium_key=None, sub_store=sub_store)
    assert billing["is_pro"] is True
    assert billing["subscription"]["effective_plan_id"] == "premium"


def test_stripe_webhook_adapter_verification_and_idempotency(tmp_path):
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    adapter = StripeWebhookAdapter()
    secret = "whsec_test_secret_1234567890"
    ts = int(time.time())
    payload = {
        "id": "evt_stripe_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": "u" + "b" * 32,
                "metadata": {"plan_id": "premium", "period_days": "30"},
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    sig_hex = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig_hex}"

    # Invalid signature rejected
    with pytest.raises(PermissionError):
        sub_store.process_webhook_idempotent(adapter, raw, f"t={ts},v1=deadbeef", secret)

    # Valid signature processed & activates subscription
    res = sub_store.process_webhook_idempotent(adapter, raw, header, secret)
    assert res["status"] == "processed"
    assert res["user_id"] == "user:u" + "b" * 32
    sub = sub_store.get_subscription("user:u" + "b" * 32)
    assert sub["effective_plan_id"] == "premium"

    # Duplicate event ignored idempotently
    dup = sub_store.process_webhook_idempotent(adapter, raw, header, secret)
    assert dup["status"] == "duplicate_ignored"


def test_env_configured_pricing_and_payment_methods(monkeypatch):
    monkeypatch.setenv("PLAN_PREMIUM_PRICE_XAF", "15000")
    monkeypatch.setenv("MOBILE_MONEY_AIRTEL_NUMBER", "+23566112233")
    monkeypatch.setenv("STRIPE_CHECKOUT_URL", "https://buy.stripe.com/test_freedata")

    plans = {p["plan_id"]: p for p in get_configured_plans()}
    assert plans["premium"]["price_configured"] is True
    assert plans["premium"]["price_xaf_month"] == 15000

    methods = get_payment_methods()
    assert methods["premium_price_xaf_month"] == 15000
    by_provider = {m["provider"]: m for m in methods["methods"]}
    assert by_provider["airtel_money"]["configured"] is True
    assert by_provider["airtel_money"]["destination"] == "+23566112233"
    assert by_provider["stripe"]["checkout_url"] == "https://buy.stripe.com/test_freedata"

