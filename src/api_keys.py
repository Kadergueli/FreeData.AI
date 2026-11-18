"""Lightweight API Key Manager with issuance, revocation, and daily usage quotas."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class ApiKeyManager:
    """Thread-safe in-memory API key lifecycle & quota manager."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, Any]] = {}  # key_id -> metadata

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def issue_key(self, owner_id: str, *, label: str = "default", daily_quota: int = 500) -> dict[str, Any]:
        raw_key = f"fd_{secrets.token_urlsafe(24)}"
        key_id = f"KEY-{secrets.token_hex(4).upper()}"
        key_hash = self._hash_key(raw_key)
        with self._lock:
            self._keys[key_id] = {
                "key_id": key_id,
                "key_hash": key_hash,
                "owner_id": owner_id,
                "label": label,
                "daily_quota": max(1, int(daily_quota)),
                "revoked": False,
                "usage_day": _utc_day(),
                "usage_count": 0,
            }
        return {"key_id": key_id, "api_key": raw_key, "owner_id": owner_id, "daily_quota": daily_quota}

    def revoke_key(self, key_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._keys.get(key_id)
            if not rec:
                raise KeyError(f"Clé API introuvable : {key_id}")
            rec["revoked"] = True
            return {"key_id": key_id, "revoked": True}

    def list_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in rec.items() if k != "key_hash"} for rec in self._keys.values()]

    def validate_and_consume(self, raw_key: Optional[str]) -> Optional[dict[str, Any]]:
        if not raw_key or not raw_key.strip().startswith("fd_"):
            return None
        candidate_hash = self._hash_key(raw_key)
        today = _utc_day()
        with self._lock:
            for rec in self._keys.values():
                if hmac.compare_digest(rec["key_hash"], candidate_hash):
                    if rec["revoked"]:
                        raise PermissionError("Clé API révoquée.")
                    if rec["usage_day"] != today:
                        rec["usage_day"] = today
                        rec["usage_count"] = 0
                    if rec["usage_count"] >= rec["daily_quota"]:
                        raise OverflowError("Quota journalier de la clé API dépassé.")
                    rec["usage_count"] += 1
                    return {k: v for k, v in rec.items() if k != "key_hash"}
        return None

