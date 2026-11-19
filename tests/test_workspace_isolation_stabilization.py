"""Multi-Tenant Workspace, Projects, Documents & Conversations Isolation Regression Tests."""
import base64
import sqlite3

import pytest
from fastapi import HTTPException

from api import server
from src.conversations import ConversationStore
from src.monetization import SubscriptionStore
from src.projects import ProjectStore
from src.user_documents import UserDocumentStore


def test_cross_tenant_isolation_projects_conversations_and_documents(tmp_path, monkeypatch):
    proj_store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    conv_store = ConversationStore(db_path=str(tmp_path / "convs.db"))
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.5] * 8 for _ in texts])

    alice = "user:" + "u" + "a" * 32
    bob = "user:" + "u" + "b" * 32

    # 1. Alice creates a project, uploads a document, and saves a project conversation
    p_alice = proj_store.create_project(alice, name="Dossier Mil Alice")
    pid = p_alice["project_id"]

    doc_b64 = base64.b64encode(
        "Contrat achat mil Salamat 300 sacs a 215 XAF/kg transport 20 XAF/kg.".encode("utf-8")
    ).decode("ascii")
    up = server.upload_user_document_endpoint(
        server.DocumentValidateRequest(
            filename="contrat_alice.txt",
            content_base64=doc_b64,
            mime_type="text/plain",
            project_id=pid,
        ),
        owner_id=alice,
        x_premium_key=None,
        sub_store=sub_store,
        doc_store=doc_store,
        project_store=proj_store,
    )
    assert up["project_id"] == pid

    saved_conv = server.upsert_cloud_conversation_endpoint(
        "conv-alice-1",
        server.CloudConversationPayload(
            id="conv-alice-1",
            title="Analyse Mil",
            projectId=pid,
            projectName="Dossier Mil Alice",
            messages=[
                {"id": "m1", "role": "user", "text": "Prix du mil au Salamat ?"},
                {"id": "m2", "role": "assistant", "text": "215 XAF/kg observé."},
            ],
        ),
        owner_id=alice,
        conv_store=conv_store,
        project_store=proj_store,
    )
    assert saved_conv["projectId"] == pid
    assert [m["id"] for m in saved_conv["messages"]] == ["m1", "m2"]

    # 2. Bob CANNOT read, update, or delete Alice's project
    with pytest.raises(HTTPException) as exc_get:
        server.get_project_endpoint(pid, owner_id=bob, store=proj_store)
    assert exc_get.value.status_code == 404

    with pytest.raises(HTTPException) as exc_del_p:
        server.delete_project_endpoint(
            pid,
            confirm=True,
            owner_id=bob,
            store=proj_store,
            doc_store=doc_store,
            conv_store=conv_store,
        )
    assert exc_del_p.value.status_code == 404

    # 3. Bob CANNOT attach his conversation to Alice's projectId via PUT
    with pytest.raises(HTTPException) as exc_conv_hijack:
        server.upsert_cloud_conversation_endpoint(
            "conv-bob-hijack",
            server.CloudConversationPayload(
                id="conv-bob-hijack",
                title="Hijack",
                projectId=pid,
                messages=[{"id": "b1", "role": "user", "text": "Test"}],
            ),
            owner_id=bob,
            conv_store=conv_store,
            project_store=proj_store,
        )
    assert exc_conv_hijack.value.status_code == 404

    # 4. Bob submitting Alice's projectId in /conversations/sync has projectId stripped (detached)
    synced = server.sync_cloud_conversations_endpoint(
        server.CloudConversationSyncRequest(
            conversations=[
                {
                    "id": "conv-bob-sync",
                    "title": "Sync Test",
                    "projectId": pid,
                    "projectName": "Dossier Mil Alice",
                    "messages": [{"id": "b2", "role": "user", "text": "Bonjour"}],
                }
            ]
        ),
        owner_id=bob,
        conv_store=conv_store,
        project_store=proj_store,
    )
    assert synced["count"] == 1
    assert synced["conversations"][0]["projectId"] is None
    assert synced["conversations"][0]["projectName"] is None

    # 5. Bob CANNOT delete Alice's conversation or document
    with pytest.raises(HTTPException) as exc_del_c:
        server.delete_cloud_conversation_endpoint("conv-alice-1", owner_id=bob, conv_store=conv_store)
    assert exc_del_c.value.status_code == 404

    with pytest.raises(HTTPException) as exc_del_d:
        server.delete_user_document_endpoint(up["doc_id"], owner_id=bob, doc_store=doc_store)
    assert exc_del_d.value.status_code == 404

    # 6. Alice deletes her project -> documents deleted, conversations safely detached (history preserved!)
    del_res = server.delete_project_endpoint(
        pid,
        confirm=True,
        owner_id=alice,
        store=proj_store,
        doc_store=doc_store,
        conv_store=conv_store,
    )
    assert del_res["deleted"] is True
    assert del_res["deleted_documents"] == 1
    assert del_res["detached_conversations"] == 1

    # Verify conversation history preserved with projectId == None (no orphan reference)
    alice_convs = conv_store.list_conversations(alice)
    assert len(alice_convs) == 1
    assert alice_convs[0]["projectId"] is None
    assert len(alice_convs[0]["messages"]) == 2


def test_unauthenticated_workspace_request_is_rejected():
    with pytest.raises(HTTPException) as exc:
        server._require_project_owner(x_user_id=None, x_premium_key=None, authorization=None)
    assert exc.value.status_code == 401


def test_database_composite_indexes_exist_for_project_scoped_queries(tmp_path):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    conv_store = ConversationStore(db_path=str(tmp_path / "convs.db"))

    with sqlite3.connect(str(doc_store.db_path)) as conn:
        doc_indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_user_documents_owner_project" in doc_indexes
    assert "idx_user_doc_chunks_owner_project" in doc_indexes

    with sqlite3.connect(str(conv_store.db_path)) as conn:
        conv_indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_user_conversations_owner_project" in conv_indexes

