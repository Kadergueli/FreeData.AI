"""Deep Stabilization Tests for Chat Engine, Instruction Understanding, RAG, Tool Routing & PDF Validation."""
from dataclasses import replace

import numpy as np
import pandas as pd

from src.ai_agent import FreeDataAIAgent, extract_client_state
from src.orchestrator_ml_rag import IntelligenceOrchestrator
from src.reports import build_market_study_dossier, render_market_study_pdf
from src.study_context import classify_user_turn, extract_structured_instructions


def _make_sample_frames():
    months = pd.period_range("2024-01", "2026-10", freq="M")
    rows = []
    for i, m in enumerate(months):
        rows.append({
            "source": "WFP",
            "province": "Salamat",
            "market_name": "Am Timan",
            "commodity_std": "Millet",
            "year_month": str(m),
            "last_observed_month": str(m),
            "value": 200.0 + (i % 6) * 5.0,
            "forecast_month": "2026-11",
            "forecast_t1": 225.0,
            "ci_low_80": 195.0,
            "ci_high_80": 250.0,
            "hist_mae": 11.0,
        })
        rows.append({
            "source": "WFP",
            "province": "N'Djamena",
            "market_name": "N'Djamena",
            "commodity_std": "Millet",
            "year_month": str(m),
            "last_observed_month": str(m),
            "value": 285.0 + (i % 6) * 4.0,
            "forecast_month": "2026-11",
            "forecast_t1": 305.0,
            "ci_low_80": 270.0,
            "ci_high_80": 330.0,
            "hist_mae": 13.0,
        })
    hist_df = pd.DataFrame(rows)
    fc_df = hist_df.groupby(["province", "commodity_std"], as_index=False).tail(1).reset_index(drop=True)
    cp_df = pd.DataFrame([
        {
            "province": "Salamat",
            "commodity_std": "Millet",
            "credit_score": 76.0,
            "grade": "A",
            "ltv_ratio": 0.72,
            "cv_pct": 12.0,
            "max_drawdown_pct": -15.0,
            "obs_months": 34,
            "policy_recommendation": "Favorable",
        },
        {
            "province": "N'Djamena",
            "commodity_std": "Millet",
            "credit_score": 71.0,
            "grade": "A",
            "ltv_ratio": 0.68,
            "cv_pct": 14.0,
            "max_drawdown_pct": -18.0,
            "obs_months": 34,
            "policy_recommendation": "Favorable",
        },
    ])
    return hist_df, fc_df, cp_df


def test_turn_intent_classification_covers_all_six_categories():
    assert classify_user_turn("Quel est le prix du mil ?") == "new_request"
    assert classify_user_turn("Finalement mets plutôt 4 000 000 FCFA") == "modification"
    assert classify_user_turn("Continue la suite", has_history=True) == "continuation"
    assert classify_user_turn("Générer le PDF de mon business plan") == "document_generation"
    assert classify_user_turn("Analyse mon document et résume les tarifs") == "file_analysis"
    assert classify_user_turn("Fais une prévision Ridge et vérifie les anomalies") == "tool_ml_rag"

    parsed = extract_structured_instructions("Inclure SWOT, sans marketing, CAPEX = 0, en PDF")
    assert parsed["turn_intent"] == "document_generation"
    assert "SWOT" in parsed["add_sections"]
    assert "marketing" in parsed["remove_sections"]
    assert parsed["zero_capex_override"] is True


def test_long_multi_turn_conversation_preserves_constraints_and_applies_recent_corrections():
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    # 12-turn conversation with early constraints (SWOT, sans equipement, Salamat -> N'Djamena)
    # and a late correction changing capital from 2M to 4.5M FCFA
    history = [
        {"role": "user", "content": "Je veux faire du négoce de mil du Salamat vers N'Djamena avec 2 000 000 FCFA."},
        {"role": "assistant", "content": "Très bien, je note 2 000 000 FCFA sur l'axe Salamat → N'Djamena."},
        {"role": "user", "content": "Inclure une analyse SWOT, sans équipement (CAPEX = 0) et sans marketing."},
        {"role": "assistant", "content": "Noté : SWOT inclus, CAPEX = 0, marketing exclu."},
    ]
    for i in range(5):
        history.append({"role": "user", "content": f"Question de suivi {i+1} sur les délais de rotation."})
        history.append({"role": "assistant", "content": f"Réponse sur les délais {i+1}."})

    state = extract_client_state(
        history,
        "Finalement mon capital passe à 4 500 000 FCFA et mon transport est à 22 XAF/kg.",
        provider=agent.provider,
    )
    kp = state["known_params"]
    ctx = state["study_context"]
    # Recent corrections applied:
    assert kp["capital_xaf"] == 4_500_000.0
    assert kp["transport_cost_per_kg"] == 22.0
    # Earlier constraints preserved across long conversation:
    assert kp["commodity"] == "Millet"
    assert kp["origin_province"] == "Salamat"
    assert kp["dest_province"] == "N'Djamena"
    assert "SWOT" in ctx["required_sections"]
    assert "marketing" in ctx["excluded_sections"]
    assert ctx["budget_and_assumptions"]["zero_capex"] is True


def test_missing_document_evidence_is_explicitly_acknowledged():
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    ans = agent.answer(
        "Que dit mon document sur les clauses de pénalité bancaire ?",
        tier="free",
        private_chunks=[],
    )
    assert ans["intent"] == "document_not_found"
    assert "aucun passage suffisamment pertinent" in ans["reply"].lower()
    assert ans["sources"] == []


def test_pdf_generation_preserves_requested_sections_tables_and_passes_post_render_validation():
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    state = extract_client_state(
        [],
        "Business plan mil Salamat vers N'Djamena capital 3 000 000 FCFA, inclure SWOT et PESTEL, sans équipement, sans marketing.",
        provider=agent.provider,
    )
    dossier = build_market_study_dossier(
        provider=agent.provider,
        commodity="Millet",
        origin_province="Salamat",
        dest_province="N'Djamena",
        capital_xaf=3_000_000.0,
        transport_cost_per_kg=25.0,
        promoter_name="Coopérative Salamat",
        user_instructions=state["user_instructions"],
        study_context=state["study_context"],
    )
    pdf_bytes, post_val = render_market_study_pdf(dossier, return_validation=True)
    assert pdf_bytes.startswith(b"%PDF-")
    assert post_val["passed"] is True, f"Post-render PDF issues: {post_val['issues']}"
    assert post_val["page_count"] >= 1
    assert post_val["missing_sections"] == []
    assert post_val["expected_table_count"] >= 3


def test_tool_orchestrator_routes_and_executes_ridge_on_value_column():
    hist_df, fc_df, cp_df = _make_sample_frames()
    orch = IntelligenceOrchestrator()

    assert orch.select_tool("Fais une prévision Ridge du mil") == "ml_forecast"
    assert orch.select_tool("Quelles sont les anomalies récentes ?") == "ml_anomaly"
    assert orch.select_tool("Segmente les marchés en clusters") == "ml_cluster"
    assert orch.select_tool("Quelle est la méthodologie du rapport ?") == "rag_hybrid"

    res = orch.handle(
        "Fais une prévision Ridge du mil au Salamat",
        forecast_df=fc_df,
        hist_df=hist_df,
        passport_df=cp_df,
        anomalies_df=pd.DataFrame(),
        commodity="Millet",
        province="Salamat",
    )
    assert res["tool_used"] == "ml_forecast"
    # Verify Ridge actually evaluated on the `value` column (not `insufficient_history`)
    assert res["result"]["ridge_regression"]["status"] == "evaluated"


def test_provider_timeout_falls_back_gracefully_without_exposing_secrets(monkeypatch):
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    from src import ai_agent
    monkeypatch.setattr(
        ai_agent,
        "settings",
        replace(ai_agent.settings, llm_api_key="gsk_secret_token_never_leak"),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("Simulated Groq timeout with gsk_secret_token_never_leak")

    monkeypatch.setattr(ai_agent.requests, "post", _boom)
    ans = agent.answer("Quel est le prix prévu du mil au Salamat ?", tier="premium")
    assert ans["intent"] == "forecast"
    assert "gsk_secret_token_never_leak" not in ans["reply"]
    assert "Simulated Groq timeout" not in ans["reply"]
    assert "225" in ans["reply"] or "Salamat" in ans["reply"]


def test_multi_intent_single_turn_executes_primary_and_secondary_tools():
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    # Combines price forecast + Credit Passport in a single turn
    ans = agent.answer(
        "Donne-moi la prévision du prix du mil au Salamat ainsi que son score Credit Passport et son LTV.",
        tier="free",
    )
    assert ans["intent"] in ("forecast", "credit_passport")
    # Both forecast price (225) and Credit Passport score (76) must appear in the grounded response
    assert "225" in ans["reply"]
    assert "76" in ans["reply"]
    assert ans["entities"].get("secondary_intents")




def test_rag_evidence_prevents_generic_clarification_when_public_docs_match(monkeypatch):
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)
    expected_chunk = {
        "titre": "Méthodologie de validation",
        "editeur": "FreeData.AI",
        "page": 4,
        "url_source": "https://example.org/methodologie",
        "content": "La qualité des prix est évaluée par validation des unités, contrôle des doublons et comparaison temporelle.",
        "similarity": 0.81,
    }
    seen_queries = []
    monkeypatch.setattr(
        agent.provider,
        "retrieve_rag_chunks",
        lambda query, match_count=6, **kwargs: (seen_queries.append(query) or [expected_chunk]),
    )

    answer = agent.answer("Comment la qualité des prix est-elle vérifiée ?", tier="free")

    assert answer["intent"] == "rag_answer"
    assert "validation des unités" in answer["reply"]
    assert answer["sources"][0]["titre"] == "Méthodologie de validation"
    assert seen_queries


def test_rag_short_followup_uses_recent_user_context_instead_of_generic_reply(monkeypatch):
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)
    expected_chunk = {
        "titre": "Méthodologie",
        "editeur": "WFP",
        "page": 2,
        "content": "Le suivi combine les prix observés et les contrôles de cohérence.",
        "similarity": 0.79,
    }
    seen_queries = []
    monkeypatch.setattr(
        agent.provider,
        "retrieve_rag_chunks",
        lambda query, match_count=6, **kwargs: (seen_queries.append(query) or [expected_chunk]),
    )
    history = [
        {"role": "user", "content": "Explique la méthodologie de contrôle des prix du mil au Salamat."},
        {"role": "assistant", "content": "La méthodologie combine plusieurs contrôles."},
    ]

    answer = agent.answer("Pourquoi ?", history=history, tier="free")

    assert answer["intent"] == "rag_answer"
    assert "mil au salamat" in seen_queries[0].lower()
    assert "contrôles de cohérence" in answer["reply"]


def test_rag_methodology_question_uses_retrieved_evidence_even_with_market_entities(monkeypatch):
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)
    expected_chunk = {
        "titre": "Méthode de prévision",
        "editeur": "FreeData.AI",
        "page": 6,
        "content": "La prévision combine une validation chronologique, un modèle de référence et une régression Ridge.",
        "similarity": 0.84,
    }
    monkeypatch.setattr(
        agent.provider,
        "retrieve_rag_chunks",
        lambda query, match_count=6, **kwargs: [expected_chunk],
    )

    answer = agent.answer(
        "Quelle est la méthodologie de calcul de la prévision du mil au Salamat ?",
        tier="free",
    )

    assert answer["intent"] == "rag_answer"
    assert "validation chronologique" in answer["reply"]
    assert answer["sources"][0]["titre"] == "Méthode de prévision"


def test_llm_clarify_router_cannot_bypass_relevant_rag_evidence(monkeypatch):
    hist_df, fc_df, cp_df = _make_sample_frames()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)
    from src import ai_agent

    monkeypatch.setattr(
        ai_agent,
        "settings",
        replace(ai_agent.settings, llm_api_key="gsk_test_key", llm_routing=True),
    )
    monkeypatch.setattr(agent, "_route_with_llm", lambda *args, **kwargs: {"intent": "clarify"})
    expected_chunk = {
        "titre": "Méthodologie des prix",
        "editeur": "FreeData.AI",
        "page": 3,
        "content": "Les prix sont contrôlés par cohérence des unités, détection des doublons et validation des dates.",
        "similarity": 0.86,
    }
    monkeypatch.setattr(
        agent.provider,
        "retrieve_rag_chunks",
        lambda query, match_count=6, **kwargs: [expected_chunk],
    )
    synthesis_calls = []
    monkeypatch.setattr(
        agent,
        "_synthesize_with_llm",
        lambda query, facts, chunks, **kwargs: (
            synthesis_calls.append({"query": query, "facts": facts, "chunks": chunks, **kwargs})
            or "Le document décrit trois contrôles : cohérence des unités, détection des doublons et validation des dates."
        ),
    )

    answer = agent.answer(
        "Comment fonctionne le contrôle qualité du prix du mil au Salamat ?",
        tier="premium",
    )

    assert answer["intent"] == "rag_answer"
    assert "détection des doublons" in answer["reply"]
    assert synthesis_calls and synthesis_calls[0]["rag_only"] is True
