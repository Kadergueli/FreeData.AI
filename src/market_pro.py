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

    def purge_owner(self, owner_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM market_watchlists WHERE owner_id = ?",
                (owner_id,),
            )
        return int(cur.rowcount or 0)


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
                pred = float(sub["forecast_t1"].dropna().mean()) if "forecast_t1" in sub.columns and not sub["forecast_t1"].dropna().empty else None
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
        pred_avg = float(sub["forecast_t1"].dropna().mean()) if "forecast_t1" in sub.columns and not sub["forecast_t1"].dropna().empty else None
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
            "source": "PAM-WFP (prévision FreeData.AI, sans NASA POWER)",
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
    if "province" not in forecast_df.columns or "forecast_t1" not in forecast_df.columns:
        return []
    target_crops = [_normalize_crop_id(crop_id)] if crop_id else list(SUPPORTED_AGRO_CROPS)
    opportunities: list[dict[str, Any]] = []
    for cid in target_crops:
        meta = SUPPORTED_AGRO_CROPS[cid]
        sub = forecast_df[forecast_df["commodity_std"] == meta["commodity_std"]]
        if sub.empty:
            continue
        by_prov = sub.groupby("province")["forecast_t1"].mean().dropna()
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
            "source": "PAM-WFP (prévision FreeData.AI)",
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
                round(float(r["forecast_t1"]), 1) if r.get("forecast_t1") is not None else "",
                round(float(mape), 2) if isinstance(mape, (int, float)) else "",
                r.get("source", "PAM-WFP / FreeData.AI"),
                "Attribution Required (FreeData.td)",
                "market_province",
                "ML_Backtested_70_30",
            ])
    return buf.getvalue()


def compute_spatial_arbitrage_detailed(
    forecast_df: Any,
    track_record: Optional[dict[str, Any]],
    *,
    crop_id: str,
    transport_cost_xaf_kg: Optional[float] = None,
    tonnage: Optional[float] = None,
    limit: int = 12,
) -> dict[str, Any]:
    """Arbitrage spatial détaillé entre provinces/pôles avec marge nette, ROI et MAPE hors-temps."""
    cid = _normalize_crop_id(crop_id)
    meta = SUPPORTED_AGRO_CROPS[cid]
    comm = meta["commodity_std"]
    rec = (track_record or {}).get(comm) or {}
    mape = rec.get("mape_pct") if rec.get("mape_pct") is not None else rec.get("MAPE_pct")
    mape_val = round(float(mape), 2) if isinstance(mape, (int, float)) else None

    if forecast_df is None or getattr(forecast_df, "empty", True) or "province" not in forecast_df.columns:
        return {
            "crop_id": cid,
            "commodity_std": comm,
            "label_fr": meta["label_fr"],
            "historical_mape_pct": mape_val,
            "routes": [],
            "sources": ["WFP", "FEWS NET", "NASA POWER Agro"],
            "license": "Attribution Required (FreeData.td) / Public Domain (NASA)",
        }

    sub = forecast_df[forecast_df["commodity_std"] == comm]
    if sub.empty:
        return {
            "crop_id": cid,
            "commodity_std": comm,
            "label_fr": meta["label_fr"],
            "historical_mape_pct": mape_val,
            "routes": [],
            "sources": ["WFP", "FEWS NET", "NASA POWER Agro"],
            "license": "Attribution Required (FreeData.td) / Public Domain (NASA)",
        }

    by_prov = sub.groupby("province")["forecast_t1"].mean().dropna().sort_values()
    fc_month = (
        str(sub["forecast_month"].dropna().iloc[0])
        if "forecast_month" in sub.columns and not sub["forecast_month"].dropna().empty
        else None
    )
    provs = list(by_prov.items())
    routes: list[dict[str, Any]] = []
    for i, (orig_prov, orig_px) in enumerate(provs):
        for dest_prov, dest_px in reversed(provs[i + 1 :]):
            spread = float(dest_px) - float(orig_px)
            if spread <= 0 or orig_px <= 0:
                continue
            net_kg = (spread - float(transport_cost_xaf_kg)) if transport_cost_xaf_kg is not None else None
            denom = float(orig_px) + (float(transport_cost_xaf_kg) if transport_cost_xaf_kg is not None else 0.0)
            roi_pct = round(((net_kg if net_kg is not None else spread) / denom) * 100.0, 1) if denom > 0 else None
            total_net_xaf = (
                round((net_kg if net_kg is not None else spread) * float(tonnage) * 1000.0, 0)
                if tonnage is not None
                else None
            )
            spread_bag = round(spread * 100.0)
            if transport_cost_xaf_kg is not None:
                rec_text = (
                    f"Arbitrage positif (+{net_kg:.1f} FCFA/kg net). Vérifier la disponibilité du fret et l'état de l'axe avant expédition."
                    if net_kg is not None and net_kg > 0
                    else f"Arbitrage déficitaire ({net_kg:.1f} FCFA/kg net) : le coût de transport saisi dépasse l'écart de prix."
                )
            else:
                rec_text = (
                    f"Écart brut +{spread:.1f} FCFA/kg (+{spread_bag:,} FCFA/sac 100 kg). "
                    f"Carburant/état des routes non modélisés : vérifier que le fret réel reste < {spread:.1f} FCFA/kg avant expédition."
                ).replace(",", " ")
            routes.append({
                "origin_province": str(orig_prov),
                "dest_province": str(dest_prov),
                "origin_predicted_xaf_kg": round(float(orig_px), 1),
                "dest_predicted_xaf_kg": round(float(dest_px), 1),
                "spread_xaf_kg": round(spread, 1),
                "spread_per_100kg_bag_xaf": spread_bag,
                "breakeven_transport_xaf_kg": round(spread, 1),
                "transport_cost_xaf_kg": round(float(transport_cost_xaf_kg), 1) if transport_cost_xaf_kg is not None else None,
                "net_margin_xaf_kg": round(net_kg, 1) if net_kg is not None else None,
                "tonnage": tonnage,
                "estimated_net_margin_xaf": total_net_xaf,
                "roi_pct": roi_pct,
                "forecast_month": fc_month,
                "recommendation": rec_text,
            })

    routes.sort(
        key=lambda r: r["net_margin_xaf_kg"] if r["net_margin_xaf_kg"] is not None else r["spread_xaf_kg"],
        reverse=True,
    )
    top_routes = routes[:limit]
    recommendations: list[str] = []
    if top_routes:
        best = top_routes[0]
        recommendations.append(
            f"Corridor prioritaire : {best['origin_province']} → {best['dest_province']} "
            f"(écart brut {best['spread_xaf_kg']} FCFA/kg, soit +{best['spread_per_100kg_bag_xaf']:,} FCFA/sac 100 kg).".replace(",", " ")
        )
        recommendations.append(
            f"Seuil de rentabilité transport : ne pas engager d'expédition si le coût réel (carburant, péages, manutention) dépasse {best['breakeven_transport_xaf_kg']} FCFA/kg."
        )
    if mape_val is not None:
        recommendations.append(
            f"Prudence modèle : intégrer une marge d'incertitude de ±{mape_val}% (MAPE hors-temps) dans le calcul du prix de revente."
        )
    return {
        "crop_id": cid,
        "commodity_std": comm,
        "label_fr": meta["label_fr"],
        "historical_mape_pct": mape_val,
        "backtest_verdict": rec.get("verdict"),
        "forecast_month": fc_month,
        "routes": top_routes,
        "recommendations": recommendations,
        "sources": ["WFP", "FEWS NET", "NASA POWER Agro"],
        "license": "Attribution Required (FreeData.td) / Public Domain (NASA)",
        "spatial_resolution": "regional_city_hub / market_province",
        "confidence_level": "ML_Backtested_70_30",
    }


def compute_agro_credit_passport(
    *,
    province: str,
    crop_id: str,
    area_hectares: float,
    loan_amount_xaf: float,
    hist_df: Any,
    forecast_df: Any,
    passport_df: Any,
    regional_agro_rows: list[dict[str, Any]],
    national_agro_rows: list[dict[str, Any]],
    disclaimer: str,
) -> dict[str, Any]:
    """Profil Credit Passport Agro : rendement World Bank 2020-2024, DSCR sous 3 scénarios et fréquence années sèches."""
    from src.agro_engine import build_zone_profile
    from src.agro_indicators import HUB_PROVINCE, canonical_region, national_indicator_key

    cid = _normalize_crop_id(crop_id)
    meta = SUPPORTED_AGRO_CROPS[cid]
    comm = meta["commodity_std"]

    # Résolution province <-> pôle NASA POWER
    hub = canonical_region(province)
    if hub and hub != "national":
        prov_name = HUB_PROVINCE.get(hub, province)
    else:
        prov_name = province.strip()
        hub = next((h for h, p in HUB_PROVINCE.items() if p.lower() == prov_name.lower()), None)

    # 1. Rendement céréalier national World Bank (moyenne 2020-2024)
    yield_vals = [
        float(r["value"])
        for r in national_agro_rows
        if national_indicator_key(r["indicator"]) == "cereal_yield" and 2020 <= int(r["reference_date"][:4]) <= 2024
    ]
    yield_mean_kg_ha = round(sum(yield_vals) / len(yield_vals), 1) if yield_vals else None
    est_prod_kg = round(float(area_hectares) * yield_mean_kg_ha, 1) if yield_mean_kg_ha is not None else None

    # 2. Fréquence des années sèches NASA POWER Agro (< 0.45 en juillet-août)
    dry_info = {"critical_july_aug_years": None, "observed_july_aug_years": 0, "dry_year_frequency_pct": None}
    if hub and regional_agro_rows:
        zp = build_zone_profile(hub, regional_agro_rows, national_agro_rows)
        sig = zp.get("hydric_risk_signals") or {}
        crit = sig.get("critical_july_aug_years")
        obs_y = sig.get("observed_july_aug_years") or 0
        dry_info = {
            "hub": hub,
            "critical_july_aug_years": crit,
            "observed_july_aug_years": obs_y,
            "dry_year_frequency_pct": round(crit / obs_y * 100.0, 1) if (crit is not None and obs_y > 0) else None,
        }

    # 3. Prix pour les 3 scénarios vérifiables
    stress_px: Optional[float] = None
    central_px: Optional[float] = None
    storage_px: Optional[float] = None
    if hist_df is not None and not getattr(hist_df, "empty", True):
        h_comm = hist_df[hist_df["commodity_std"] == comm]
        h_prov = h_comm[h_comm["province"].astype(str).str.lower() == prov_name.lower()]
        h_scope = h_prov if not h_prov.empty else h_comm
        if not h_scope.empty and "value" in h_scope.columns:
            storage_px = round(float(h_scope["value"].dropna().median()), 1) if not h_scope["value"].dropna().empty else None
            if "year_month" in h_scope.columns:
                recent = h_scope[h_scope["year_month"].astype(str) >= "2024-01"]
                if not recent.empty and not recent["value"].dropna().empty:
                    stress_px = round(float(recent["value"].dropna().min()), 1)
            if stress_px is None and not h_scope["value"].dropna().empty:
                stress_px = round(float(h_scope["value"].dropna().min()), 1)

    if forecast_df is not None and not getattr(forecast_df, "empty", True):
        f_comm = forecast_df[forecast_df["commodity_std"] == comm]
        f_prov = f_comm[f_comm["province"].astype(str).str.lower() == prov_name.lower()]
        f_scope = f_prov if not f_prov.empty else f_comm
        if not f_scope.empty and "forecast_t1" in f_scope.columns and not f_scope["forecast_t1"].dropna().empty:
            central_px = round(float(f_scope["forecast_t1"].dropna().mean()), 1)

    def _scenario(name: str, desc: str, px: Optional[float]) -> dict[str, Any]:
        rev = round(est_prod_kg * px, 0) if (est_prod_kg is not None and px is not None) else None
        dscr = round(rev / float(loan_amount_xaf), 2) if (rev is not None and loan_amount_xaf > 0) else None
        return {
            "scenario": name,
            "description": desc,
            "price_xaf_kg": px,
            "estimated_revenue_xaf": rev,
            "dscr": dscr,
        }

    scenarios = [
        _scenario("stress_floor", "Plancher de stress (prix min observé 2024–2026)", stress_px),
        _scenario("central_ml", "Scénario central (prévision ML t+1)", central_px),
        _scenario("storage_90d", "Arbitrage stockage 90 jours (médiane historique)", storage_px),
    ]

    # 4. Score Credit Passport existant si disponible
    cp_match = None
    if passport_df is not None and not getattr(passport_df, "empty", True):
        p_sub = passport_df[
            (passport_df["commodity_std"] == comm)
            & (passport_df["province"].astype(str).str.lower() == prov_name.lower())
        ]
        if not p_sub.empty:
            r0 = p_sub.iloc[0]
            cp_match = {
                "credit_score": float(r0["credit_score"]) if "credit_score" in r0 else None,
                "risk_grade": str(r0["risk_grade"]) if "risk_grade" in r0 else None,
                "ltv_ratio": float(r0["ltv_ratio"]) if "ltv_ratio" in r0 else None,
            }

    return {
        "profile": "agro",
        "province": prov_name,
        "crop_id": cid,
        "commodity_std": comm,
        "label_fr": meta["label_fr"],
        "area_hectares": float(area_hectares),
        "loan_amount_xaf": float(loan_amount_xaf),
        "cereal_yield_mean_2020_2024_kg_ha": yield_mean_kg_ha,
        "estimated_production_kg": est_prod_kg,
        "dry_years_risk": dry_info,
        "market_credit_passport": cp_match,
        "scenarios": scenarios,
        "sources": ["WFP", "FEWS NET", "NASA POWER Agro", "World Bank"],
        "licenses": ["CC BY-IGO 3.0", "Attribution Required", "Public Domain (NASA)", "CC BY 4.0"],
        "spatial_resolution": "province / regional_city_hub",
        "confidence_level": "Composite_Historical_ML_Satellite",
        "disclaimer": disclaimer,
    }

