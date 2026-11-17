"""Tests pour l'écoute active, la mémoire de consignes client et le dialogue consultatif."""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.ai_agent import FreeDataAIAgent, extract_client_state
from src.config import settings


def _sample_agent() -> FreeDataAIAgent:
    hist_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "date": "2026-07-01", "price": 210.0},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "date": "2026-07-01", "price": 340.0},
        {"province": "Salamat", "market_name": "Am Timan", "commodity_std": "Onions", "date": "2026-07-01", "price": 450.0},
    ])
    fc_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 220.0, "last_observed_price": 210.0, "change_pct": 4.8},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 350.0, "last_observed_price": 340.0, "change_pct": 2.9},
        {"province": "Salamat", "market_name": "Am Timan", "commodity_std": "Onions", "forecast_month": "2026-08", "forecast_t1": 480.0, "last_observed_price": 450.0, "change_pct": 6.7},
    ])
    cp_df = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "score_global": 82.0, "grade": "A", "cv_pct": 8.5, "ltv_pct": 70.0, "max_drawdown_pct": 6.0},
        {"province": "Salamat", "commodity_std": "Onions", "score_global": 88.0, "grade": "A", "cv_pct": 18.0, "ltv_pct": 60.0, "max_drawdown_pct": 12.0},
        {"province": "N'Djamena", "commodity_std": "Sorghum (red)", "score_global": 79.0, "grade": "B", "cv_pct": 9.2, "ltv_pct": 65.0, "max_drawdown_pct": 7.0},
    ])
    return FreeDataAIAgent(hist_df=hist_df, forecast_df=fc_df, passport_df=cp_df)


@pytest.mark.parametrize("msg,expected_profile", [
    ("Je veux acheter 20 sacs de mil et les revendre à N'Djamena", "commercant"),
    ("Je suis débutant et je veux monter un business au Tchad", "debutant"),
    ("Je prépare un mémoire universitaire sur la volatilité MAE et CV", "chercheur"),
    ("Notre ONG prépare un programme de sécurité alimentaire PAM", "ong"),
    ("Notre institution financière étudie un dossier de crédit LTV", "institution_financiere"),
    ("Bonjour, quel est le prix à Moundou ?", "general"),
])
def test_extract_client_state_profiles(msg, expected_profile):
    state = extract_client_state([], msg)
    assert state["user_profile"] == expected_profile


def test_extract_client_state_accumulates_params_and_instructions():
    history = [
        {"role": "user", "content": "Je veux acheter du mil à Lac. Évite les produits périssables."},
        {"role": "assistant", "content": "Très bien, quel est votre capital de départ ?"},
        {"role": "user", "content": "Mon objectif est d'investir 1 200 000 FCFA avec un transport de 45 XAF/kg pour 10 sacs."},
    ]
    state = extract_client_state(history, "Je veux revendre à N'Djamena. Prends en compte mes contraintes.")
    kp = state["known_params"]
    assert kp["commodity"] == "Millet"
    assert kp["origin_province"] == "Lac"
    assert kp["dest_province"] == "N'Djamena"
    assert kp["capital_xaf"] == 1_200_000.0
    assert kp["transport_cost_per_kg"] == 45.0
    assert kp["quantity_kg"] == 1000.0
    assert len(state["user_instructions"]) >= 3
    assert state["missing_fields"] == []


def test_consultative_dialogue_qualifies_then_applies_constraints():
    agent = _sample_agent()
    r1 = agent.answer("Aide-moi à monter un business", history=[], tier="free")
    assert r1["intent"] == "needs_capital"
    assert "1." in r1["reply"] and "2." in r1["reply"] and "3." in r1["reply"]
    assert "500 000" not in r1["reply"].split("1.")[0]

    history = [
        {"role": "user", "content": "Aide-moi à monter un business. Sans produits périssables."},
        {"role": "assistant", "content": r1["reply"]},
    ]
    r2 = agent.answer("J'ai 1 000 000 FCFA pour acheter à Lac et vendre à N'Djamena, transport 40 XAF/kg.", history=history, tier="free")
    assert r2["intent"] == "business_simulator"
    assert "40 XAF/kg" in r2["reply"]
    assert "1 000 000" in r2["reply"]


def test_synthesize_with_llm_includes_client_state(monkeypatch):
    from dataclasses import replace

    agent = _sample_agent()
    monkeypatch.setattr("src.ai_agent.settings", replace(settings, llm_api_key="test-key"))
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["messages"] = json["messages"]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"choices": [{"message": {"content": "Voici votre plan pour 1 000 000 XAF à Lac."}}]}
        return resp

    monkeypatch.setattr("src.ai_agent.requests.post", fake_post)
    state = extract_client_state([], "Je veux investir 1 000 000 FCFA à Lac, sans périssables.")
    out = agent._synthesize_with_llm("Plan", "Mil Lac : 220 XAF/kg", [], client_state=state)
    assert "1 000 000" in out
    sys_msg = captured["messages"][0]["content"]
    usr_msg = captured["messages"][-1]["content"]
    assert "COMPRÉHENSION DU CLIENT & RESPECT STRICT DE SES INSTRUCTIONS" in sys_msg
    assert "[ÉTAT ET INSTRUCTIONS DU CLIENT]" in usr_msg
    assert "sans périssables" in usr_msg.lower()
