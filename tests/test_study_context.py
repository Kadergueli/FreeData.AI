"""Tests for persistent StudyContext, structured instruction extraction, partial updates, and contradictions."""
from src.ai_agent import extract_client_state
from src.study_context import StudyContext


def test_long_conversation_preserves_early_instructions_beyond_8_messages():
    history = [
        {"role": "user", "content": "Je veux lancer un négoce de mil de Lac vers N'Djamena avec 500 000 XAF, promoteur : Moussa Mahamat."},
        {"role": "assistant", "content": "Bien noté."},
        {"role": "user", "content": "Inclure une analyse SWOT et PESTEL, sans produits périssables."},
        {"role": "assistant", "content": "Noté."},
    ]
    for i in range(1, 7):
        history.append({"role": "user", "content": f"Question intermédiaire {i} sur les prix."})
        history.append({"role": "assistant", "content": f"Réponse {i}."})

    assert len(history) == 16  # > 8 messages
    state = extract_client_state(history, "Ajoute une analyse concurrentielle et génère le PDF.")
    ctx = state["study_context"]

    assert state["known_params"]["commodity"] == "Millet"
    assert state["known_params"]["origin_province"] == "Lac"
    assert state["known_params"]["dest_province"] == "N'Djamena"
    assert state["known_params"]["capital_xaf"] == 500000.0
    assert state["known_params"]["promoter_name"] == "Moussa Mahamat"
    assert "SWOT" in ctx["required_sections"]
    assert "PESTEL" in ctx["required_sections"]
    assert "competitor_analysis" in ctx["required_sections"]
    assert ctx["report_format"] == "pdf"
    assert any("périssables" in c.lower() for c in ctx["operational_constraints"])


def test_truncated_history_restores_early_instructions_from_study_context():
    early_state = extract_client_state(
        [],
        "Étude de préfaisabilité du sorgho à Batha, capital 800 000 XAF, promoteur : Amina Saleh, inclure SWOT et recommandations opérationnelles.",
    )
    saved_ctx = early_state["study_context"]

    # Simulate client sending only recent truncated turns + persisted study_context
    recent_history = [{"role": "user", "content": f"Message récent {i}"} for i in range(8)]
    updated_state = extract_client_state(
        recent_history,
        "Finalement mets plutôt un budget de 1 200 000 XAF pour les restaurateurs.",
        previous_context=saved_ctx,
    )
    ctx = updated_state["study_context"]

    assert updated_state["known_params"]["capital_xaf"] == 1200000.0
    assert updated_state["known_params"]["commodity"] == "Sorghum (red)"
    assert updated_state["known_params"]["origin_province"] == "Batha"
    assert updated_state["known_params"]["promoter_name"] == "Amina Saleh"
    assert "SWOT" in ctx["required_sections"]
    assert "operational_recommendations" in ctx["required_sections"]
    assert "restaurateurs" in ctx["target_customers"]


def test_exclusions_products_provinces_and_sections():
    state = extract_client_state(
        [],
        "Négoce de mil à Batha vers N'Djamena, sans riz, exclure Lac, inclure SWOT et PESTEL, sans marketing.",
    )
    ctx = state["study_context"]

    assert ctx["product_activity"]["commodity"] == "Millet"
    assert "Rice (imported)" in ctx["product_activity"]["excluded_commodities"]
    assert ctx["geography"]["origin_province"] == "Batha"
    assert ctx["geography"]["dest_province"] == "N'Djamena"
    assert "Lac" in ctx["geography"]["excluded_provinces"]
    assert "SWOT" in ctx["required_sections"]
    assert "PESTEL" in ctx["required_sections"]
    assert "marketing" in ctx["excluded_sections"]


def test_contradictory_instructions_flagged_unless_explicit_correction():
    s1 = extract_client_state([], "Inclure PESTEL dans le rapport.")
    s2 = extract_client_state([], "Exclure PESTEL.", previous_context=s1["study_context"])
    ctx2 = s2["study_context"]
    assert ctx2["needs_clarification"] is True
    assert len(ctx2["contradictions"]) >= 1
    assert len(ctx2["clarification_questions"]) >= 1

    # Explicit correction should cleanly update without flagging a contradiction
    s3 = extract_client_state([], "Finalement exclure PESTEL.", previous_context=s1["study_context"])
    ctx3 = s3["study_context"]
    assert ctx3["needs_clarification"] is False
    assert "PESTEL" in ctx3["excluded_sections"]
    assert "PESTEL" not in ctx3["required_sections"]


def test_study_context_serialization_and_credential_stripping():
    ctx = StudyContext()
    ctx.promoter_info["name"] = "Kader"
    ctx.required_sections.append("SWOT")
    raw = ctx.to_dict()
    raw["x_premium_key"] = "secret-key"
    raw["promoter_info"]["api_token"] = "leak"

    restored = StudyContext.from_dict(raw)
    restored_json = restored.to_json()
    restored2 = StudyContext.from_json(restored_json)

    assert restored2.promoter_info["name"] == "Kader"
    assert "SWOT" in restored2.required_sections
    assert "x_premium_key" not in restored2.to_dict()
    assert "api_token" not in restored2.promoter_info
