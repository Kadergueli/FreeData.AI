"""Accès aux données de l'Intelligence marché : historique de prix local et séries mondiales.

En production (mode « gold_fast_read »), l'état ne contient pas l'historique des prix : on le charge à la demande
depuis Supabase (vue `v_clean_markets`) avec un cache mémoire à durée de vie limitée. Les séries mondiales viennent de
`v_world_prices` (voir sql/17_market_intel_views.sql) ; si la vue n'existe pas, on renvoie un tableau vide et les
modules concernés indiquent « indisponible » au lieu d'échouer.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import pandas as pd
import requests

from src.config import settings

logger = logging.getLogger("freedata.market_data")

CACHE_TTL_SECONDS = 6 * 3600
_FAILURE_TTL_SECONDS = 120  # un échec n'est pas rejoué à chaque requête
_cache: dict[str, tuple[float, Optional[pd.DataFrame]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key: str, loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1] if hit[1] is not None else pd.DataFrame()
    try:
        value = loader()
        with _lock:
            _cache[key] = (now + CACHE_TTL_SECONDS, value)
        return value
    except Exception as exc:  # noqa: BLE001 - dégradation voulue
        logger.warning("Chargement %s impossible : %s", key, exc)
        with _lock:
            _cache[key] = (now + _FAILURE_TTL_SECONDS, None)
        return pd.DataFrame()


def load_price_history() -> pd.DataFrame:
    """Historique des prix de détail (XAF/kg), colonnes : source, province, market_name, commodity_std, year_month, value."""
    from src.data_loader import load_clean_markets

    return _cached("price_history", load_clean_markets)


def _fetch_rest_view(view: str, select: str, order: str) -> pd.DataFrame:
    base = (settings.supabase_url or "").rstrip("/")
    key = settings.read_key
    if not base or not key:
        return pd.DataFrame()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    rows: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(
            f"{base}/rest/v1/{view}",
            headers=headers,
            params={"select": select, "order": order, "limit": 1000, "offset": offset},
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < 1000 or offset > 50_000:
            break
        offset += 1000
    return pd.DataFrame(rows)


def load_world_prices() -> pd.DataFrame:
    """Prix mondiaux mensuels (Banque mondiale, Pink Sheet). Colonnes : month, indicator, value, unit."""

    def _load() -> pd.DataFrame:
        df = _fetch_rest_view("v_world_prices", "month_date,indicator,value,unit", "month_date")
        if df.empty:
            return df
        df["month"] = pd.to_datetime(df["month_date"]).dt.to_period("M")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])[["month", "indicator", "value", "unit"]]

    return _cached("world_prices", _load)


def load_macro_context() -> pd.DataFrame:
    """Indicateurs annuels (commerce extérieur du Tchad). Colonnes : year, indicator, value, unit."""

    def _load() -> pd.DataFrame:
        df = _fetch_rest_view("v_macro_context", "year_date,indicator,value,unit", "year_date")
        if df.empty:
            return df
        df["year"] = pd.to_datetime(df["year_date"]).dt.year
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])[["year", "indicator", "value", "unit"]]

    return _cached("macro_context", _load)
