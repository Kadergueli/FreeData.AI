"""Tests for ChatGPT-grade User Space: profile update, password change, account deletion, and cloud conversation sync."""
import pytest
from fastapi import HTTPException

from api import server
from src.auth import AuthStore
from src.conversations import ConversationStore
from src.projects.store import ProjectStore


def test_profile_update_change_password_and_delete_account_cascade(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "user-space-secret-key-for-tests-12345")
    auth_store = AuthStore(db_path=str(tmp_path / "auth.db"))
    conv_store = ConversationStore(db_path=str(tmp_path / "conv.db"))
    proj_store = ProjectStore(db_path=str(tmp_path / "proj.db"), artifacts_dir=str(tmp_path / "art"))
    monkeypatch.setattr(server, "_AUTH_STORE", auth_store)

    reg = server.auth_register_endpoint(
        server.AuthRegisterRequest(email="kader@freedata.td", password="OldPassword123!", display_name="Kader"),
        auth_store=auth_store,
    )
    bearer = f"Bearer {reg['token']}"
    owner_id = f"user:{reg['user']['user_id']}"

    # Update profile
    upd = server.auth_update_profile_endpoint(
        server.AuthProfileUpdateRequest(display_name="Kader — Coopérative Lac"),
        authorization=bearer,
        auth_store=auth_store,
    )
    assert upd["user"]["display_name"] == "Kader — Coopérative Lac"

    # Change password with wrong old password -> 401
    with pytest.raises(HTTPException) as exc_wrong:
        server.auth_change_password_endpoint(
            server.AuthChangePasswordRequest(current_password="WrongPassword!", new_password="NewPassword456!"),
            authorization=bearer,
            auth_store=auth_store,
        )
    assert exc_wrong.value.status_code == 401

    # Change password with correct old password -> succeeds
    ch = server.auth_change_password_endpoint(
        server.AuthChangePasswordRequest(current_password="OldPassword123!", new_password="NewPassword456!"),
        authorization=bearer,
        auth_store=auth_store,
    )
    assert ch["updated"] is True

    # Old password rejected, new password works
    with pytest.raises(HTTPException):
        server.auth_login_endpoint(
            server.AuthLoginRequest(email="kader@freedata.td", password="OldPassword123!"),
            auth_store=auth_store,
        )
    login2 = server.auth_login_endpoint(
        server.AuthLoginRequest(email="kader@freedata.td", password="NewPassword456!"),
        auth_store=auth_store,
    )
    bearer2 = f"Bearer {login2['token']}"

    # Seed conversation & project, then delete account
    conv_store.upsert_conversation(
        owner_id,
        {
            "id": "conv-1",
            "title": "Mil Salamat",
            "messages": [{"id": "m1", "isUser": True, "text": "Prix du mil ?"}],
            "createdAt": "2026-11-19T10:00:00Z",
            "updatedAt": "2026-11-19T10:00:00Z",
        },
    )
    proj_store.create_project(owner_id, name="Projet Test")

    deleted = server.auth_delete_account_endpoint(
        server.AuthDeleteAccountRequest(password="NewPassword456!"),
        authorization=bearer2,
        auth_store=auth_store,
        conv_store=conv_store,
        project_store=proj_store,
    )
    assert deleted["deleted"] is True
    assert conv_store.list_conversations(owner_id) == []
    assert proj_store.list_projects(owner_id, include_archived=True) == []
    assert auth_store.get_user(reg["user"]["user_id"]) is None


def test_cloud_conversation_sync_merges_by_timestamp_and_isolates_users(tmp_path):
    conv_store = ConversationStore(db_path=str(tmp_path / "conv.db"))
    owner_a = "user:u" + "a" * 32
    owner_b = "user:u" + "b" * 32

    # User A saves a thread on phone (newer timestamp)
    server.upsert_cloud_conversation_endpoint(
        "c1",
        server.CloudConversationPayload(
            id="c1",
            title="Analyse Mil (Phone)",
            isSavedInLibrary=True,
            createdAt="2026-11-19T08:00:00Z",
            updatedAt="2026-11-19T10:00:00Z",
            messages=[{"id": "1", "isUser": True, "text": "Mil ?"}, {"id": "2", "isUser": False, "text": "220 XAF"}],
        ),
        owner_id=owner_a,
        conv_store=conv_store,
    )

    # User A syncs from PC with older version of c1 + new thread c2
    merged = server.sync_cloud_conversations_endpoint(
        server.CloudConversationSyncRequest(
            conversations=[
                {
                    "id": "c1",
                    "title": "Analyse Mil (Old PC)",
                    "createdAt": "2026-11-19T08:00:00Z",
                    "updatedAt": "2026-11-19T09:00:00Z",
                    "messages": [{"id": "1", "isUser": True, "text": "Mil ?"}],
                },
                {
                    "id": "c2",
                    "title": "Sorgho Moundou",
                    "createdAt": "2026-11-19T11:00:00Z",
                    "updatedAt": "2026-11-19T11:00:00Z",
                    "messages": [{"id": "3", "isUser": True, "text": "Sorgho ?"}],
                },
            ]
        ),
        owner_id=owner_a,
        conv_store=conv_store,
    )
    assert merged["count"] == 2
    by_id = {c["id"]: c for c in merged["conversations"]}
    # Newer phone version preserved over stale PC version
    assert by_id["c1"]["title"] == "Analyse Mil (Phone)"
    assert by_id["c1"]["isSavedInLibrary"] is True
    assert by_id["c2"]["title"] == "Sorgho Moundou"

    # Strict isolation: User B sees zero conversations
    b_list = server.list_cloud_conversations_endpoint(include_deleted=True, owner_id=owner_b, conv_store=conv_store)
    assert b_list["count"] == 0

