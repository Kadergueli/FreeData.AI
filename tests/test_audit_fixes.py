"""Regression tests for P0 audit fixes: /admin/me, owner_id unification, read-only /billing/me, PRO project studies & 404."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server
from src.monetization import SubscriptionStore
from src.projects.store import ProjectStore


def test_admin_me_endpoint_returns_actor_role_and_permissions():
    res = server.admin_me_endpoint(actor_info=("analyst1", "read_only_analyst"))
    assert res["actor"] == "analyst1"
    assert res["role"] == "read_only_analyst"
    assert res["permissions"] == ["read_overview"]

    res_super = server.admin_me_endpoint(actor_info=("root_admin", "super_admin"))
    assert "manage_users" in res_super["permissions"]
    assert "manage_system" in res_super["permissions"]


def test_owner_id_isolates_pro_users_and_syncs_billing_quotas(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))

    uid_a = "u" + "a" * 32
    uid_b = "u" + "b" * 32
    owner_a = server._require_project_owner(x_user_id=uid_a, x_premium_key="pro-key-1234567890", authorization=None)
    owner_b = server._require_project_owner(x_user_id=uid_b, x_premium_key="pro-key-1234567890", authorization=None)
    assert owner_a == f"user:{uid_a}"
    assert owner_b == f"user:{uid_b}"
    assert owner_a != owner_b

    # Simulate chat & PDF consumption via unified helper, then verify /billing/me shows exact counts
    server._consume_user_quota(owner_a, "pro-key-1234567890", "daily_chat", sub_store, "limit")
    server._consume_user_quota(owner_a, "pro-key-1234567890", "monthly_pdf", sub_store, "limit")

    summary_a = server.get_my_billing_endpoint(owner_id=owner_a, x_premium_key="pro-key-1234567890", sub_store=sub_store)
    assert summary_a["subscription"]["effective_plan_id"] == "premium"
    assert summary_a["quotas"]["daily_chat"]["used"] == 1
    assert summary_a["quotas"]["daily_chat"]["limit"] == 500
    assert summary_a["quotas"]["monthly_pdf"]["used"] == 1
    assert summary_a["quotas"]["monthly_pdf"]["limit"] == 50

    # User B remains completely isolated at 0
    summary_b = server.get_my_billing_endpoint(owner_id=owner_b, x_premium_key="pro-key-1234567890", sub_store=sub_store)
    assert summary_b["quotas"]["daily_chat"]["used"] == 0


def test_billing_me_is_read_only_and_respects_admin_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))

    out = server.get_my_billing_endpoint(
        owner_id="user:active_free",
        x_premium_key="pro-key-1234567890",
        sub_store=sub_store,
    )
    assert out["subscription"]["effective_plan_id"] == "premium"
    assert out["quotas"]["daily_chat"]["limit"] == 500
    assert sub_store.get_subscription("user:active_free")["plan_id"] == "free"

    sub_store.admin_update_subscription(
        actor="admin",
        target_user_id="user:cancelled",
        plan_id="premium",
        status="cancelled",
        reason="Revoked by admin",
    )
    out_revoked = server.get_my_billing_endpoint(
        owner_id="user:cancelled",
        x_premium_key="pro-key-1234567890",
        sub_store=sub_store,
    )
    assert out_revoked["subscription"]["status"] == "cancelled"
    assert out_revoked["subscription"]["effective_plan_id"] == "free"


def test_project_study_requires_premium_key_and_404_on_unknown_study_id(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    store = ProjectStore(db_path=str(tmp_path / "proj.db"), artifacts_dir=str(tmp_path / "art"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    proj = store.create_project("user:bob", name="Mon Projet")

    monkeypatch.setattr(
        server,
        "_build_study_dossier_or_404",
        lambda req, st: {"commodity": "Millet", "commodity_fr": "Mil", "origin_province": "Lac", "validation": {"can_deliver_pdf": True}},
    )
    monkeypatch.setattr(server, "render_market_study_pdf", lambda d: b"%PDF-1.4 mock")

    req = server.ProjectStudyCreateRequest(
        commodity="Millet",
        origin_province="Lac",
        capital_xaf=500000,
        study_id="FD-DOES-NOT-EXIST",
    )
    # Without X-Premium-Key -> 403
    with pytest.raises(HTTPException) as exc_403:
        server.create_project_study_version_endpoint(
            proj["project_id"],
            req,
            state={},
            owner_id="user:bob",
            x_premium_key=None,
            store=store,
            sub_store=sub_store,
        )
    assert exc_403.value.status_code == 403

    # With valid X-Premium-Key and unknown study_id -> 404
    with pytest.raises(HTTPException) as exc_404:
        server.create_project_study_version_endpoint(
            proj["project_id"],
            req,
            state={},
            owner_id="user:bob",
            x_premium_key="pro-key-1234567890",
            store=store,
            sub_store=sub_store,
        )
    assert exc_404.value.status_code == 404


def test_admin_suspension_blocks_jwt_and_login_and_lists_email(tmp_path, monkeypatch):
    from src.admin import AdminService
    from src.auth import AuthStore

    monkeypatch.setenv("AUTH_SECRET", "super-secret-auth-key-for-tests-123456")
    auth_store = AuthStore(db_path=str(tmp_path / "auth.db"))
    admin_svc = AdminService(db_path=str(tmp_path / "admin.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr(server, "_AUTH_STORE", auth_store)
    monkeypatch.setattr(server, "_ADMIN_SERVICE", admin_svc)

    reg = server.auth_register_endpoint(
        server.AuthRegisterRequest(email="suspended@freedata.td", password="StrongPassword123!", display_name="Kader"),
        auth_store=auth_store,
    )
    uid = reg["user"]["user_id"]
    owner_id = f"user:{uid}"
    bearer = f"Bearer {reg['token']}"

    # Admin user list shows email and supports both q and search
    listed = server.admin_list_users_endpoint(
        q=None,
        search="suspended@freedata.td",
        status=None,
        limit=50,
        offset=0,
        actor_info=("root", "super_admin"),
        admin=admin_svc,
        sub_store=sub_store,
        auth_store=auth_store,
    )
    assert len(listed["users"]) == 1
    assert listed["users"][0]["email"] == "suspended@freedata.td"
    assert listed["users"][0]["status"] == "active"

    # Admin suspends the user
    server.admin_set_user_status_endpoint(
        owner_id,
        server.AdminUserStatusRequest(status="suspended", reason="Test suspension"),
        actor_info=("root", "super_admin"),
        admin=admin_svc,
        auth_store=auth_store,
    )

    # Active JWT is immediately blocked with 403
    with pytest.raises(HTTPException) as exc_jwt:
        server._require_project_owner(x_user_id=None, x_premium_key=None, authorization=bearer)
    assert exc_jwt.value.status_code == 403

    # Re-login is also blocked
    with pytest.raises(HTTPException) as exc_login:
        server.auth_login_endpoint(
            server.AuthLoginRequest(email="suspended@freedata.td", password="StrongPassword123!"),
            auth_store=auth_store,
        )
    assert exc_login.value.status_code == 401


def test_max_projects_limit_and_privacy_deletion_purges_conversations(tmp_path):
    from src.conversations import ConversationStore

    store = ProjectStore(db_path=str(tmp_path / "proj.db"), artifacts_dir=str(tmp_path / "art"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    conv_store = ConversationStore(db_path=str(tmp_path / "conv.db"))
    owner_id = "user:" + "u" + "c" * 32

    # Free plan allows up to 5 active projects
    for i in range(5):
        server.create_project_endpoint(
            server.ProjectCreateRequest(name=f"Projet {i+1}"),
            owner_id=owner_id,
            x_premium_key=None,
            store=store,
            sub_store=sub_store,
        )

    # 6th active project -> 429
    with pytest.raises(HTTPException) as exc_limit:
        server.create_project_endpoint(
            server.ProjectCreateRequest(name="Projet 6"),
            owner_id=owner_id,
            x_premium_key=None,
            store=store,
            sub_store=sub_store,
        )
    assert exc_limit.value.status_code == 429

    # Privacy deletion purges both projects and cloud conversations
    conv_store.upsert_conversation(
        owner_id,
        {"id": "conv-1", "title": "Test", "messages": [{"role": "user", "text": "Bonjour"}]},
    )
    assert len(conv_store.list_conversations(owner_id)) == 1
    out = server.delete_my_data_endpoint(confirm=True, owner_id=owner_id, store=store, conv_store=conv_store)
    assert out["deleted_projects"] == 5
    assert out["deleted_conversations"] == 1
    assert len(conv_store.list_conversations(owner_id)) == 0

