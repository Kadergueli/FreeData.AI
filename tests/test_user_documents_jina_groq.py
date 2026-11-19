"""Tests for Private User Document Vault: Jina Embeddings v3 indexing, strict owner isolation, and Groq interpretation."""
import base64
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.ai_agent import FreeDataAIAgent
from src.monetization import SubscriptionStore
from src.user_documents import UserDocumentStore


def test_user_document_vault_jina_indexing_and_strict_owner_isolation(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))

    # Simulate Jina Embeddings v3 returning 1024-d semantic vectors
    jina_calls = []

    def _fake_jina(texts: list[str]):
        jina_calls.append(texts)
        return [[0.5 if "coopérative" in t.lower() else 0.1] * 8 for t in texts]

    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", _fake_jina)

    owner_alice = "user:" + "u" + "a" * 32
    owner_bob = "user:" + "u" + "b" * 32

    pdf_bytes = b"%PDF-1.4\n1 0 obj\n(Rapport interne Cooperative Salamat : stock 450 sacs de mil a 18500 XAF)\nendobj\n%%EOF"
    b64_pdf = base64.b64encode(pdf_bytes).decode("ascii")

    res = server.upload_user_document_endpoint(
        server.DocumentValidateRequest(
            filename="rapport_salamat.pdf",
            content_base64=b64_pdf,
            mime_type="application/pdf",
        ),
        owner_id=owner_alice,
        x_premium_key=None,
        sub_store=sub_store,
        doc_store=doc_store,
    )
    assert res["filename"] == "rapport_salamat.pdf"
    assert res["embedding_provider"] == "jina-embeddings-v3"
    assert res["chunks_count"] >= 1
    assert len(jina_calls) == 1

    # Alice sees her document and can retrieve chunks via Jina semantic search
    alice_docs = server.list_user_documents_endpoint(owner_id=owner_alice, doc_store=doc_store)
    assert alice_docs["count"] == 1
    alice_hits = doc_store.retrieve_for_owner(owner_alice, "Combien de sacs dans la coopérative ?")
    assert len(alice_hits) == 1
    assert "450 sacs" in alice_hits[0]["content"]
    assert alice_hits[0]["metadata"]["owner_id"] == owner_alice

    # Bob is strictly isolated: sees 0 documents, 0 chunks, and cannot delete Alice's document
    bob_docs = server.list_user_documents_endpoint(owner_id=owner_bob, doc_store=doc_store)
    assert bob_docs["count"] == 0
    assert doc_store.retrieve_for_owner(owner_bob, "coopérative Salamat 450 sacs") == []
    with pytest.raises(HTTPException) as exc_del:
        server.delete_user_document_endpoint(res["doc_id"], owner_id=owner_bob, doc_store=doc_store)
    assert exc_del.value.status_code == 404

    # Alice deletes her document -> removed cleanly
    del_ok = server.delete_user_document_endpoint(res["doc_id"], owner_id=owner_alice, doc_store=doc_store)
    assert del_ok["deleted"] is True
    assert server.list_user_documents_endpoint(owner_id=owner_alice, doc_store=doc_store)["count"] == 0


def test_chat_passes_jina_retrieved_chunks_to_groq_for_interpretation(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.25] * 8 for _ in texts])
    monkeypatch.setattr(server, "settings", replace(server.settings, llm_api_key="gsk_test_groq_key"))

    owner_id = "user:" + "u" + "d" * 32
    doc_store.ingest_document(
        owner_id,
        filename="contrat_transport.txt",
        content_bytes="Contrat transporteur Abéché-N'Djamena : tarif négocié 18 XAF/kg pour 120 tonnes.".encode("utf-8"),
        mime_type="text/plain",
    )

    fc_df = pd.DataFrame([
        {
            "source": "WFP",
            "province": "N'Djamena",
            "market_name": "N'Djamena",
            "commodity_std": "Millet",
            "last_observed_month": "2026-10",
            "value": 240.0,
            "forecast_month": "2026-11",
            "forecast_t1": 255.0,
            "ci_low_80": 220.0,
            "ci_high_80": 280.0,
            "hist_mae": 15.0,
        }
    ])
    cp_df = pd.DataFrame([
        {
            "province": "N'Djamena",
            "commodity_std": "Millet",
            "credit_score": 72.0,
            "grade": "A",
            "ltv_ratio": 0.70,
            "cv_pct": 14.0,
            "max_drawdown_pct": -18.0,
            "obs_months": 36,
            "policy_recommendation": "Favorable",
        }
    ])
    agent = FreeDataAIAgent(fc_df, fc_df, cp_df)

    groq_captured = {}

    def _fake_groq_synth(q, facts, chunks, history=None, client_state=None, business_plan_blueprint=None):
        groq_captured["query"] = q
        groq_captured["facts"] = facts
        groq_captured["chunks"] = chunks
        return "Synthèse Groq : Selon votre contrat privé (contrat_transport.txt), le tarif négocié est de 18 XAF/kg pour 120 tonnes."

    monkeypatch.setattr(agent, "_synthesize_with_llm", _fake_groq_synth)

    private_chunks = doc_store.retrieve_for_owner(owner_id, "Analyse mon contrat de transport")
    ans = agent.answer(
        "Analyse mon contrat de transport et résume le tarif négocié.",
        tier="free",
        private_chunks=private_chunks,
    )
    assert ans["intent"] == "private_document_analysis"
    assert "18 XAF/kg" in ans["reply"]
    assert groq_captured["chunks"][0]["filename"] == "contrat_transport.txt"
    assert ans["sources"][0]["title"] == "contrat_transport.txt (Document privé)"


def test_out_of_domain_and_malicious_documents_are_rejected(tmp_path):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    sub_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    owner_id = "user:" + "u" + "e" * 32

    # 1. Completely off-topic document (recipe / horoscope) -> HTTP 422 rejected
    off_topic_b64 = base64.b64encode("Recette de gateau au chocolat avec 3 oeufs et de la vanille.".encode("utf-8")).decode("ascii")
    with pytest.raises(HTTPException) as exc_off:
        server.upload_user_document_endpoint(
            server.DocumentValidateRequest(
                filename="recette_gateau.txt",
                content_base64=off_topic_b64,
                mime_type="text/plain",
            ),
            owner_id=owner_id,
            x_premium_key=None,
            sub_store=sub_store,
            doc_store=doc_store,
        )
    assert exc_off.value.status_code == 422
    assert "hors périmètre" in str(exc_off.value.detail).lower()

    # 2. Malicious / abusive document -> HTTP 422 rejected
    malicious_b64 = base64.b64encode("Rapport marche mil avec payload ransomware et reverse shell.".encode("utf-8")).decode("ascii")
    with pytest.raises(HTTPException) as exc_mal:
        server.upload_user_document_endpoint(
            server.DocumentValidateRequest(
                filename="virus.txt",
                content_base64=malicious_b64,
                mime_type="text/plain",
            ),
            owner_id=owner_id,
            x_premium_key=None,
            sub_store=sub_store,
            doc_store=doc_store,
        )
    assert exc_mal.value.status_code == 422
    assert "charte de sécurité" in str(exc_mal.value.detail).lower()

    # Nothing was stored in DB
    assert doc_store.list_documents(owner_id) == []


def test_valid_domain_document_extracts_params_and_crosses_freedata_calculations(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", lambda texts: [[0.3333333] * 8 for _ in texts])

    owner_id = "user:" + "u" + "f" * 32
    ingested = doc_store.ingest_document(
        owner_id,
        filename="etude_mil_salamat.txt",
        content_bytes=(
            "Projet negoce mil entre Salamat et N'Djamena avec un capital de 2 000 000 FCFA "
            "et un tarif de transport de 20 XAF/kg."
        ).encode("utf-8"),
        mime_type="text/plain",
    )
    assert ingested["domain_valid"] is True
    assert ingested["raw_binary_stored"] is False
    params = ingested["extracted_business_params"]
    assert params["commodity"] == "Millet"
    assert params["capital_xaf"] == 2000000.0
    assert params["transport_cost_per_kg"] == 20.0

    # Cross-check with FreeDataAIAgent deterministic calculations (no LLM key needed to verify facts)
    fc_df = pd.DataFrame([
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
        },
        {
            "source": "WFP",
            "province": "N'Djamena",
            "market_name": "N'Djamena",
            "commodity_std": "Millet",
            "last_observed_month": "2026-10",
            "value": 290.0,
            "forecast_month": "2026-11",
            "forecast_t1": 305.0,
            "ci_low_80": 270.0,
            "ci_high_80": 330.0,
            "hist_mae": 14.0,
        },
    ])
    cp_df = pd.DataFrame([
        {
            "province": "Salamat",
            "commodity_std": "Millet",
            "credit_score": 76.0,
            "grade": "A",
            "ltv_ratio": 0.72,
            "cv_pct": 12.0,
            "max_drawdown_pct": -15.0,
            "obs_months": 36,
            "policy_recommendation": "Favorable",
        }
    ])
    monkeypatch.setattr("src.ai_agent.settings", replace(server.settings, llm_api_key=""))
    agent = FreeDataAIAgent(fc_df, fc_df, cp_df)
    chunks = doc_store.retrieve_for_owner(owner_id, "Analyse mon document")
    ans = agent.answer("Analyse mon document et donne moi les benchmarks", tier="free", private_chunks=chunks)
    assert ans["intent"] == "private_document_analysis"
    assert "Benchmark marché FreeData.AI" in ans["reply"]
    assert "Credit Passport" in ans["reply"]
    assert "210.0 XAF/kg" in ans["reply"]


def test_p1_smalltalk_and_unrelated_query_skip_private_doc_injection(tmp_path, monkeypatch):
    doc_store = UserDocumentStore(db_path=str(tmp_path / "docs.db"))
    # Simulate orthogonal Jina vectors (cosine = 0.0 for unrelated query)
    def _fake_jina(texts):
        return [[1.0, 0.0, 0.0, 0.0] if "salamat" in t.lower() else [0.0, 1.0, 0.0, 0.0] for t in texts]

    monkeypatch.setattr("src.user_documents.compute_jina_embeddings", _fake_jina)
    owner_id = "user:" + "u" + "g" * 32
    doc_store.ingest_document(
        owner_id,
        filename="contrat_salamat.txt",
        content_bytes="Contrat achat mil Salamat 450 sacs a 210 XAF/kg.".encode("utf-8"),
        mime_type="text/plain",
    )

    # 1. Pure greeting ("Bonjour") must NOT retrieve the PDF and must NOT waste Jina tokens
    assert doc_store.retrieve_for_owner(owner_id, "Bonjour") == []
    # 2. Unrelated question with cosine=0 and BM25=0 must NOT inject the old PDF
    assert doc_store.retrieve_for_owner(owner_id, "Quel est le prix du sorgho à Moundou ?") == []
    # 3. Explicit document question MUST retrieve it
    hits = doc_store.retrieve_for_owner(owner_id, "Résume mon contrat")
    assert len(hits) == 1
    assert hits[0]["filename"] == "contrat_salamat.txt"


def test_p2_numbers_are_grounded_allows_rounding_and_margin_diff_but_blocks_hallucination():
    from src.ai_agent import numbers_are_grounded

    source = "Prix d'achat Salamat : 210 XAF/kg. Prix de vente N'Djamena : 290 XAF/kg."
    # Margin diff = 290 - 210 = 80 (and per 100kg bag = 8000), rounding = 211 -> ALLOWED
    assert numbers_are_grounded("L'écart est de 80 XAF/kg (soit 8 000 XAF par sac de 100 kg), autour de 211 XAF.", source)
    # Hallucinated price 945 XAF/kg -> STILL BLOCKED
    assert not numbers_are_grounded("Le prix prévu est de 945 XAF/kg.", source)



