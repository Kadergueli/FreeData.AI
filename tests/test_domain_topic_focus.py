"""Les thématiques du sélecteur de l'application correspondent chacune à un vrai domaine : la réponse est cadrée par lui."""
import pytest

from src.domains import DomainRegistry

UI_TOPICS = ["markets_and_prices", "economy", "health", "population", "environment", "infrastructure", "transport"]


@pytest.mark.parametrize("topic", UI_TOPICS)
def test_ui_topic_resolves_to_its_own_domain(topic):
    mod = DomainRegistry.classify_domain("bonjour", explicit_domain=topic)
    assert mod.domain_id == topic
    assert mod is DomainRegistry.MODULES[topic]


def test_agriculture_domain_is_selectable():
    assert DomainRegistry.classify_domain("bonjour", explicit_domain="agriculture").domain_id == "agriculture"


def test_unknown_explicit_domain_falls_back_to_query_routing():
    assert DomainRegistry.classify_domain("bonjour", explicit_domain="inconnu").domain_id == "markets_and_prices"
    assert DomainRegistry.classify_domain("situation sanitaire et paludisme", explicit_domain="inconnu").domain_id == "health"
