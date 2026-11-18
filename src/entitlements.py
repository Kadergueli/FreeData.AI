"""Backend-enforced Free & Premium Entitlements and Daily Usage Quotas."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class EntitlementManager:
    """Enforces feature access and daily usage quotas in the backend."""

    POLICIES: dict[str, dict[str, Any]] = {
        "free": {
            "tier": "free",
            "daily_chat_quota": 30,
            "max_active_projects": 5,
            "max_documents": 10,
            "allowed_features": {
                "general_chat",
                "domain_chat",
                "rag_search",
                "analytics_read",
                "market_lookup",
                "project_workspace",
            },
            "model_policy": "deterministic_tools_plus_free_rag",
        },
        "premium": {
            "tier": "premium",
            "daily_chat_quota": 500,
            "max_active_projects": 100,
            "max_documents": 200,
            "allowed_features": {
                "general_chat",
                "domain_chat",
                "rag_search",
                "analytics_read",
                "market_lookup",
                "project_workspace",
                "pro_pdf_reports",
                "ml_batch_predict",
                "llm_synthesis",
                "async_report_jobs",
            },
            "model_policy": "full_llm_plus_ml_rag_pro_pdf",
        },
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage: dict[str, dict[str, Any]] = {}  # user_id -> {day, count}

    def get_entitlements(self, tier: str, user_id: str) -> dict[str, Any]:
        eff_tier = "premium" if tier == "premium" else "free"
        pol = dict(self.POLICIES[eff_tier])
        pol["allowed_features"] = sorted(pol["allowed_features"])
        today = _utc_day()
        with self._lock:
            u = self._usage.get(user_id)
            used = u["count"] if (u and u["day"] == today) else 0
        pol["used_today"] = used
        pol["remaining_today"] = max(0, pol["daily_chat_quota"] - used)
        return pol

    def check_feature(self, tier: str, feature: str) -> None:
        eff_tier = "premium" if tier == "premium" else "free"
        allowed = self.POLICIES[eff_tier]["allowed_features"]
        if feature not in allowed:
            raise PermissionError(f"La fonctionnalité '{feature}' nécessite un accès Premium.")

    def consume_chat_quota(self, tier: str, user_id: str) -> dict[str, Any]:
        eff_tier = "premium" if tier == "premium" else "free"
        limit = int(self.POLICIES[eff_tier]["daily_chat_quota"])
        today = _utc_day()
        with self._lock:
            rec = self._usage.get(user_id)
            if not rec or rec["day"] != today:
                rec = {"day": today, "count": 0}
                self._usage[user_id] = rec
            if rec["count"] >= limit:
                raise OverflowError(f"Quota journalier atteint ({limit} requêtes/jour pour le niveau {eff_tier}).")
            rec["count"] += 1
            return {"tier": eff_tier, "used_today": rec["count"], "remaining_today": limit - rec["count"]}

