"""Centralized Subscription Lifecycle, Atomic Usage Metering, Provider-Independent Webhooks & Cost Simulation."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3

from src import db as _db
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def _parse_iso(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return None


DEFAULT_PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "plan_id": "free",
        "label": "Gratuit",
        "price_configured": False,
        "daily_chat_limit": 30,
        "monthly_pdf_limit": 0,
        "daily_ml_limit": 5,
        "daily_rag_limit": 20,
        "max_projects": 5,
        "max_file_mb": 2,
        "history_limit": 40,
        "features": ["general_chat", "domain_chat", "rag_search", "analytics_read", "market_lookup", "project_workspace"],
    },
    "trial": {
        "plan_id": "trial",
        "label": "Essai PRO",
        "price_configured": False,
        "daily_chat_limit": 100,
        "monthly_pdf_limit": 5,
        "daily_ml_limit": 30,
        "daily_rag_limit": 100,
        "max_projects": 20,
        "max_file_mb": 10,
        "history_limit": 100,
        "features": ["general_chat", "domain_chat", "rag_search", "analytics_read", "market_lookup", "project_workspace", "pro_pdf_reports", "llm_synthesis"],
    },
    "premium": {
        "plan_id": "premium",
        "label": "Partenaire PRO",
        "price_configured": False,
        "daily_chat_limit": 500,
        "monthly_pdf_limit": 50,
        "daily_ml_limit": 200,
        "daily_rag_limit": 500,
        "max_projects": 100,
        "max_file_mb": 25,
        "history_limit": 200,
        "features": [
            "general_chat", "domain_chat", "rag_search", "analytics_read", "market_lookup",
            "project_workspace", "pro_pdf_reports", "ml_batch_predict", "llm_synthesis", "async_report_jobs",
        ],
    },
}


class PaymentProviderAdapter(ABC):
    """Provider-independent payment abstraction (Chad mobile money, India UPI/Razorpay, Intl Stripe)."""

    provider_name: str = "generic"

    @abstractmethod
    def verify_signature(self, raw_body: bytes, signature_header: str, secret: str) -> bool:
        """Verify webhook cryptographic signature."""

    @abstractmethod
    def parse_webhook_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize external webhook event into {event_id, event_type, user_id, plan_id, status}."""


class HmacJsonWebhookAdapter(PaymentProviderAdapter):
    """Standard HMAC-SHA256 JSON webhook verifier suitable for custom/mobile-money/gateway bridges."""

    def __init__(self, provider_name: str = "generic_hmac") -> None:
        self.provider_name = provider_name

    def verify_signature(self, raw_body: bytes, signature_header: str, secret: str) -> bool:
        if not secret or not signature_header:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        provided = signature_header.strip().removeprefix("sha256=")
        return hmac.compare_digest(expected, provided)

    def parse_webhook_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": str(payload.get("event_id") or ""),
            "event_type": str(payload.get("event_type") or ""),
            "user_id": str(payload.get("user_id") or ""),
            "plan_id": str(payload.get("plan_id") or "premium"),
            "status": str(payload.get("status") or "active"),
            "period_days": int(payload.get("period_days") or 30),
        }


class SubscriptionStore:
    """SQLite-backed subscription lifecycle, atomic quota consumption, usage metering, and audit log."""

    def __init__(self, db_path: Optional[str] = None, *, database_url: Optional[str] = None, schema: Optional[str] = None) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = _db.validate_schema(schema) if schema else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        self.db_path = Path(db_path or os.getenv("FREEDATA_BILLING_DB_PATH", "data/freedata_billing.db"))
        if not self._pg_url:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL DEFAULT 'free',
                    status TEXT NOT NULL DEFAULT 'active',
                    provider TEXT NOT NULL DEFAULT 'manual',
                    external_subscription_id TEXT,
                    current_period_start TEXT NOT NULL,
                    current_period_end TEXT,
                    grace_until TEXT,
                    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_counters (
                    user_id TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, period_key, metric_name)
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    request_id TEXT,
                    operation TEXT NOT NULL,
                    provider_name TEXT,
                    model_name TEXT,
                    tokens_in INTEGER NOT NULL DEFAULT 0,
                    tokens_out INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL NOT NULL DEFAULT 0.0,
                    success INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_webhook_events (
                    webhook_event_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    target_user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    previous_plan TEXT,
                    new_plan TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    def get_subscription(self, user_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return {
                    "user_id": user_id,
                    "plan_id": "free",
                    "effective_plan_id": "free",
                    "status": "active",
                    "provider": "none",
                    "current_period_end": None,
                    "limits": DEFAULT_PLANS["free"],
                }
            sub = dict(row)
            eff_plan = sub["plan_id"]
            status = sub["status"]
            end_dt = _parse_iso(sub.get("current_period_end"))
            grace_dt = _parse_iso(sub.get("grace_until"))
            if sub["plan_id"] in ("trial", "premium"):
                if status in ("cancelled", "expired"):
                    eff_plan = "free"
                elif end_dt and now > end_dt:
                    if grace_dt and now <= grace_dt:
                        status = "grace_period"
                    else:
                        status = "expired"
                        eff_plan = "free"
            sub["status"] = status
            sub["effective_plan_id"] = eff_plan
            sub["limits"] = DEFAULT_PLANS.get(eff_plan, DEFAULT_PLANS["free"])
            return sub

    def check_feature_access(self, user_id: str, feature: str) -> None:
        sub = self.get_subscription(user_id)
        allowed = sub["limits"]["features"]
        if feature not in allowed:
            raise PermissionError(f"Fonctionnalité '{feature}' non incluse dans le plan '{sub['effective_plan_id']}'.")

    def consume_usage_atomic(self, user_id: str, metric_name: str, limit: int, period_key: Optional[str] = None) -> dict[str, Any]:
        """Atomically checks and increments a usage counter using SQLite BEGIN IMMEDIATE."""
        now_dt = _utc_now()
        pkey = period_key or (now_dt.strftime("%Y-%m") if "monthly" in metric_name else now_dt.strftime("%Y-%m-%d"))
        now_s = _iso(now_dt) or ""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT used_count FROM usage_counters WHERE user_id = ? AND period_key = ? AND metric_name = ?",
                (user_id, pkey, metric_name),
            ).fetchone()
            current = int(row["used_count"]) if row else 0
            if current >= limit:
                conn.execute("ROLLBACK;")
                raise OverflowError(f"Quota '{metric_name}' dépassé ({current}/{limit} pour {pkey}).")
            next_val = current + 1
            conn.execute(
                """
                INSERT INTO usage_counters (user_id, period_key, metric_name, used_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (user_id, period_key, metric_name)
                DO UPDATE SET used_count = excluded.used_count, updated_at = excluded.updated_at
                """,
                (user_id, pkey, metric_name, next_val, now_s),
            )
            conn.execute("COMMIT;")
            return {"metric": metric_name, "period": pkey, "used": next_val, "limit": limit, "remaining": limit - next_val}
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def record_usage_event(
        self,
        user_id: str,
        operation: str,
        *,
        request_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0.0,
        success: bool = True,
    ) -> str:
        """Logs anonymized metering metadata (never stores private prompts or documents)."""
        ev_id = f"USE-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (event_id, user_id, request_id, operation, provider_name, model_name, tokens_in, tokens_out, latency_ms, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ev_id, user_id, request_id, operation, provider_name, model_name, int(tokens_in), int(tokens_out), float(latency_ms), 1 if success else 0, _iso(_utc_now())),
            )
        return ev_id

    def get_usage_summary(self, user_id: str) -> dict[str, Any]:
        sub = self.get_subscription(user_id)
        now = _utc_now()
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT period_key, metric_name, used_count FROM usage_counters WHERE user_id = ? AND period_key IN (?, ?)",
                (user_id, day_key, month_key),
            ).fetchall()
            counters = {r["metric_name"]: int(r["used_count"]) for r in rows}
            ev_count = conn.execute("SELECT COUNT(*) FROM usage_events WHERE user_id = ?", (user_id,)).fetchone()[0]
        lim = sub["limits"]
        return {
            "subscription": sub,
            "quotas": {
                "daily_chat": {"used": counters.get("daily_chat", 0), "limit": lim["daily_chat_limit"]},
                "monthly_pdf": {"used": counters.get("monthly_pdf", 0), "limit": lim["monthly_pdf_limit"]},
                "daily_ml": {"used": counters.get("daily_ml", 0), "limit": lim["daily_ml_limit"]},
                "daily_rag": {"used": counters.get("daily_rag", 0), "limit": lim["daily_rag_limit"]},
            },
            "total_metered_events": int(ev_count),
        }

    def admin_update_subscription(
        self,
        *,
        actor: str,
        target_user_id: str,
        plan_id: str,
        status: str = "active",
        period_days: int = 30,
        grace_days: int = 3,
        provider: str = "manual",
        reason: str = "",
    ) -> dict[str, Any]:
        if plan_id not in DEFAULT_PLANS:
            raise ValueError(f"Plan inconnu : {plan_id}")
        prev = self.get_subscription(target_user_id)
        now = _utc_now()
        end_dt = now + timedelta(days=period_days) if plan_id in ("trial", "premium") and period_days > 0 else None
        grace_dt = (end_dt + timedelta(days=grace_days)) if end_dt else None
        audit_id = f"AUD-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO subscriptions (user_id, plan_id, status, provider, current_period_start, current_period_end, grace_until, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    status = excluded.status,
                    provider = excluded.provider,
                    current_period_start = excluded.current_period_start,
                    current_period_end = excluded.current_period_end,
                    grace_until = excluded.grace_until,
                    updated_at = excluded.updated_at
                """,
                (target_user_id, plan_id, status, provider, _iso(now), _iso(end_dt), _iso(grace_dt), _iso(now)),
            )
            conn.execute(
                """
                INSERT INTO subscription_audit_logs (audit_id, actor, target_user_id, action, previous_plan, new_plan, reason, created_at)
                VALUES (?, ?, ?, 'admin_update_subscription', ?, ?, ?, ?)
                """,
                (audit_id, actor, target_user_id, prev["plan_id"], plan_id, reason, _iso(now)),
            )
            conn.execute("COMMIT;")
        return self.get_subscription(target_user_id)

    def process_webhook_idempotent(
        self,
        adapter: PaymentProviderAdapter,
        raw_body: bytes,
        signature_header: str,
        webhook_secret: str,
    ) -> dict[str, Any]:
        if not adapter.verify_signature(raw_body, signature_header, webhook_secret):
            raise PermissionError("Signature webhook invalide.")
        payload = json.loads(raw_body.decode("utf-8"))
        ev = adapter.parse_webhook_event(payload)
        ev_id = ev["event_id"]
        if not ev_id or not ev["user_id"]:
            raise ValueError("Webhook incomplet (event_id et user_id requis).")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT webhook_event_id FROM payment_webhook_events WHERE webhook_event_id = ?",
                (ev_id,),
            ).fetchone()
            if existing:
                return {"status": "duplicate_ignored", "event_id": ev_id}
            conn.execute(
                "INSERT INTO payment_webhook_events (webhook_event_id, provider, event_type, processed_at) VALUES (?, ?, ?, ?)",
                (ev_id, adapter.provider_name, ev["event_type"], _iso(_utc_now())),
            )

        self.admin_update_subscription(
            actor=f"webhook:{adapter.provider_name}",
            target_user_id=ev["user_id"],
            plan_id=ev["plan_id"],
            status=ev["status"],
            period_days=ev["period_days"],
            provider=adapter.provider_name,
            reason=f"Webhook {ev['event_type']} ({ev_id})",
        )
        return {"status": "processed", "event_id": ev_id, "user_id": ev["user_id"], "plan_id": ev["plan_id"]}

    def get_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM subscription_audit_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


def simulate_unit_economics(
    *,
    active_users: int = 100,
    paid_users: int = 20,
    monthly_subscription_price_xaf: float = 0.0,
    avg_chats_per_user_month: int = 25,
    avg_pdfs_per_paid_user_month: int = 3,
    cost_per_chat_xaf: float = 2.0,
    cost_per_pdf_xaf: float = 5.0,
    cost_per_ml_rag_op_xaf: float = 0.5,
    monthly_infra_fixed_xaf: float = 15000.0,
) -> dict[str, Any]:
    """Configurable cost & gross margin simulator (never invents final retail prices)."""
    total_chats = active_users * avg_chats_per_user_month
    total_pdfs = paid_users * avg_pdfs_per_paid_user_month
    total_ml_rag = active_users * 15
    var_cost = (total_chats * cost_per_chat_xaf) + (total_pdfs * cost_per_pdf_xaf) + (total_ml_rag * cost_per_ml_rag_op_xaf)
    total_cost = var_cost + monthly_infra_fixed_xaf
    revenue = paid_users * monthly_subscription_price_xaf
    gross_margin = revenue - total_cost
    return {
        "active_users": active_users,
        "paid_users": paid_users,
        "monthly_revenue_xaf": round(revenue, 2),
        "cost_per_conversation_xaf": round(cost_per_chat_xaf + cost_per_ml_rag_op_xaf, 2),
        "cost_per_report_xaf": round(cost_per_pdf_xaf + cost_per_ml_rag_op_xaf, 2),
        "avg_cost_per_user_xaf": round(total_cost / max(1, active_users), 2),
        "monthly_infra_fixed_xaf": round(monthly_infra_fixed_xaf, 2),
        "total_monthly_cost_xaf": round(total_cost, 2),
        "estimated_gross_margin_xaf": round(gross_margin, 2),
        "note": "Simulation basée sur des hypothèses configurables ; aucun tarif commercial final n'est imposé.",
    }

