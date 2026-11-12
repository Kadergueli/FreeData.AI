import pytest

from api import server
from src.ai_agent import FreeDataAIAgent, numbers_are_grounded


@pytest.fixture()
def agent(gold_tables):
    fc_gold, cp_gold = gold_tables
    state = server.build_state_from_gold(fc_gold, cp_gold)
    return FreeDataAIAgent(state["hist_df"], state["forecast_df"], state["passport_df"])


@pytest.mark.parametrize(
    "question, intent, province, commodity, loan",
    [
        # Cas reproduits dans l'audit
        ("Quel est le risque de credit du mil au Salamat en 2025 ?", "credit_passport", "Salamat", "Millet", 1_000_000),
        ("Je fais une recherche sur le prix du mil", "forecast", None, "Millet", 1_000_000),
        ("Dois-je placer mon argent dans le mil ?", "forecast", None, "Millet", 1_000_000),
        # Questions proposées par l'application (chips)
        ("Quelle est la prévision du prix du mil à N'Djamena ?", "forecast", "N'Djamena", "Millet", 1_000_000),
        ("Quel est le risque de financer 3 millions de FCFA de mil au Salamat ?", "credit_passport", "Salamat", "Millet", 3_000_000),
        ("Quelles sont les alertes de hausse de prix actuelles ?", "alerts", None, None, 1_000_000),
        # Montants avec unité
        ("credit mil Salamat 500 000 fcfa", "credit_passport", "Salamat", "Millet", 500_000),
        ("pret de 2,5 millions pour du mil", "credit_passport", None, "Millet", 2_500_000),
    ],
)
def test_entity_extraction(agent, question, intent, province, commodity, loan):
    e = agent._extract_entities(question)
    assert (e["intent"], e["province"], e["commodity"], e["loan_amount"]) == (intent, province, commodity, loan)


def test_unknown_product_is_announced(agent):
    reply = agent.answer_with_metadata("Quel est le prix du ble a N'Djamena ?")["reply"]
    assert "Produit non précisé ou non reconnu" in reply


def test_credit_reply_has_disclaimer(agent):
    reply = agent.answer_with_metadata("risque de credit du mil au Salamat")["reply"]
    assert "ne constitue" in reply


def test_numbers_are_grounded_accepts_facts_and_rejects_invented():
    facts = "prévision `352 XAF/kg`, IC 80% : [301 – 403]"
    assert numbers_are_grounded("Le prix prévu est de 352 XAF/kg (entre 301 et 403).", facts, "question")
    assert not numbers_are_grounded("Le prix prévu est de 999 XAF/kg.", facts, "question")
    # chiffres isolés (numéros de liste) tolérés
    assert numbers_are_grounded("1. 352 XAF/kg", facts, "question")


def test_llm_answer_with_invented_number_falls_back_to_facts(agent, monkeypatch):
    import dataclasses
    from src import ai_agent

    monkeypatch.setattr(ai_agent, "settings", dataclasses.replace(ai_agent.settings, ollama_base_url="http://x"))

    class FakeResp:
        status_code = 200

        def json(self):
            return {"response": "Le prix sera de 987654 XAF/kg."}

    monkeypatch.setattr(ai_agent.requests, "post", lambda *a, **k: FakeResp())
    out = agent._refine_with_ollama("prix du mil", "faits: 352 XAF/kg")
    assert out == "faits: 352 XAF/kg"
