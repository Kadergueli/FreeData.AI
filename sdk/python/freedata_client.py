"""Lightweight Python SDK for FreeData.AI Data Products, ML, and RAG APIs."""
from __future__ import annotations

from typing import Any, Optional

import requests


class FreeDataClient:
    """Thin HTTP wrapper around the FreeData.AI REST API (no duplicated business logic)."""

    def __init__(self, base_url: str, *, api_key: Optional[str] = None, user_id: Optional[str] = None, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
            h["X-Premium-Key"] = self.api_key
        if self.user_id:
            h["X-User-Id"] = self.user_id
        return h

    def list_products(self) -> list[dict[str, Any]]:
        r = requests.get(f"{self.base_url}/api/v1/products", timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("products", [])

    def export_product(self, product_id: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        r = requests.get(
            f"{self.base_url}/api/v1/products/{product_id}/export",
            params={"limit": limit, "offset": offset, "format": "json"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def predict_prices(self, series_prices: list[float]) -> dict[str, Any]:
        r = requests.post(
            f"{self.base_url}/api/v1/ml/predict",
            headers=self._headers(),
            json={"series_prices": series_prices},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def rag_search(self, query: str, *, top_k: int = 4) -> list[dict[str, Any]]:
        r = requests.post(
            f"{self.base_url}/api/v1/rag/search",
            headers=self._headers(),
            json={"query": query, "top_k": top_k},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("hits", [])

