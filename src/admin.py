"""Centralized Admin RBAC, User Management, Model Flags, and Immutable Audit Logging."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "read_only_analyst": {"read_overview"},
    "support_admin": {"read_overview", "manage_users", "manage_subscriptions"},
    "platform_admin": {
        "read_overview",
        "manage_users",
        "manage_subscriptions",
        "manage_models",
        "manage_data_governance",
        "manage_system",
    },
    "super_admin": {
        "read_overview",
        "manage_users",
        "manage_roles",
        "manage_subscriptions",
        "manage_models",
        "manage_data_governance",
        "manage_system",
        "delete_user_data",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AdminService:
    """SQLite-backed RBAC, account suspension, model availability flags, and admin audit logs."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path or os.getenv("FREEDATA_ADMIN_DB_PATH", "data/freedata_admin.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_accounts (
                    user_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'user',
                    account_status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_flags (
                    profile_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def check_permission(role: str, permission: str) -> None:
        perms = ROLE_PERMISSIONS.get(role)
        if not perms or permission not in perms:
            raise PermissionError(f"Rôle '{role}' non autorisé pour l'action '{permission}'.")

    def log_action(
        self,
        *,
        actor: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: str = "",
    ) -> dict[str, Any]:
        rec = {
            "audit_id": f"ADM-{uuid.uuid4().hex[:10].upper()}",
            "actor": actor,
            "actor_role": actor_role,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details,
            "created_at": _utc_now(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_audit_logs (audit_id, actor, actor_role, action, resource_type, resource_id, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["audit_id"], rec["actor"], rec["actor_role"], rec["action"],
                    rec["resource_type"], rec["resource_id"], rec["details"], rec["created_at"],
                ),
            )
        return rec

    def set_user_status(
        self,
        *,
        actor: str,
        actor_role: str,
        target_user_id: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any]:
        self.check_permission(actor_role, "manage_users")
        if status not in ("active", "suspended"):
            raise ValueError("Statut invalide (active | suspended).")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_accounts (user_id, role, account_status, updated_at)
                VALUES (?, 'user', ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET account_status = excluded.account_status, updated_at = excluded.updated_at
                """,
                (target_user_id, status, now),
            )
        self.log_action(
            actor=actor,
            actor_role=actor_role,
            action=f"set_user_status:{status}",
            resource_type="user",
            resource_id=target_user_id,
            details=reason,
        )
        return {"user_id": target_user_id, "account_status": status, "updated_at": now}

    def assign_role(
        self,
        *,
        actor: str,
        actor_role: str,
        target_user_id: str,
        new_role: str,
        reason: str = "",
    ) -> dict[str, Any]:
        self.check_permission(actor_role, "manage_roles")
        if new_role not in (*ROLE_PERMISSIONS.keys(), "user"):
            raise ValueError(f"Rôle invalide : {new_role}")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_accounts (user_id, role, account_status, updated_at)
                VALUES (?, ?, 'active', ?)
                ON CONFLICT (user_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at
                """,
                (target_user_id, new_role, now),
            )
        self.log_action(
            actor=actor,
            actor_role=actor_role,
            action="assign_role",
            resource_type="user",
            resource_id=target_user_id,
            details=f"role={new_role}; {reason}",
        )
        return {"user_id": target_user_id, "role": new_role, "updated_at": now}

    def list_users(
        self,
        sub_store: Any,
        *,
        q: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lists users with role, status, subscription, and usage count (never private conversations/files)."""
        with self._connect() as conn:
            acc_rows = {r["user_id"]: dict(r) for r in conn.execute("SELECT * FROM admin_accounts").fetchall()}

        with sub_store._connect() as sconn:
            sub_rows = {r["user_id"]: dict(r) for r in sconn.execute("SELECT user_id, plan_id, status FROM subscriptions").fetchall()}
            ev_counts = {
                r["user_id"]: int(r["cnt"])
                for r in sconn.execute("SELECT user_id, COUNT(*) AS cnt FROM usage_events GROUP BY user_id").fetchall()
            }

        all_ids = sorted(set(acc_rows.keys()) | set(sub_rows.keys()) | set(ev_counts.keys()))
        out: list[dict[str, Any]] = []
        q_low = (q or "").strip().lower()
        for uid in all_ids:
            acc = acc_rows.get(uid, {})
            sub = sub_rows.get(uid, {})
            acc_status = acc.get("account_status", "active")
            if q_low and q_low not in uid.lower():
                continue
            if status and acc_status != status:
                continue
            out.append({
                "user_id": uid,
                "role": acc.get("role", "user"),
                "account_status": acc_status,
                "plan_id": sub.get("plan_id", "free"),
                "subscription_status": sub.get("status", "active"),
                "usage_events_count": ev_counts.get(uid, 0),
            })
        return out[offset : offset + limit]

    def set_model_enabled(
        self,
        *,
        actor: str,
        actor_role: str,
        profile_id: str,
        enabled: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        self.check_permission(actor_role, "manage_models")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_flags (profile_id, enabled, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (profile_id) DO UPDATE SET enabled = excluded.enabled, updated_by = excluded.updated_by, updated_at = excluded.updated_at
                """,
                (profile_id, 1 if enabled else 0, actor, now),
            )
        self.log_action(
            actor=actor,
            actor_role=actor_role,
            action=f"set_model_enabled:{enabled}",
            resource_type="model_profile",
            resource_id=profile_id,
            details=reason,
        )
        return {"profile_id": profile_id, "enabled": enabled, "updated_at": now}

    def list_model_flags(self) -> dict[str, bool]:
        with self._connect() as conn:
            rows = conn.execute("SELECT profile_id, enabled FROM model_flags").fetchall()
            return {r["profile_id"]: bool(r["enabled"]) for r in rows}

    def list_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM admin_audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

