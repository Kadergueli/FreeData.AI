"""AI Infrastructure Layer: Model Routing, Provider Abstraction, Fallback, Caching & Quality Monitoring."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import requests


class TTLCache:
    """Thread-safe bounded TTL cache for ML predictions and RAG retrieval."""

    def __init__(self, ttl_seconds: float = 300.0, max_size: int = 512) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self.misses += 1
                return None
            exp, val = item
            if now > exp:
                self._store.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return val

    def set(self, key: str, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._store) >= self.max_size:
                oldest = sorted(self._store.items(), key=lambda kv: kv[1][0])[: max(1, self.max_size // 4)]
                for k, _ in oldest:
                    self._store.pop(k, None)
            self._store[key] = (now + self.ttl_seconds, value)


class ModelRouter:
    """Selects the appropriate model/engine based on task, subscription, accuracy, and cost."""

    MODEL_PROFILES: dict[str, dict[str, Any]] = {
        "deterministic_ml": {
            "category": "ml_model",
            "model_id": "ridge_kmeans_classifier",
            "cost_tier": "zero_llm_cost",
            "requires_premium": False,
        },
        "embedding_rag": {
            "category": "embedding",
            "model_id": "hybrid_bm25_hashed_or_jina_v3",
            "cost_tier": "low",
            "requires_premium": False,
        },
        "lightweight_fast": {
            "category": "lightweight_llm",
            "model_id": "llama-3.1-8b-instant",
            "cost_tier": "low",
            "requires_premium": False,
        },
        "advanced_reasoning": {
            "category": "advanced_llm",
            "model_id": "llama-3.3-70b-versatile",
            "cost_tier": "high",
            "requires_premium": True,
        },
        "coding_specialist": {
            "category": "coding_llm",
            "model_id": "llama-3.3-70b-versatile",
            "cost_tier": "high",
            "requires_premium": False,
        },
    }

    def select_model(
        self,
        *,
        task_type: str,
        subscription_tier: str = "free",
        context_length: int = 0,
        require_high_accuracy: bool = False,
    ) -> dict[str, Any]:
        if task_type in ("prediction", "forecasting", "clustering", "classification", "ml"):
            return {"profile": "deterministic_ml", **self.MODEL_PROFILES["deterministic_ml"], "allow_downgrade_fallback": False}
        if task_type in ("embedding", "rag_retrieval"):
            return {"profile": "embedding_rag", **self.MODEL_PROFILES["embedding_rag"], "allow_downgrade_fallback": True}
        if task_type == "coding":
            return {"profile": "coding_specialist", **self.MODEL_PROFILES["coding_specialist"], "allow_downgrade_fallback": False}
        if task_type in ("complex_reasoning", "business_plan", "market_study") or require_high_accuracy or context_length > 2000:
            if subscription_tier != "premium" and require_high_accuracy:
                raise PermissionError("Le raisonnement haute précision nécessite un abonnement Premium.")
            prof = "advanced_reasoning" if subscription_tier == "premium" else "lightweight_fast"
            return {
                "profile": prof,
                **self.MODEL_PROFILES[prof],
                "allow_downgrade_fallback": not require_high_accuracy,
            }
        return {"profile": "lightweight_fast", **self.MODEL_PROFILES["lightweight_fast"], "allow_downgrade_fallback": True}


class LLMProviderAdapter(ABC):
    """Provider-independent LLM transport abstraction with connection pooling."""

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[dict[str, str]], *, model: str, max_tokens: int, temperature: float, timeout: float) -> dict[str, Any]:
        """Execute completion and return {content, tokens_in, tokens_out, model, provider}."""


class OpenAICompatibleAdapter(LLMProviderAdapter):
    """Connection-pooled OpenAI-compatible provider (Groq, OpenAI, Together, etc.)."""

    def __init__(self, name: str, base_url: str, api_key: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session = requests.Session()

    def complete(self, messages: list[dict[str, str]], *, model: str, max_tokens: int, temperature: float, timeout: float) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(f"Clé API manquante pour le fournisseur {self.name}.")
        resp = self._session.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        content = (choices[0]["message"]["content"] if choices else "").strip()
        usage = data.get("usage") or {}
        return {
            "content": content,
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "model": model,
            "provider": self.name,
        }


class AIQualityMonitor:
    """Tracks non-PII AI infrastructure metrics: routing, latency, tokens, errors, fallbacks, cache."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.routing_counts: dict[str, int] = {}
        self.provider_errors = 0
        self.fallback_count = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.total_latency_ms = 0.0
        self.total_calls = 0

    def record_call(self, *, profile: str, latency_ms: float, tokens_in: int = 0, tokens_out: int = 0, used_fallback: bool = False, failed: bool = False) -> None:
        with self._lock:
            self.total_calls += 1
            self.total_latency_ms += latency_ms
            self.routing_counts[profile] = self.routing_counts.get(profile, 0) + 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            if used_fallback:
                self.fallback_count += 1
            if failed:
                self.provider_errors += 1

    def snapshot(self, ml_cache: TTLCache, rag_cache: TTLCache) -> dict[str, Any]:
        with self._lock:
            avg_ms = round(self.total_latency_ms / max(1, self.total_calls), 2)
            return {
                "total_calls": self.total_calls,
                "avg_latency_ms": avg_ms,
                "routing_counts": dict(self.routing_counts),
                "provider_errors": self.provider_errors,
                "fallback_count": self.fallback_count,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "ml_cache": {"hits": ml_cache.hits, "misses": ml_cache.misses},
                "rag_cache": {"hits": rag_cache.hits, "misses": rag_cache.misses},
            }


class ProviderGateway:
    """Executes completions across ordered providers with strict accuracy-preserving fallback."""

    def __init__(self, providers: list[LLMProviderAdapter], monitor: Optional[AIQualityMonitor] = None) -> None:
        self.providers = providers
        self.monitor = monitor or AIQualityMonitor()

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        route_decision: dict[str, Any],
        max_tokens: int = 750,
        temperature: float = 0.3,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        last_exc: Optional[Exception] = None
        for idx, prov in enumerate(self.providers):
            if idx > 0 and not route_decision.get("allow_downgrade_fallback", True):
                # Never silently switch to a lower-quality fallback when high accuracy is required
                break
            try:
                out = prov.complete(
                    messages,
                    model=route_decision["model_id"],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
                elapsed = (time.perf_counter() - t0) * 1000.0
                self.monitor.record_call(
                    profile=route_decision["profile"],
                    latency_ms=elapsed,
                    tokens_in=out["tokens_in"],
                    tokens_out=out["tokens_out"],
                    used_fallback=(idx > 0),
                )
                out["used_fallback"] = idx > 0
                return out
            except Exception as exc:
                last_exc = exc
                continue

        elapsed = (time.perf_counter() - t0) * 1000.0
        self.monitor.record_call(profile=route_decision["profile"], latency_ms=elapsed, failed=True)
        raise RuntimeError(f"Tous les fournisseurs éligibles ont échoué : {last_exc}")


def cache_key_for_series(series: list[float]) -> str:
    payload = json.dumps([round(float(x), 4) for x in series])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

