"""Phase 11B tests: Multi-Domain Architecture, Unified Routing, and Free/Premium Entitlements."""
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.domains import DomainRegistry
from src.entitlements import EntitlementManager
from src.rag_engine import HybridRAGEngine


def test_domain_classification_across_10_domains():
    assert DomainRegistry.classify_domain("Debug ce script Python FastAPI").domain_id == "tech_programming"
    assert DomainRegistry.classify_domain("Fais un clustering K-Means et backtest RMSE").domain_id == "data_science"
    assert DomainRegistry.classify_domain("Explique-moi ce théorème avec un exercice").domain_id == "education"
    assert DomainRegistry.classify_domain("Revue de littérature pour ma thèse").domain_id == "academic_research"
    assert DomainRegistry.classify_domain("Organiser ma checklist et roadmap").domain_id == "productivity"
    assert DomainRegistry.classify_domain("Calcule le BFR, CAPEX et point mort").domain_id == "finance"
    assert DomainRegistry.classify_domain("Fais un business plan avec SWOT et PESTEL").domain_id == "business_entrepreneurship"
    assert DomainRegistry.classify_domain("Prix du mil à Bol").domain_id == "agriculture"
    assert DomainRegistry.classify_domain("Situation économique à N'Djamena en XAF").domain_id == "chad_intelligence"
    assert DomainRegistry.classify_domain("Bonjour, comment vas-tu aujourd'hui ?").domain_id == "general_ai"
    assert len(DomainRegistry.list_domains()) == 10


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

    # Tech domain on free tier
    r_tech = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Comment valider avec FastAPI ?", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_tech["domain"] == "tech_programming"
    assert "API.md" in r_tech["reply"]

    # Data science domain routes to IntelligenceOrchestrator
    r_ds = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Fais un clustering K-Means des marchés", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_ds["domain"] == "data_science"
    assert r_ds["intent"] == "ml_cluster"

    # Agriculture / Chad domain routes to FreeDataAIAgent preserving StudyContext
    r_ag = server.platform_chat_endpoint(
        server.PlatformChatRequest(message="Quel est le prix du mil à Lac ?", tier="free"),
        state=st,
        x_user_id="user:test1",
        x_premium_key=None,
        rag=rag,
        svc=server.get_analytics_service(),
        ent=ent,
    )
    assert r_ag["domain"] == "agriculture"
    assert "210" in r_ag["reply"]

    doms = server.list_domains_endpoint(x_user_id="user:test1", x_premium_key=None, ent=ent)
    assert len(doms["domains"]) == 10
    assert doms["entitlements"]["used_today"] == 3

