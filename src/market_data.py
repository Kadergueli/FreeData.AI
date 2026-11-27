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


_RAW_COLUMNS = "id,source_api,date_reference,indicateur,region,unite,valeur,notes_publiques"


def _rest_headers() -> dict:
    # v_clean_markets est en security_invoker et table_public a la RLS sans politique publique : la clé anon
    # ne voit aucune ligne. Lecture côté serveur uniquement, avec la clé privilégiée (jamais exposée au client),
    # comme pour les tables Gold privilégiées ; repli sur la clé de lecture si elle est seule configurée.
    key = settings.write_key
    return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}


def _edge_id(order: str) -> Optional[int]:
    resp = requests.get(
        f"{settings.supabase_url.rstrip('/')}/rest/v1/table_public",
        headers=_rest_headers(),
        params={"select": "id", "source_api": "in.(WFP,\"FEWS NET\")", "order": order, "limit": 1},
        timeout=25,
    )
    resp.raise_for_status()
    rows = resp.json()
    return int(rows[0]["id"]) if rows else None


def _fetch_id_range(bounds: tuple[int, int]) -> list[dict]:
    """Relevés WFP/FEWS NET dont id est dans [lo, hi) ; pagination par clé (coût constant par page).

    On filtre sur la table de base (indexée) et non sur la vue : la vue recalcule des expressions
    régulières sur toute la table à chaque requête (≈1,3 s), ce qui saturait Supabase.
    """
    lo, hi = bounds
    rows: list[dict] = []
    last = lo - 1
    for _ in range(40):
        resp = requests.get(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/table_public",
            headers=_rest_headers(),
            params=[
                ("select", _RAW_COLUMNS),
                ("source_api", 'in.(WFP,"FEWS NET")'),
                ("valeur", "not.is.null"),
                ("id", f"gt.{last}"),
                ("id", f"lt.{hi}"),
                ("order", "id"),
                ("limit", "1000"),
            ],
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < 1000:
            break
        last = int(batch[-1]["id"])
    return rows


def _load_history_rest() -> pd.DataFrame:
    """Charge les relevés WFP/FEWS NET (≈50 000 lignes) par plages d'id en parallèle, puis normalise."""
    from concurrent.futures import ThreadPoolExecutor

    from src.data_loader import drop_flagged_outliers, standardize_raw_markets, unify_commodity_case
    from src.market_intel import PRODUCTS

    lo, hi = _edge_id("id.asc"), _edge_id("id.desc")
    if lo is None or hi is None:
        raise ValueError(
            "Aucun relevé reçu depuis table_public (clé sans accès en lecture ? "
            "SUPABASE_SERVICE_ROLE_KEY doit être définie sur l'API)."
        )
    n_chunks = 8
    step = max(1, (hi - lo + 1) // n_chunks + 1)
    ranges = [(a, min(a + step, hi + 1)) for a in range(lo, hi + 1, step)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        chunks = list(pool.map(_fetch_id_range, ranges))
    rows = [r for chunk in chunks for r in chunk]
    if not rows:
        raise ValueError("Aucun relevé de prix reçu depuis table_public.")
    raw = pd.DataFrame(rows).rename(columns={
        "source_api": "source", "date_reference": "reference_date", "indicateur": "indicator",
        "unite": "unit", "valeur": "value", "notes_publiques": "notes",
    })
    df = unify_commodity_case(standardize_raw_markets(raw))
    if settings.exclude_flagged_outliers:
        df = drop_flagged_outliers(df)
    names = {n for meta in PRODUCTS.values() for n in meta["names"]}
    return df[df["commodity_std"].astype(str).str.lower().isin(names)].reset_index(drop=True)


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
