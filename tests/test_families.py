"""Contrat des familles : le chat découvre les familles via le registre, sans les connaître."""
import re

import pytest

from api import server
from src import ai_agent, families
from src.families import registry
from src.families.base import FamilySpec


@pytest.fixture()
def agent(gold_tables):
    fc_gold, cp_gold = gold_tables
    state = server.build_state_from_gold(fc_gold, cp_gold)
    return ai_agent.FreeDataAIAgent(state["hist_df"], state["forecast_df"], state["passport_df"])


def test_seasonality_family_is_registered():
    fam = families.by_intent("timing")
    assert fam is not None and fam.name == "seasonality"
    assert fam.gold_tables == ("table_ml_seasonality_studies",) and fam.offline_script


def test_registry_refuses_duplicates():
    spec = families.by_intent("timing")
    with pytest.raises(ValueError):
        registry.register(spec)
    with pytest.raises(ValueError):
        registry.register(FamilySpec(name="autre", label="x", intent="timing", pattern=re.compile("x"),
                                     router_hint="x", run=lambda a, e: ("", {}), intro=lambda e, w, h: ""))


def test_detect_respects_route_questions():
    assert families.detect("quand acheter du mil") is not None
    assert families.detect("quand acheter du mil", has_route=True) is None
    assert families.detect("bonjour") is None


def test_router_knows_registered_intents():
    assert "timing" in ai_agent.FreeDataAIAgent._ROUTER_INTENTS


def test_a_new_family_plugs_in_without_touching_the_core(agent, monkeypatch):
    """Une famille fictive est reconnue, exécutée, introduite et peut demander une précision."""
    monkeypatch.setattr(registry, "_FAMILIES", dict(registry._FAMILIES))
    fam = FamilySpec(
        name="demo", label="Démo", intent="demo_intent", pattern=re.compile(r"\bzorglub\b"),
        router_hint="demo_intent: test", intro=lambda e, what, where: f"Intro démo{what}{where}.",
        run=lambda a, e: ("FAITS-DEMO", {"ok": True}),
        clarify=lambda a, e, h: "Quel produit pour la démo ?" if not e.get("commodity") else None,
    )
    registry.register(fam)
    r = agent.answer("zorglub du mil")
    assert r["intent"] == "demo_intent" and "FAITS-DEMO" in r["reply"] and "Intro démo" in r["reply"]
    r2 = agent.answer("zorglub")
    assert r2["intent"] == "clarification" and "démo" in r2["reply"]
