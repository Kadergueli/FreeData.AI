"""Automated Privacy & Data Protection Tests (Section 8)."""
import logging
import sqlite3
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.ai_agent import FreeDataAIAgent
from src.projects import ProjectStore
from src.security import redact_secrets
from src.user_documents import UserDocumentStore


def test_deleted_document_removes_all_vectors_and_never_appears_in_rag_retrieval(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.5] * 8 for _ in texts])

    owner = "user:" + "u" + "p" * 32
    up = doc_store.ingest_document(
        owner,
        filename="devis_confidentiel.txt",
        content_bytes="Devis achat mil Salamat 500 sacs a 210 XAF/kg transport 18 XAF/kg.".encode("utf-8"),
        mime_type="text/plain",
    )
    doc_id = up["doc_id"]

    # Confirm chunk & embedding exist before deletion
    assert len(doc_store.retrieve_for_owner(owner, "Résume mon devis mil Salamat")) == 1
    with sqlite3.connect(str(doc_store.db_path)) as conn:
        cnt_before = conn.execute("SELECT COUNT(*) FROM user_document_chunks WHERE doc_id = ?", (doc_id,)).fetchone()[0]
    assert cnt_before >= 1

    # Delete document -> both metadata and all chunk vectors are permanently removed
    assert doc_store.delete_document(owner, doc_id) is True
    with sqlite3.connect(str(doc_store.db_path)) as conn:
        cnt_after = conn.execute("SELECT COUNT(*) FROM user_document_chunks WHERE doc_id = ?", (doc_id,)).fetchone()[0]
    assert cnt_after == 0
    assert doc_store.retrieve_for_owner(owner, "Résume mon devis mil Salamat") == []


def test_single_generated_study_deletion_respects_ownership(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    alice = "user:" + "u" + "a" * 32
    bob = "user:" + "u" + "b" * 32

    proj = store.create_project(alice, name="Projet Etude Alice")
    pid = proj["project_id"]
    ver = store.create_study_version(
        alice,
        pid,
        study_id=None,
        dossier={"commodity": "Millet", "commodity_fr": "Mil", "origin_province": "Salamat", "dest_province": "N'Djamena"},
        generation_params={"commodity": "Millet"},
        pdf_bytes=b"%PDF-1.4\n%%EOF",
    )
    study_id = ver["study_id"]

    # Bob cannot delete Alice's generated study -> HTTP 404
    with pytest.raises(HTTPException) as exc_bob:
        server.delete_study_endpoint(pid, study_id, confirm=True, owner_id=bob, store=store)
    assert exc_bob.value.status_code == 404

    # Alice deletes her single study cleanly (without deleting her project)
    res = server.delete_study_endpoint(pid, study_id, confirm=True, owner_id=alice, store=store)
    assert res["deleted"] is True
    full_proj = store.get_project(alice, pid)
    assert full_proj["studies"] == []


def test_secret_redaction_and_provider_error_logs_never_leak_credentials(caplog, monkeypatch):
    raw_pg = "Connection failed: postgresql://postgres:SuperSecretPass123@aws-0-eu.pooler.supabase.com:6543/postgres"
    raw_bearer = "HTTP 401 Authorization: Bearer eyJhbGciOi.supersecrettoken123"
    raw_key = "Provider error with gsk_1234567890abcdef and jina_abcdef123456"

    assert "SuperSecretPass123" not in redact_secrets(raw_pg)
    assert "[REDACTED]" in redact_secrets(raw_pg)
    assert "supersecrettoken123" not in redact_secrets(raw_bearer)
    assert "gsk_1234567890abcdef" not in redact_secrets(raw_key)
    assert "jina_abcdef123456" not in redact_secrets(raw_key)

    # Verify Groq failure log redacts secrets
    from src import ai_agent
    fc = pd.DataFrame([
        {
            "source": "WFP",
            "province": "Salamat",
            "market_name": "Am Timan",
            "commodity_std": "Millet",
            "last_observed_month": "2026-10",
            "value": 210.0,
            "forecast_month": "2026-11",
            "forecast_t1": 225.0,
            "ci_low_80": 195.0,
            "ci_high_80": 250.0,
            "hist_mae": 12.0,
        }
    ])
    agent = FreeDataAIAgent(fc, fc, pd.DataFrame())
    monkeypatch.setattr(ai_agent, "settings", replace(ai_agent.settings, llm_api_key="gsk_live_secret_999999"))
    monkeypatch.setattr(
        ai_agent.requests,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Timeout using gsk_live_secret_999999")),
    )
    with caplog.at_level(logging.WARNING):
        agent.answer("Quel est le prix du mil au Salamat ?", tier="premium")
    assert "gsk_live_secret_999999" not in caplog.text
    assert "[REDACTED_KEY]" in caplog.text

