"""Les thématiques du sélecteur de l'application orientent réellement la réponse."""
import pytest

from src.domains import DomainRegistry

UI_TOPICS = ["markets_and_prices", "economy", "health", "population", "environment", "infrastructure", "transport"]


@pytest.mark.parametrize("topic", UI_TOPICS)
def test_ui_topic_resolves_to_existing_domain_with_focus(topic):
    mod = DomainRegistry.classify_domain("bonjour", explicit_domain=topic)
    base_id = DomainRegistry.TOPIC_FOCUS[topic][0]
    assert mod.domain_id == base_id
    assert DomainRegistry.TOPIC_FOCUS[topic][1] in mod.instructions
    assert DomainRegistry.MODULES[base_id].instructions in mod.instructions


def test_registry_is_not_mutated_and_count_unchanged():
    DomainRegistry.classify_domain("x", explicit_domain="health")
    assert "Cadre la réponse" not in DomainRegistry.MODULES["chad_intelligence"].instructions
    assert not any(t in DomainRegistry.MODULES for t in UI_TOPICS)


def test_explicit_real_domain_and_unknown_unchanged():
    assert DomainRegistry.classify_domain("x", explicit_domain="finance").domain_id == "finance"
    assert DomainRegistry.classify_domain("bonjour", explicit_domain="inconnu").domain_id == "general_ai"
