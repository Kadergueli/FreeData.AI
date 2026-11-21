"""Phase 11B tests: Multi-Domain Architecture, Unified Routing, and Free/Premium Entitlements."""
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.domains import DomainRegistry
from src.entitlements import EntitlementManager
from src.rag_engine import HybridRAGEngine


def test_domain_classification_across_chad_domains():
    assert DomainRegistry.classify_domain("Quels sont les indicateurs de santé et vaccination au Tchad ?").domain_id == "health"
    assert DomainRegistry.classify_domain("Évolution de la population et recensement démographique").domain_id == "population"
    assert DomainRegistry.classify_domain("Impact de la sécheresse et du climat autour du Lac Tchad").domain_id == "environment"
    assert DomainRegistry.classify_domain("État des infrastructures et accès à l'eau potable").domain_id == "infrastructure"
    assert DomainRegistry.classify_domain("Coût du transport et corridor de fret logistique").domain_id == "transport"
    assert DomainRegistry.classify_domain("Calcule le BFR, CAPEX, point mort et risque crédit").domain_id == "economy"
    assert DomainRegistry.classify_domain("Rendement et campagne agricole au Tchad").domain_id == "agriculture"
    assert DomainRegistry.classify_domain("Prix du mil à Bol en XAF").domain_id == "markets_and_prices"
    assert DomainRegistry.classify_domain("Bonjour, comment vas-tu aujourd'hui ?").domain_id == "markets_and_prices"
    assert len(DomainRegistry.list_domains()) == 8


def test_backend_entitlements_and_quotas():
    ent = EntitlementManager()
    # Free tier has useful features, but blocks PRO PDF & batch ML
    ent.check_feature("free", "general_chat")
    ent.check_feature("free", "market_lookup")
    with pytest.raises(PermissionError):
        ent.check_feature("free", "pro_pdf_reports")
    with pytest.raises(PermissionError):
        ent.check_feature("free", "ml_batch_predict")

    # Premium unlocks all features
    ent.check_feature("premium", "pro_pdf_reports")
    ent.check_feature("premium", "ml_batch_predict")

    # Daily quota enforcement
    ent.POLICIES["free"]["daily_chat_quota"] = 2
    try:
        ent.consume_chat_quota("free", "u1")
        ent.consume_chat_quota("free", "u1")
        with pytest.raises(OverflowError):
            ent.consume_chat_quota("free", "u1")
    finally:
        ent.POLICIES["free"]["daily_chat_quota"] = 30


def test_platform_chat_cross_domain_routing_and_quota(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    fc = pd.DataFrame([
        {"source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "last_observed_month": "2026-10", "last_observed_price": 210.0, "forecast_month": "2026-11", "forecast_t1": 220.0},
    ])
    cp = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "cv_pct": 8.5, "ltv_ratio": 0.8}])
    st = server.build_state_from_gold(fc, cp)
    rag = HybridRAGEngine()
    rag.add_text_document("api", "FastAPI utilise Pydantic pour la validation.", title="API", source="API.md")
    ent = EntitlementManager()

    # Health domain (in_preparation) on free tier -> grounded RAG fallback, zero invented stats
    r_health = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Quelles données de santé et vaccination sont disponibles ?", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_health["domain"] == "health"
    assert "préparation" in r_health["reply"].lower()

    # Transport domain (in_preparation)
    r_tr = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Coût du fret et corridor de transport au Tchad", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_tr["domain"] == "transport"

    # Markets & Prices operational Chad domain routes to FreeDataAIAgent
    r_mp = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Quel est le prix du mil à Lac ?", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_mp["domain"] == "markets_and_prices"
    assert "210" in r_mp["reply"]

    doms = server.list_domains_endpoint(x_user_id="user:test1", x_premium_key=None, ent=ent)
    assert len(doms["domains"]) == 8
    assert doms["entitlements"]["used_today"] == 3

