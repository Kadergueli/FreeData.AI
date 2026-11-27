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
_FAILURE_TTL_SECONDS = 20  # un échec n'est pas rejoué à chaque requête
_cache: dict[str, tuple[float, Optional[pd.DataFrame]]] = {}
_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_status: dict[str, dict] = {}


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _status.clear()


def _short_reason(exc: Exception) -> str:
    """Raison d'échec lisible et sûre à afficher : jamais d'URL, de clé ni de contenu de réponse."""
    if isinstance(exc, requests.exceptions.Timeout):
        return "délai dépassé en lisant Supabase"
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code in (401, 403):
            return f"accès refusé par Supabase (HTTP {code}) : vérifier SUPABASE_SERVICE_ROLE_KEY"
        return f"erreur Supabase (HTTP {code})"
    if isinstance(exc, requests.exceptions.RequestException):
        return "Supabase injoignable"
    if isinstance(exc, ValueError):
        return str(exc)[:160]
    return f"erreur interne ({type(exc).__name__})"


def history_status() -> dict:
    """État du chargement de l'historique : loading / loaded / error, sans donnée sensible."""
    with _lock:
        st = dict(_status.get("price_history", {}))
        entry = _cache.get("price_history")
    rows = int(len(entry[1])) if entry and entry[1] is not None else 0
    return {"state": st.get("state", "idle"), "rows": rows, "error": st.get("error"), "seconds": st.get("seconds")}


def is_loading(key: str = "price_history") -> bool:
    with _lock:
        return _status.get(key, {}).get("state") == "loading"


def _cached(key: str, loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """Cache TTL avec chargement unique : les requêtes simultanées attendent la première au lieu de recharger
    chacune les données (la mémoire d'une instance gratuite ne supporte pas plusieurs chargements en parallèle)."""

    def _hit() -> Optional[pd.DataFrame]:
        with _lock:
            entry = _cache.get(key)
            if entry and entry[0] > time.time():
                return entry[1] if entry[1] is not None else pd.DataFrame()
        return None

    found = _hit()
    if found is not None:
        return found
    with _lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        found = _hit()  # un autre thread a peut-être chargé pendant l'attente
        if found is not None:
            return found
        started = time.time()
        with _lock:
            _status[key] = {"state": "loading", "error": None, "seconds": None}
        try:
            value = loader()
            ttl, stored = CACHE_TTL_SECONDS, value
            with _lock:
                _status[key] = {"state": "loaded", "error": None, "seconds": round(time.time() - started, 1)}
            logger.info("Chargement %s terminé : %d lignes en %.1f s.", key, len(value), time.time() - started)
        except Exception as exc:  # noqa: BLE001 - dégradation voulue
            reason = _short_reason(exc)
            logger.warning("Chargement %s impossible : %s", key, reason)
            value, ttl, stored = pd.DataFrame(), _FAILURE_TTL_SECONDS, None
            with _lock:
                _status[key] = {"state": "error", "error": reason, "seconds": round(time.time() - started, 1)}
        with _lock:
            _cache[key] = (time.time() + ttl, stored)
        return value


_PANEL_VIEW = "mv_market_panel"


def _panel_to_frame(rows: list[dict]) -> pd.DataFrame:
    """Reconstruit un tableau long (source, province, market_name, commodity_std, year_month, value) depuis le panneau."""
    recs = []
    for r in rows:
        for month, price in zip(r.get("months") or [], r.get("prices") or []):
            if price is None:
                continue
            recs.append((r["province"], r["market_name"], r["commodity"], pd.Period(str(month)[:7], freq="M"), float(price)))
    df = pd.DataFrame(recs, columns=["province", "market_name", "commodity_std", "year_month", "value"])
    df["source"] = "panel"
    df["is_flagged_outlier"] = 0
    return df[["source", "province", "market_name", "commodity_std", "year_month", "value", "is_flagged_outlier"]]


def _load_history_rest() -> pd.DataFrame:
    """Lit le panneau pré-agrégé `mv_market_panel` (~700 lignes, 1 requête) : voir sql/18_market_intel_panel.sql."""
    key = settings.read_key
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    rows: list[dict] = []
    for page in range(10):
        resp = requests.get(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/{_PANEL_VIEW}",
            headers=headers,
            params={"select": "commodity,province,market_name,months,prices", "order": "commodity,province,market_name",
                    "limit": 1000, "offset": page * 1000},
            timeout=25,
        )
        if resp.status_code == 404:
            raise ValueError("Panneau de prix absent : appliquer sql/18_market_intel_panel.sql dans Supabase.")
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < 1000:
            break
    if not rows:
        raise ValueError("Panneau de prix vide : exécuter REFRESH MATERIALIZED VIEW public.mv_market_panel.")
    return _panel_to_frame(rows)


def load_price_history() -> pd.DataFrame:
    """Historique des prix de détail (XAF/kg), colonnes : source, province, market_name, commodity_std, year_month, value."""
    from src.data_loader import load_clean_markets

    if settings.data_backend == "supabase_rest":
        return _cached("price_history", _load_history_rest)
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
