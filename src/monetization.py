"""Centralized Subscription Lifecycle, Atomic Usage Metering, Provider-Independent Webhooks & Cost Simulation."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
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
        "label": "Standard (Gratuit)",
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
        "label": "FreeData PRO",
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


_STRIPE_ACTIVATING_EVENTS = frozenset({"checkout.session.completed", "invoice.paid", "invoice.payment_succeeded"})
_STRIPE_CANCEL_EVENTS = frozenset({"customer.subscription.deleted"})


class StripeWebhookAdapter(PaymentProviderAdapter):
    """Stripe webhook signature verifier (t=...,v1=...) & event normalizer."""

    provider_name: str = "stripe"

    def __init__(self, tolerance_seconds: int = 300) -> None:
        self.tolerance_seconds = tolerance_seconds

    def verify_signature(self, raw_body: bytes, signature_header: str, secret: str) -> bool:
        if not secret or not signature_header:
            return False
        parts: dict[str, list[str]] = {}
        for item in signature_header.split(","):
            if "=" not in item:
                continue
            k, v = item.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
        ts_list = parts.get("t") or []
        sigs = parts.get("v1") or []
        if not ts_list or not sigs:
            return False
        try:
            ts = int(ts_list[0])
        except ValueError:
            return False
        if self.tolerance_seconds > 0:
            now_ts = int(_utc_now().timestamp())
            if abs(now_ts - ts) > self.tolerance_seconds:
                return False
        signed_payload = f"{ts}.".encode("utf-8") + raw_body
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, s) for s in sigs)

    def parse_webhook_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        ev_id = str(payload.get("id") or payload.get("event_id") or "")
        ev_type = str(payload.get("type") or payload.get("event_type") or "")
        obj = (payload.get("data") or {}).get("object") or {}
        meta = obj.get("metadata") if isinstance(obj, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        user_id = str(meta.get("user_id") or obj.get("client_reference_id") or payload.get("user_id") or "").strip()
        if user_id and not user_id.startswith("user:") and not user_id.startswith("key:"):
            user_id = f"user:{user_id}"
        plan_id = str(meta.get("plan_id") or "premium").strip()
        if plan_id not in DEFAULT_PLANS:
            plan_id = "premium"
        if ev_type in _STRIPE_CANCEL_EVENTS:
            status = "cancelled"
        elif ev_type in _STRIPE_ACTIVATING_EVENTS:
            status = "active"
            # Une session de paiement non réglée (ex. paiement différé) n'ouvre pas de droits.
            if isinstance(obj, dict) and obj.get("payment_status") not in (None, "paid", "no_payment_required"):
                status = "ignored"
        else:
            status = "ignored"  # invoice.payment_failed, checkout.session.expired, customer.created, etc.
        try:
            period_days = int(meta.get("period_days") or 30)
        except (TypeError, ValueError):
            period_days = 30
        return {
            "event_id": ev_id,
            "event_type": ev_type,
            "user_id": user_id,
            "plan_id": plan_id,
            "status": status,
            "period_days": max(1, min(365, period_days)),
        }


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return val if val >= 0 else default
    except ValueError:
        return default


def get_configured_plans() -> list[dict[str, Any]]:
    """Retourne les plans enrichis par la tarification environnementale si définie."""
    premium_price = _env_int("PLAN_PREMIUM_PRICE_XAF", 0)
    stripe_url = os.getenv("STRIPE_CHECKOUT_URL", "").strip()
    plans = []
    for pid in ("free", "trial", "premium"):
        plan = dict(DEFAULT_PLANS[pid])
        if pid == "premium" and (premium_price > 0 or stripe_url):
            plan["price_configured"] = True
            if premium_price > 0:
                plan["price_xaf_month"] = premium_price
        plans.append(plan)
    return plans


def get_payment_methods() -> dict[str, Any]:
    """Catalogue dynamique des moyens de paiement configurés (Tchad Mobile Money + International Stripe)."""
    airtel = os.getenv("MOBILE_MONEY_AIRTEL_NUMBER", "").strip()
    moov = os.getenv("MOBILE_MONEY_MOOV_NUMBER", "").strip()
    bank = os.getenv("BANK_TRANSFER_DETAILS", "").strip()
    stripe_url = os.getenv("STRIPE_CHECKOUT_URL", "").strip()
    price_xaf = _env_int("PLAN_PREMIUM_PRICE_XAF", 0)

    methods: list[dict[str, Any]] = [
        {
            "provider": "airtel_money",
            "label": "Airtel Money (Tchad)",
            "kind": "mobile_money",
            "configured": bool(airtel),
            "destination": airtel or None,
            "instructions": (
                f"Envoyez le montant au numéro marchand Airtel Money {airtel}, puis renseignez la référence de transaction ci-dessous."
                if airtel
                else "Soumettez votre référence Airtel Money ; notre équipe confirmera le numéro marchand et activera votre compte PRO."
            ),
        },
        {
            "provider": "moov_money",
            "label": "Moov Money (Tchad)",
            "kind": "mobile_money",
            "configured": bool(moov),
            "destination": moov or None,
            "instructions": (
                f"Envoyez le montant au numéro marchand Moov Money {moov}, puis renseignez la référence de transaction ci-dessous."
                if moov
                else "Soumettez votre référence Moov Money ; notre équipe confirmera la réception et activera votre compte PRO."
            ),
        },
        {
            "provider": "bank_transfer",
            "label": "Virement bancaire / Facture B2B",
            "kind": "bank_transfer",
            "configured": bool(bank),
            "destination": bank or None,
            "instructions": bank or "Indiquez la référence du virement ou du bon de commande entreprise pour validation sous 24 h ouvrées.",
        },
    ]
    if stripe_url:
        methods.append(
            {
                "provider": "stripe",
                "label": "Carte bancaire internationale (Stripe)",
                "kind": "checkout_url",
                "configured": True,
                "checkout_url": stripe_url,
                "instructions": "Paiement sécurisé par carte bancaire ; activation automatique dès confirmation webhook.",
            }
        )
    return {
        "currency": "XAF",
        "premium_price_xaf_month": price_xaf if price_xaf > 0 else None,
        "methods": methods,
    }


_ALLOWED_PAYMENT_PROVIDERS = {"airtel_money", "moov_money", "bank_transfer", "mobile_money", "stripe"}


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
                CREATE TABLE IF NOT EXISTS payment_requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL DEFAULT 'premium',
                    provider TEXT NOT NULL,
                    amount_xaf INTEGER NOT NULL DEFAULT 0,
                    phone_or_ref TEXT NOT NULL,
                    transaction_ref TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pro_activation_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    plan_id TEXT NOT NULL DEFAULT 'premium',
                    duration_days INTEGER NOT NULL DEFAULT 30,
                    status TEXT NOT NULL DEFAULT 'unused',
                    note TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    redeemed_by_user_id TEXT,
                    redeemed_at TEXT,
                    revoked_by TEXT,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pro_keys_status ON pro_activation_keys(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_payment_requests_user ON payment_requests(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_payment_requests_status ON payment_requests(status, created_at DESC);
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
        if ev.get("status") == "ignored":
            return {"status": "ignored", "event_id": ev_id, "event_type": ev["event_type"]}
        if not ev_id or not ev["user_id"]:
            raise ValueError("Webhook incomplet (event_id et user_id requis).")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT webhook_event_id FROM payment_webhook_events WHERE webhook_event_id = ?",
                (ev_id,),
            ).fetchone()
            if existing:
                return {"status": "duplicate_ignored", "event_id": ev_id}

        # L'abonnement est mis à jour AVANT d'enregistrer l'événement : si la mise à jour échoue, le rejeu
        # du fournisseur n'est pas ignoré à tort (l'opération est idempotente : même état final).
        self.admin_update_subscription(
            actor=f"webhook:{adapter.provider_name}",
            target_user_id=ev["user_id"],
            plan_id=ev["plan_id"],
            status=ev["status"],
            period_days=ev["period_days"],
            provider=adapter.provider_name,
            reason=f"Webhook {ev['event_type']} ({ev_id})",
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO payment_webhook_events (webhook_event_id, provider, event_type, processed_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (webhook_event_id) DO NOTHING",
                (ev_id, adapter.provider_name, ev["event_type"], _iso(_utc_now())),
            )
        return {"status": "processed", "event_id": ev_id, "user_id": ev["user_id"], "plan_id": ev["plan_id"]}

    def purge_user(self, user_id: str) -> dict[str, int]:
        """Efface abonnement, compteurs, événements d'usage et demandes de paiement (le journal d'audit financier est conservé)."""
        counts: dict[str, int] = {}
        with self._connect() as conn:
            for table in ("subscriptions", "usage_counters", "usage_events", "payment_requests"):
                cur = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                counts[table] = int(cur.rowcount or 0)
            # La clé reste « utilisée » (anti-réutilisation) mais n'est plus rattachée à une personne.
            cur = conn.execute(
                "UPDATE pro_activation_keys SET redeemed_by_user_id = 'deleted' WHERE redeemed_by_user_id = ?", (user_id,)
            )
            counts["pro_activation_keys"] = int(cur.rowcount or 0)
        return counts

    def get_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM subscription_audit_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def create_payment_request(
        self,
        user_id: str,
        *,
        provider: str,
        phone_or_ref: str,
        transaction_ref: str,
        plan_id: str = "premium",
        amount_xaf: int = 0,
        note: str = "",
    ) -> dict[str, Any]:
        clean_provider = (provider or "").strip().lower()
        if clean_provider not in _ALLOWED_PAYMENT_PROVIDERS:
            raise ValueError(f"Moyen de paiement non supporté : {provider}")
        if plan_id not in ("trial", "premium"):
            raise ValueError("Plan cible invalide (trial ou premium requis).")
        clean_phone = (phone_or_ref or "").strip()[:80]
        clean_tx = (transaction_ref or "").strip()[:120]
        if len(clean_phone) < 3 or len(clean_tx) < 3:
            raise ValueError("Numéro / identifiant payeur et référence de transaction requis (min. 3 caractères).")
        req_id = f"PAY-{uuid.uuid4().hex[:10].upper()}"
        now = _iso(_utc_now()) or ""
        with self._connect() as conn:
            dup = conn.execute(
                "SELECT request_id FROM payment_requests WHERE provider = ? AND transaction_ref = ? AND status IN ('pending', 'approved')",
                (clean_provider, clean_tx),
            ).fetchone()
            if dup:
                raise ValueError("Cette référence de transaction a déjà été soumise.")
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM payment_requests WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            ).fetchone()
            if pending and int(pending["n"]) >= 5:
                raise ValueError("Trop de demandes de paiement en attente (maximum 5). Patientez la validation.")
            conn.execute(
                """
                INSERT INTO payment_requests (
                    request_id, user_id, plan_id, provider, amount_xaf,
                    phone_or_ref, transaction_ref, status, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (req_id, user_id, plan_id, clean_provider, max(0, int(amount_xaf)), clean_phone, clean_tx, (note or "").strip()[:400], now),
            )
            row = conn.execute("SELECT * FROM payment_requests WHERE request_id = ?", (req_id,)).fetchone()
        return dict(row)

    def list_payment_requests(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM payment_requests WHERE 1=1"
        params: list[Any] = []
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(200, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def review_payment_request(
        self,
        request_id: str,
        *,
        actor: str,
        decision: str,
        period_days: int = 30,
        note: str = "",
    ) -> dict[str, Any]:
        if decision not in ("approved", "rejected"):
            raise ValueError("Décision invalide : 'approved' ou 'rejected' attendu.")
        now = _iso(_utc_now()) or ""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM payment_requests WHERE request_id = ?", (request_id,)).fetchone()
            if not row:
                raise KeyError(f"Demande de paiement introuvable : {request_id}")
            req = dict(row)
            if req["status"] != "pending":
                raise ValueError(f"Demande déjà traitée (statut : {req['status']}).")
            final_note = (note or "").strip()[:400] or req.get("note", "")
            conn.execute(
                """
                UPDATE payment_requests
                SET status = ?, note = ?, reviewed_by = ?, reviewed_at = ?
                WHERE request_id = ?
                """,
                (decision, final_note, actor, now, request_id),
            )
            updated = dict(conn.execute("SELECT * FROM payment_requests WHERE request_id = ?", (request_id,)).fetchone())

        subscription = None
        if decision == "approved":
            subscription = self.admin_update_subscription(
                actor=actor,
                target_user_id=updated["user_id"],
                plan_id=updated["plan_id"],
                status="active",
                period_days=max(1, min(365, int(period_days))),
                provider=updated["provider"],
                reason=f"Paiement validé ({request_id} · réf. {updated['transaction_ref']})",
            )
        return {"request": updated, "subscription": subscription}

    # --- Clés d'activation PRO uniques (1 clé = 1 compte connecté) -----------

    @staticmethod
    def _normalize_activation_key(raw_key: str) -> str:
        return re.sub(r"\s+", "", (raw_key or "").strip()).upper()

    @staticmethod
    def _hash_activation_key(normalized_key: str) -> str:
        return hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _generate_plain_activation_key() -> str:
        import secrets
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
        return f"FDPRO-{'-'.join(parts)}"

    def create_activation_key(
        self,
        *,
        actor: str,
        plan_id: str = "premium",
        duration_days: int = 30,
        note: str = "",
    ) -> dict[str, Any]:
        if plan_id not in ("trial", "premium"):
            raise ValueError("Seuls les plans 'trial' ou 'premium' peuvent être activés par clé.")
        days = max(1, min(365, int(duration_days)))
        plain_key = self._generate_plain_activation_key()
        key_hash = self._hash_activation_key(plain_key)
        key_prefix = plain_key[:10]
        key_id = f"KEY-{uuid.uuid4().hex[:10].upper()}"
        now = _iso(_utc_now()) or ""
        clean_note = (note or "").strip()[:240]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pro_activation_keys (
                    key_id, key_hash, key_prefix, plan_id, duration_days,
                    status, note, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'unused', ?, ?, ?)
                """,
                (key_id, key_hash, key_prefix, plan_id, days, clean_note, actor, now),
            )
        return {
            "key_id": key_id,
            "activation_key": plain_key,
            "key_prefix": key_prefix,
            "plan_id": plan_id,
            "duration_days": days,
            "status": "unused",
            "note": clean_note,
            "created_by": actor,
            "created_at": now,
        }

    def list_activation_keys(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(200, int(limit)))
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT key_id, key_prefix, plan_id, duration_days, status, note,
                           created_by, created_at, redeemed_by_user_id, redeemed_at,
                           revoked_by, revoked_at
                    FROM pro_activation_keys
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status.strip().lower(), lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT key_id, key_prefix, plan_id, duration_days, status, note,
                           created_by, created_at, redeemed_by_user_id, redeemed_at,
                           revoked_by, revoked_at
                    FROM pro_activation_keys
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        return [dict(r) for r in rows]

    def revoke_activation_key(self, key_id: str, *, actor: str) -> dict[str, Any]:
        now = _iso(_utc_now()) or ""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT key_id, key_prefix, status FROM pro_activation_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK;")
                raise KeyError(f"Clé introuvable : {key_id}")
            if row["status"] != "unused":
                conn.execute("ROLLBACK;")
                raise ValueError(f"Impossible de révoquer cette clé (statut actuel : {row['status']}).")
            conn.execute(
                """
                UPDATE pro_activation_keys
                SET status = 'revoked', revoked_by = ?, revoked_at = ?
                WHERE key_id = ? AND status = 'unused'
                """,
                (actor, now, key_id),
            )
            conn.execute("COMMIT;")
        return {"key_id": key_id, "key_prefix": row["key_prefix"], "status": "revoked", "revoked_by": actor, "revoked_at": now}

    def redeem_activation_key(self, user_id: str, raw_key: str) -> dict[str, Any]:
        """Active atomiquement une clé PRO unique pour le compte `user_id` (usage unique strict)."""
        norm_key = self._normalize_activation_key(raw_key)
        if len(norm_key) < 8 or len(norm_key) > 64:
            raise ValueError("Format de clé d'activation invalide.")
        key_hash = self._hash_activation_key(norm_key)
        now_dt = _utc_now()
        now_s = _iso(now_dt) or ""
        audit_id = f"AUD-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                """
                SELECT key_id, key_prefix, plan_id, duration_days, status
                FROM pro_activation_keys
                WHERE key_hash = ?
                """,
                (key_hash,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK;")
                raise KeyError("Clé d'activation PRO introuvable ou invalide.")
            if row["status"] != "unused":
                conn.execute("ROLLBACK;")
                raise ValueError("Cette clé d'activation a déjà été utilisée ou révoquée.")
            cur = conn.execute(
                """
                UPDATE pro_activation_keys
                SET status = 'redeemed', redeemed_by_user_id = ?, redeemed_at = ?
                WHERE key_id = ? AND status = 'unused'
                """,
                (user_id, now_s, row["key_id"]),
            )
            if (cur.rowcount or 0) != 1:
                conn.execute("ROLLBACK;")
                raise ValueError("Cette clé d'activation a déjà été utilisée.")

            prev_row = conn.execute(
                "SELECT plan_id, status, current_period_end FROM subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            prev_plan = prev_row["plan_id"] if prev_row else "free"
            base_end = now_dt
            if prev_row and prev_row["plan_id"] == row["plan_id"] and prev_row["status"] == "active":
                existing_end = _parse_iso(prev_row["current_period_end"])
                if existing_end and existing_end > now_dt:
                    base_end = existing_end
            new_end = base_end + timedelta(days=int(row["duration_days"]))
            grace_dt = new_end + timedelta(days=3)
            conn.execute(
                """
                INSERT INTO subscriptions (user_id, plan_id, status, provider, current_period_start, current_period_end, grace_until, updated_at)
                VALUES (?, ?, 'active', 'activation_key', ?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    status = 'active',
                    provider = 'activation_key',
                    current_period_start = excluded.current_period_start,
                    current_period_end = excluded.current_period_end,
                    grace_until = excluded.grace_until,
                    updated_at = excluded.updated_at
                """,
                (user_id, row["plan_id"], now_s, _iso(new_end), _iso(grace_dt), now_s),
            )
            conn.execute(
                """
                INSERT INTO subscription_audit_logs (audit_id, actor, target_user_id, action, previous_plan, new_plan, reason, created_at)
                VALUES (?, ?, ?, 'redeem_activation_key', ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    user_id,
                    user_id,
                    prev_plan,
                    row["plan_id"],
                    f"Activation clé unique {row['key_id']} ({row['duration_days']} j)",
                    now_s,
                ),
            )
            conn.execute("COMMIT;")
        sub = self.get_subscription(user_id)
        return {
            "redeemed": True,
            "key_id": row["key_id"],
            "key_prefix": row["key_prefix"],
            "duration_days": int(row["duration_days"]),
            "subscription": sub,
            "is_pro": sub.get("effective_plan_id") in ("trial", "premium"),
        }


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

