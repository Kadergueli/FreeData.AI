"""Tests for Monetization: Free/Premium permissions, expiry, concurrent atomic quotas, webhooks, and audit."""
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from api import server
from src.monetization import HmacJsonWebhookAdapter, SubscriptionStore, simulate_unit_economics


def test_free_premium_permissions_and_expired_subscription(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))

    # Default free user cannot generate PRO PDFs
    store.check_feature_access("u_free", "general_chat")
    with pytest.raises(PermissionError):
        store.check_feature_access("u_free", "pro_pdf_reports")

    # Manual admin activation grants premium
    store.admin_update_subscription(
        actor="admin",
        target_user_id="u_pro",
        plan_id="premium",
        status="active",
        period_days=30,
        reason="Partner onboarding",
    )
    store.check_feature_access("u_pro", "pro_pdf_reports")
    assert len(store.get_audit_logs()) == 1

    # Expired subscription (past grace_until) falls back to free
    past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    with store._connect() as conn:
        conn.execute("UPDATE subscriptions SET current_period_end = ?, grace_until = ? WHERE user_id = ?", (past, past, "u_pro"))
    sub = store.get_subscription("u_pro")
    assert sub["status"] == "expired"
    assert sub["effective_plan_id"] == "free"
    with pytest.raises(PermissionError):
        store.check_feature_access("u_pro", "pro_pdf_reports")


def test_atomic_concurrent_quota_enforcement(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    limit = 5

    def _hit(_):
        try:
            store.consume_usage_atomic("u_conc", "daily_chat", limit)
            return "ok"
        except OverflowError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_hit, range(12)))

    assert results.count("ok") == 5
    assert results.count("blocked") == 7


def test_webhook_signature_and_replay_protection(tmp_path):
    store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    adapter = HmacJsonWebhookAdapter("mobile_money_bridge")
    secret = "whsec_test_123456"
    payload = {"event_id": "EVT-001", "event_type": "payment.succeeded", "user_id": "u_pay", "plan_id": "premium", "status": "active", "period_days": 30}
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    # Invalid signature rejected
    with pytest.raises(PermissionError):
        store.process_webhook_idempotent(adapter, raw, "bad-sig", secret)

    # First valid webhook activates subscription
    res1 = store.process_webhook_idempotent(adapter, raw, sig, secret)
    assert res1["status"] == "processed"
    assert store.get_subscription("u_pay")["effective_plan_id"] == "premium"

    # Replay attack with same event_id is safely ignored
    res2 = store.process_webhook_idempotent(adapter, raw, sig, secret)
    assert res2["status"] == "duplicate_ignored"


def test_usage_metering_failed_ai_and_admin_auth(tmp_path, monkeypatch):
    store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    store.record_usage_event("u_m", "llm_chat", request_id="req-1", model_name="llama-3.3", tokens_in=120, tokens_out=0, latency_ms=510.0, success=False)
    summary = store.get_usage_summary("u_m")
    assert summary["total_metered_events"] == 1

    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="adm-12"))
    with pytest.raises(HTTPException) as exc:
        server.admin_activate_subscription_endpoint(
            server.AdminSubscriptionActivateRequest(target_user_id="u_m", plan_id="premium"),
            x_admin_token="wrong",
            sub_store=store,
        )
    assert exc.value.status_code == 403

    sim = simulate_unit_economics(active_users=100, paid_users=20, monthly_subscription_price_xaf=5000.0)
    assert sim["monthly_revenue_xaf"] == 100000.0
    assert "estimated_gross_margin_xaf" in sim

