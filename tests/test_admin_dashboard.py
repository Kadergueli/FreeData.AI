"""Tests for Admin Dashboard: RBAC roles, audit logs, user suspension, privacy, and model flags."""
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.admin import AdminService
from src.monetization import SubscriptionStore


def test_admin_rbac_roles_and_audit_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="adm-root-secret"))
    admin = AdminService(db_path=str(tmp_path / "admin.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    sub_store.admin_update_subscription(actor="admin", target_user_id="user:alice", plan_id="premium")
    sub_store.record_usage_event("user:alice", "chat")

    # 1. read_only_analyst can read overview, but cannot suspend users or toggle models
    admin.check_permission("read_only_analyst", "read_overview")
    with pytest.raises(HTTPException) as exc_ro:
        server.admin_set_user_status_endpoint(
            "user:alice",
            server.AdminUserStatusRequest(status="suspended", reason="Abuse"),
            actor_info=("analyst1", "read_only_analyst"),
            admin=admin,
        )
    assert exc_ro.value.status_code == 403

    # 2. support_admin can suspend user, but cannot assign roles or toggle models
    res_sup = server.admin_set_user_status_endpoint(
        "user:alice",
        server.AdminUserStatusRequest(status="suspended", reason="Billing dispute"),
        actor_info=("sup1", "support_admin"),
        admin=admin,
    )
    assert res_sup["account_status"] == "suspended"

    with pytest.raises(HTTPException) as exc_role:
        server.admin_assign_role_endpoint(
            "user:alice",
            server.AdminAssignRoleRequest(role="platform_admin"),
            actor_info=("sup1", "support_admin"),
            admin=admin,
        )
    assert exc_role.value.status_code == 403

    with pytest.raises(HTTPException) as exc_mod:
        server.admin_toggle_model_endpoint(
            "advanced_reasoning",
            server.AdminModelFlagRequest(enabled=False),
            actor_info=("sup1", "support_admin"),
            admin=admin,
        )
    assert exc_mod.value.status_code == 403

    # 3. super_admin can assign roles and toggle models; audit logs capture every action
    server.admin_assign_role_endpoint(
        "user:bob",
        server.AdminAssignRoleRequest(role="support_admin", reason="Onboarding"),
        actor_info=("root", "super_admin"),
        admin=admin,
    )
    mod_res = server.admin_toggle_model_endpoint(
        "lightweight_fast",
        server.AdminModelFlagRequest(enabled=False, reason="Maintenance"),
        actor_info=("root", "super_admin"),
        admin=admin,
    )
    assert mod_res["enabled"] is False
    assert admin.list_model_flags()["lightweight_fast"] is False

    logs = admin.list_audit_logs()
    assert len(logs) == 3
    assert {l["action"] for l in logs} == {"set_user_status:suspended", "assign_role", "set_model_enabled:False"}

    # 4. User directory never exposes private conversations or documents
    users = admin.list_users(sub_store)
    alice = next(u for u in users if u["user_id"] == "user:alice")
    assert alice["account_status"] == "suspended"
    assert alice["plan_id"] == "premium"
    assert "messages" not in alice and "conversations" not in alice

