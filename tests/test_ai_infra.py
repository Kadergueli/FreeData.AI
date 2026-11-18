"""Tests for AI Infrastructure: ModelRouter, ProviderGateway fallback, TTLCache, and AIQualityMonitor."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from api import server
from src.ai_infra import AIQualityMonitor, LLMProviderAdapter, ModelRouter, ProviderGateway, TTLCache
from src.rag_engine import HybridRAGEngine


class _FailingProvider(LLMProviderAdapter):
    name = "primary_failing"

    def complete(self, messages, *, model, max_tokens, temperature, timeout):
        raise TimeoutError("Provider timeout")


class _HealthyProvider(LLMProviderAdapter):
    name = "secondary_ok"

    def complete(self, messages, *, model, max_tokens, temperature, timeout):
        return {"content": "Réponse OK", "tokens_in": 40, "tokens_out": 15, "model": model, "provider": self.name}


def test_model_router_and_subscription_guardrails():
    router = ModelRouter()
    assert router.select_model(task_type="forecasting", subscription_tier="free")["profile"] == "deterministic_ml"
    assert router.select_model(task_type="simple_qa", subscription_tier="free")["profile"] == "lightweight_fast"
    assert router.select_model(task_type="complex_reasoning", subscription_tier="premium", require_high_accuracy=True)["profile"] == "advanced_reasoning"

    with pytest.raises(PermissionError):
        router.select_model(task_type="complex_reasoning", subscription_tier="free", require_high_accuracy=True)


def test_provider_gateway_fallback_and_strict_no_downgrade():
    mon = AIQualityMonitor()
    gw = ProviderGateway([_FailingProvider(), _HealthyProvider()], monitor=mon)
    router = ModelRouter()

    # Simple QA allows fallback
    route_qa = router.select_model(task_type="simple_qa", subscription_tier="free")
    res = gw.generate([{"role": "user", "content": "Bonjour"}], route_decision=route_qa)
    assert res["used_fallback"] is True
    assert res["provider"] == "secondary_ok"

    # High-accuracy reasoning must NOT silently downgrade on fallback
    route_strict = router.select_model(task_type="complex_reasoning", subscription_tier="premium", require_high_accuracy=True)
    with pytest.raises(RuntimeError):
        gw.generate([{"role": "user", "content": "Analyse"}], route_decision=route_strict)

    snap = mon.snapshot(TTLCache(), TTLCache())
    assert snap["fallback_count"] == 1
    assert snap["provider_errors"] == 1
    assert snap["tokens_in"] == 40 and snap["tokens_out"] == 15


def test_ml_and_rag_cache_consistency_and_concurrency():
    req = server.MLPredictRequest(series_prices=[200, 204, 208, 212, 216, 220, 224, 228, 232, 236])
    r1 = server.ml_predict_endpoint(req, _caller="dev:test")
    r2 = server.ml_predict_endpoint(req, _caller="dev:test")
    assert r1["cached"] is False
    assert r2["cached"] is True
    assert r1["prediction_xaf_kg"] == r2["prediction_xaf_kg"]

    rag = HybridRAGEngine()
    rag.add_text_document("doc1", "Le point mort est calculé avec 5 XAF/kg de sacherie.", title="doc1", source="METHODOLOGY.md")
    q = server.RagSearchRequest(query="point mort sacherie", top_k=2)
    h1 = server.rag_hybrid_search_endpoint(q, rag=rag)
    h2 = server.rag_hybrid_search_endpoint(q, rag=rag)
    assert h1["cached"] is False
    assert h2["cached"] is True
    assert h1["hits"] == h2["hits"]

    # Concurrent TTLCache stress
    cache = TTLCache(ttl_seconds=60.0)
    cache.set("k", 42)
    with ThreadPoolExecutor(max_workers=8) as pool:
        vals = list(pool.map(lambda _: cache.get("k"), range(50)))
    assert all(v == 42 for v in vals)

