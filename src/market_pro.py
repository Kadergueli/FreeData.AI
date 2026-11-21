"""Marché PRO (Étape 4 / P3) : Prévisions 4 cultures avec MAPE, Watchlists & alertes, Arbitrage inter-provinces, Export CSV.

Limité aux 4 cultures validées : millet, sorghum, maize, groundnut_raw.
Toute sortie inclut source, licence, période de référence, résolution spatiale et niveau de confiance.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src import db as _db
from src.agro_engine import SUPPORTED_AGRO_CROPS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_crop_id(raw: str) -> str:
    clean = (raw or "").strip().lower()
    if clean in SUPPORTED_AGRO_CROPS:
        return clean
    for cid, meta in SUPPORTED_AGRO_CROPS.items():
        if meta["commodity_std"].lower() == clean or meta["label_fr"].lower() == clean:
            return cid
    raise ValueError(f"Culture non supportée en Marché PRO V1 : {raw!r}. Cultures autorisées : {', '.join(SUPPORTED_AGRO_CROPS)}.")


class MarketWatchlistStore:
    """Watchlists et alertes de seuils de prix isolées par `owner_id`."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        database_url: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = (
            _db.validate_schema(schema)
            if schema
            else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        )
        self.db_path = Path(db_path or os.getenv("FREEDATA_BILLING_DB_PATH", "data/freedata_billing.db"))
        if not self._pg_url:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_watchlists (
                    watch_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    crop_id TEXT NOT NULL,
                    commodity_std TEXT NOT NULL,
                    province TEXT NOT NULL DEFAULT '',
                    market_name TEXT NOT NULL DEFAULT '',
                    threshold_xaf_kg REAL NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'above',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_market_watch_owner
                    ON market_watchlists(owner_id, created_at DESC);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    def create_watch(
        self,
        owner_id: str,
        *,
        crop_id: str,
        threshold_xaf_kg: float,
        direction: str = "above",
        province: str = "",
        market_name: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        cid = _normalize_crop_id(crop_id)
        comm = SUPPORTED_AGRO_CROPS[cid]["commodity_std"]
        dir_clean = (direction or "above").strip().lower()
        if dir_clean not in ("above", "below"):
            raise ValueError("Direction invalide ('above' ou 'below').")
        if threshold_xaf_kg <= 0:
            raise ValueError("Le seuil de prix (XAF/kg) doit être strictement positif.")
        wid = f"W-{uuid.uuid4().hex[:10].upper()}"
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_watchlists (
                    watch_id, owner_id, crop_id, commodity_std, province,
                    market_name, threshold_xaf_kg, direction, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wid,
                    owner_id,
                    cid,
                    comm,
                    (province or "").strip()[:80],
                    (market_name or "").strip()[:80],
                    float(threshold_xaf_kg),
                    dir_clean,
                    (note or "").strip()[:240],
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM market_watchlists WHERE watch_id = ? AND owner_id = ?",
                (wid, owner_id),
            ).fetchone()
        return dict(row)

    def list_watches(self, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_watchlists WHERE owner_id = ? ORDER BY created_at DESC LIMIT 100",
                (owner_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_watch(self, owner_id: str, watch_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM market_watchlists WHERE watch_id = ? AND owner_id = ?",
                (watch_id, owner_id),
            )
        return (cur.rowcount or 0) > 0


def evaluate_watchlists(watches: list[dict[str, Any]], forecast_df: Any) -> list[dict[str, Any]]:
    """Évalue chaque alerte de seuil par rapport aux prix observés/prévus actuels."""
    out: list[dict[str, Any]] = []
    has_df = forecast_df is not None and not getattr(forecast_df, "empty", True)
    for w in watches:
        item = dict(w)
        item["label_fr"] = SUPPORTED_AGRO_CROPS.get(w["crop_id"], {}).get("label_fr", w["commodity_std"])
        item["triggered"] = False
        item["current_xaf_kg"] = None
        item["predicted_xaf_kg"] = None
        item["forecast_month"] = None
        if has_df:
            sub = forecast_df[forecast_df["commodity_std"] == w["commodity_std"]]
            if w.get("province"):
                sub = sub[sub["province"].astype(str).str.lower() == w["province"].lower()]
            if w.get("market_name") and "market_name" in sub.columns:
                sub = sub[sub["market_name"].astype(str).str.lower() == w["market_name"].lower()]
            if not sub.empty:
                pred = float(sub["predicted_price"].dropna().mean()) if "predicted_price" in sub.columns and not sub["predicted_price"].dropna().empty else None
                obs_col = "last_observed_price" if "last_observed_price" in sub.columns else ("value" if "value" in sub.columns else None)
                obs = float(sub[obs_col].dropna().mean()) if obs_col and not sub[obs_col].dropna().empty else None
                ref_price = pred if pred is not None else obs
                item["current_xaf_kg"] = round(obs, 1) if obs is not None else None
                item["predicted_xaf_kg"] = round(pred, 1) if pred is not None else None
                if "forecast_month" in sub.columns and not sub["forecast_month"].dropna().empty:
                    item["forecast_month"] = str(sub["forecast_month"].dropna().iloc[0])
                if ref_price is not None:
                    thr = float(w["threshold_xaf_kg"])
                    item["triggered"] = (ref_price >= thr) if w["direction"] == "above" else (ref_price <= thr)
        out.append(item)
    return out


def build_validated_forecasts_overview(forecast_df: Any, track_record: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Prévisions Delta-Ridge ML sur les 4 cultures validées avec affichage obligatoire du MAPE historique."""
    if forecast_df is None or getattr(forecast_df, "empty", True):
        return []
    tr = track_record or {}
    items: list[dict[str, Any]] = []
    obs_col = "last_observed_price" if "last_observed_price" in forecast_df.columns else ("value" if "value" in forecast_df.columns else None)
    for crop_id, meta in SUPPORTED_AGRO_CROPS.items():
        comm = meta["commodity_std"]
        sub = forecast_df[forecast_df["commodity_std"] == comm]
        if sub.empty:
            continue
        pred_avg = float(sub["predicted_price"].dropna().mean()) if "predicted_price" in sub.columns and not sub["predicted_price"].dropna().empty else None
        obs_avg = float(sub[obs_col].dropna().mean()) if obs_col and not sub[obs_col].dropna().empty else None
        fc_month = str(sub["forecast_month"].dropna().iloc[0]) if "forecast_month" in sub.columns and not sub["forecast_month"].dropna().empty else None
        rec = tr.get(comm) or {}
        mape_pct = rec.get("mape_pct") if rec.get("mape_pct") is not None else rec.get("MAPE_pct")
        items.append({
            "crop_id": crop_id,
            "commodity_std": comm,
            "label_fr": meta["label_fr"],
            "series_count": int(len(sub)),
            "provinces_count": int(sub["province"].nunique()) if "province" in sub.columns else 0,
            "last_observed_xaf_kg": round(obs_avg, 1) if obs_avg is not None else None,
            "predicted_xaf_kg": round(pred_avg, 1) if pred_avg is not None else None,
            "forecast_month": fc_month,
            "historical_mape_pct": round(float(mape_pct), 2) if isinstance(mape_pct, (int, float)) else None,
            "vs_naive_pct": rec.get("vs_naive_pct"),
            "backtest_verdict": rec.get("verdict"),
            "source": "FreeData.td / PAM-WFP + NASA POWER (Delta-Ridge ML)",
            "license": "Attribution Required (FreeData.td)",
            "spatial_resolution": "market_province",
            "confidence_level": "ML_Backtested_70_30",
        })
    return items


def compute_inter_province_arbitrage(
    forecast_df: Any,
    *,
    crop_id: Optional[str] = None,
    min_spread_xaf: float = 15.0,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Calcule les meilleurs écarts de prix entre provinces (excédentaire -> déficitaire) sur les 4 cultures."""
    if forecast_df is None or getattr(forecast_df, "empty", True):
        return []
    if "province" not in forecast_df.columns or "predicted_price" not in forecast_df.columns:
        return []
    target_crops = [_normalize_crop_id(crop_id)] if crop_id else list(SUPPORTED_AGRO_CROPS)
    opportunities: list[dict[str, Any]] = []
    for cid in target_crops:
        meta = SUPPORTED_AGRO_CROPS[cid]
        sub = forecast_df[forecast_df["commodity_std"] == meta["commodity_std"]]
        if sub.empty:
            continue
        by_prov = sub.groupby("province")["predicted_price"].mean().dropna()
        if len(by_prov) < 2:
            continue
        origin_prov = str(by_prov.idxmin())
        dest_prov = str(by_prov.idxmax())
        origin_px = float(by_prov.min())
        dest_px = float(by_prov.max())
        spread = dest_px - origin_px
        if spread < min_spread_xaf or origin_px <= 0:
            continue
        fc_month = str(sub["forecast_month"].dropna().iloc[0]) if "forecast_month" in sub.columns and not sub["forecast_month"].dropna().empty else None
        opportunities.append({
            "crop_id": cid,
            "label_fr": meta["label_fr"],
            "commodity_std": meta["commodity_std"],
            "origin_province": origin_prov,
            "dest_province": dest_prov,
            "origin_predicted_xaf_kg": round(origin_px, 1),
            "dest_predicted_xaf_kg": round(dest_px, 1),
            "spread_xaf_kg": round(spread, 1),
            "spread_pct": round(spread / origin_px * 100.0, 1),
            "forecast_month": fc_month,
            "source": "FreeData.td / PAM-WFP (Delta-Ridge ML)",
            "license": "Attribution Required (FreeData.td)",
            "note": "Écart brut hors coût de transport et pertes logistiques.",
        })
    opportunities.sort(key=lambda o: o["spread_xaf_kg"], reverse=True)
    return opportunities[:limit]


def export_validated_forecasts_csv(
    forecast_df: Any,
    track_record: Optional[dict[str, Any]] = None,
    *,
    crop_id: Optional[str] = None,
) -> str:
    """Export CSV institutionnel des prévisions validées avec provenance, licence et MAPE."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "crop_id", "commodity_std", "province", "market_name", "forecast_month",
        "last_observed_xaf_kg", "predicted_xaf_kg", "historical_mape_pct",
        "source", "license", "spatial_resolution", "confidence_level",
    ])
    if forecast_df is None or getattr(forecast_df, "empty", True):
        return buf.getvalue()
    tr = track_record or {}
    target_crops = [_normalize_crop_id(crop_id)] if crop_id else list(SUPPORTED_AGRO_CROPS)
    obs_col = "last_observed_price" if "last_observed_price" in forecast_df.columns else ("value" if "value" in forecast_df.columns else None)
    for cid in target_crops:
        comm = SUPPORTED_AGRO_CROPS[cid]["commodity_std"]
        sub = forecast_df[forecast_df["commodity_std"] == comm]
        rec = tr.get(comm) or {}
        mape = rec.get("mape_pct") if rec.get("mape_pct") is not None else rec.get("MAPE_pct")
        for _, r in sub.iterrows():
            writer.writerow([
                cid,
                comm,
                r.get("province", ""),
                r.get("market_name", ""),
                r.get("forecast_month", ""),
                round(float(r[obs_col]), 1) if obs_col and r.get(obs_col) is not None else "",
                round(float(r["predicted_price"]), 1) if r.get("predicted_price") is not None else "",
                round(float(mape), 2) if isinstance(mape, (int, float)) else "",
                r.get("source", "FreeData.td / PAM-WFP"),
                "Attribution Required (FreeData.td)",
                "market_province",
                "ML_Backtested_70_30",
            ])
    return buf.getvalue()

