"""Regression tests for FreeData.AI Stabilization & Quality Audit (Phases 1-6).

Covers:
- Phase 2A: Retrieval relevance (explicit document requests vs irrelevant factual queries)
- Phase 2B: Long-document truncation detection, progressive indexing, and duplicate prevention
- Phase 2D: Domain validation rejecting filename-only bypasses and mixed-domain spam
- Phase 3: Project ownership checks, invalid/cross-user project_id rejection, and project deletion cascading documents
- Phase 4: REQUIRE_SIGNED_USER_AUTH=1 blocking unsigned X-User-Id even when paired with X-Premium-Key
- Phase 6: Accurate Admin provider health categories (Connected / Configured / Degraded / Unavailable / Not configured)
"""
import base64
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.monetization import SubscriptionStore
from src.projects import ProjectStore
from src.user_documents import UserDocumentStore, chunk_document_text_with_meta, validate_document_domain_relevance


# ---------------------------------------------------------------------------
# Phase 2D — Domain Validation (filename bypass & mixed-domain noise)
# ---------------------------------------------------------------------------

def test_domain_validation_rejects_filename_only_keyword_bypass():
    # Filename contains "mil_salamat" but body is a cake recipe -> MUST be rejected
    with pytest.raises(ValueError, match="hors périmètre"):
        validate_document_domain_relevance(
            "Melanger 3 oeufs, du beurre fondu, de la vanille et cuire au four pendant 30 minutes.",
            filename="rapport_mil_salamat.txt",
        )


def test_domain_validation_rejects_mixed_domain_low_density_spam():
    # 120 words of unrelated text with only 2 scattered keywords ("prix", "projet") -> density < 1.5% -> rejected
    filler = " ".join(["football musique cinema vacances plage vacances soleil guitare"] * 15)
    text = f"Mon projet de vacances parle du prix des billets de concert. {filler}"
    with pytest.raises(ValueError, match="hors périmètre"):
        validate_document_domain_relevance(text, filename="notes.txt")


# ---------------------------------------------------------------------------
# Phase 2B — Long Documents, Non-Silent Truncation, Progressive Indexing & Dedup
# ---------------------------------------------------------------------------

def test_long_document_reports_partial_indexing_and_supports_progressive_offset(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.2] * 8 for _ in texts])

    owner_id = "user:" + "u" + "1" * 32
    paragraph = "Etude marche agricole mil Salamat N'Djamena prix 220 XAF/kg transport fret 20 XAF/kg capital 2000000 FCFA. "
    long_text = (paragraph * 60).encode("utf-8")

    # First batch capped at 3 chunks -> MUST report partial indexing & next_offset (never silent truncation)
    res1 = doc_store.ingest_document(
        owner_id,
        filename="etude_longue_salamat.txt",
        content_bytes=long_text,
        mime_type="text/plain",
        max_chunks=3,
        chunk_offset=0,
    )
    assert res1["truncated"] is True
    assert res1["indexing_status"] == "partial"
    assert res1["chunks_count"] == 3
    assert res1["total_chunks"] > 3
    assert res1["next_offset"] == 3
    assert res1["indexing_warning"] is not None
    assert res1["duplicate"] is False

    # Re-uploading identical content at offset 0 -> duplicate avoided, no extra chunks written
    res_dup = doc_store.ingest_document(
        owner_id,
        filename="etude_longue_salamat.txt",
        content_bytes=long_text,
        mime_type="text/plain",
        max_chunks=3,
        chunk_offset=0,
    )
    assert res_dup["duplicate"] is True
    assert res_dup["doc_id"] == res1["doc_id"]

    # Progressive indexing from next_offset=3 succeeds and advances coverage
    res2 = doc_store.ingest_document(
        owner_id,
        filename="etude_longue_salamat.txt",
        content_bytes=long_text,
        mime_type="text/plain",
        max_chunks=100,
        chunk_offset=res1["next_offset"],
    )
    assert res2["truncated"] is False
    assert res2["indexing_status"] == "complete"
    assert res2["coverage_pct"] == 100.0


# ---------------------------------------------------------------------------
# Phase 2A — Retrieval Relevance on Explicit Document Requests
# ---------------------------------------------------------------------------

def test_explicit_document_query_does_not_return_irrelevant_document(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    # Orthogonal Jina vectors for unrelated query
    def _fake_jina(texts):
        return [[1.0, 0.0, 0.0, 0.0] if "salamat" in t.lower() else [0.0, 1.0, 0.0, 0.0] for t in texts]

    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", _fake_jina)
    owner_id = "user:" + "u" + "2" * 32
    doc_store.ingest_document(
        owner_id,
        filename="devis_mil_salamat.txt",
        content_bytes="Devis achat mil Salamat 450 sacs a 210 XAF/kg transport 18 XAF/kg.".encode("utf-8"),
        mime_type="text/plain",
    )

    # Specific factual query mentioning "rapport" about an unrelated topic -> MUST NOT retrieve irrelevant doc
    irrelevant_hits = doc_store.retrieve_for_owner(
        owner_id,
        "Quel est le taux d'inflation du cacao en Côte d'Ivoire dans mon rapport ?",
    )
    assert irrelevant_hits == []

    # Overview query ("Résume mon devis") -> SHOULD retrieve the user's document
    overview_hits = doc_store.retrieve_for_owner(owner_id, "Résume mon devis")
    assert len(overview_hits) == 1
    assert overview_hits[0]["filename"] == "devis_mil_salamat.txt"


# ---------------------------------------------------------------------------
# Phase 3 — Project Ownership Validation & Deletion Lifecycle
# ---------------------------------------------------------------------------

def test_project_ownership_enforced_on_documents_and_cascade_on_delete(tmp_path, monkeypatch):
    proj_store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.5] * 8 for _ in texts])

    alice = "user:" + "u" + "a" * 32
    bob = "user:" + "u" + "b" * 32

    alice_proj = proj_store.create_project(alice, name="Projet Alice Mil")
    pid = alice_proj["project_id"]

    valid_b64 = base64.b64encode(
        "Contrat achat mil Salamat 200 sacs a 210 XAF/kg transport 20 XAF/kg.".encode("utf-8")
    ).decode("ascii")

    # 1. Uploading with nonexistent project_id -> HTTP 404
    with pytest.raises(HTTPException) as exc_missing:
        server.upload_user_document_endpoint(
            server.DocumentValidateRequest(
                filename="devis.txt",
                content_base64=valid_b64,
                mime_type="text/plain",
                project_id="PRJ-DOES-NOT-EXIST",
            ),
            owner_id=alice,
            x_premium_key=None,
            sub_store=sub_store,
            doc_store=doc_store,
            project_store=proj_store,
        )
    assert exc_missing.value.status_code == 404

    # 2. Bob attempting to attach a document to Alice's project_id -> HTTP 404
    with pytest.raises(HTTPException) as exc_cross:
        server.upload_user_document_endpoint(
            server.DocumentValidateRequest(
                filename="devis_bob.txt",
                content_base64=valid_b64,
                mime_type="text/plain",
                project_id=pid,
            ),
            owner_id=bob,
            x_premium_key=None,
            sub_store=sub_store,
            doc_store=doc_store,
            project_store=proj_store,
        )
    assert exc_cross.value.status_code == 404

    # 3. Bob attempting to list documents of Alice's project -> HTTP 404
    with pytest.raises(HTTPException) as exc_list:
        server.list_user_documents_endpoint(
            project_id=pid,
            owner_id=bob,
            doc_store=doc_store,
            project_store=proj_store,
        )
    assert exc_list.value.status_code == 404

    # 4. Alice attaches document to her own project -> succeeds
    up = server.upload_user_document_endpoint(
        server.DocumentValidateRequest(
            filename="devis_alice.txt",
            content_base64=valid_b64,
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
    assert len(doc_store.list_documents(alice, project_id=pid)) == 1

    # 5. Deleting Alice's project cascades and removes attached documents (zero orphans)
    del_res = server.delete_project_endpoint(
        pid,
        confirm=True,
        owner_id=alice,
        store=proj_store,
        doc_store=doc_store,
    )
    assert del_res["deleted"] is True
    assert del_res["deleted_documents"] == 1
    assert doc_store.list_documents(alice, project_id=pid) == []


# ---------------------------------------------------------------------------
# Phase 4 — REQUIRE_SIGNED_USER_AUTH Blocks Unsigned X-User-Id Spoofing
# ---------------------------------------------------------------------------

def test_require_signed_user_auth_blocks_unsigned_x_user_id_even_with_premium_key(monkeypatch):
    monkeypatch.setenv("REQUIRE_SIGNED_USER_AUTH", "1")
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-secret-key-123456"))

    spoofed_uid = "u" + "f" * 32
    # Unsigned X-User-Id alone -> rejected (None)
    assert server._resolve_owner_id_optional(x_user_id=spoofed_uid, x_premium_key=None, authorization=None) is None

    # Unsigned X-User-Id + valid X-Premium-Key -> MUST NOT resolve to `user:<spoofed_uid>`
    resolved = server._resolve_owner_id_optional(
        x_user_id=spoofed_uid,
        x_premium_key="pro-secret-key-123456",
        authorization=None,
    )
    assert resolved is not None
    assert resolved.startswith("key:")
    assert spoofed_uid not in resolved


# ---------------------------------------------------------------------------
# Phase 6 — Accurate Provider Health Status Reporting (No Secrets Leaked)
# ---------------------------------------------------------------------------

def test_probe_providers_health_reports_explicit_categories_and_handles_failures(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("EMBED_API_KEY", "")
    monkeypatch.setattr(
        server,
        "settings",
        replace(server.settings, llm_api_key="gsk_super_secret_should_never_leak", embed_api_key=""),
    )

    # 1. Without live_probe: Configured vs Not configured
    snap = server._probe_providers_health({"forecast_df": pd.DataFrame([{"a": 1}]), "agent": object()}, live_probe=False)
    assert snap["groq_status"] == "Configured"
    assert snap["jina_status"] == "Not configured"
    assert snap["supabase_status"] == "Not configured"
    assert snap["ml_engine_status"] == "Connected"
    assert snap["rag_engine_status"] == "Connected"
    assert "gsk_super_secret_should_never_leak" not in str(snap)

    # 2. With live_probe failing (network timeout / 429) -> Degraded / Unavailable, no crash, no secret leak
    class _RateLimitedResp:
        status_code = 429

    monkeypatch.setattr(server.requests, "get", lambda *a, **k: _RateLimitedResp())
    snap_live = server._probe_providers_health({"forecast_df": pd.DataFrame(), "agent": object()}, live_probe=True)
    assert snap_live["groq_status"] == "Degraded"
    assert snap_live["ml_engine_status"] == "Unavailable"
    assert "gsk_super_secret_should_never_leak" not in str(snap_live)
