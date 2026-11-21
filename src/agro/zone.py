"""Pré-diagnostic agro-climatique de zone (Grand Public) : indicateurs d'un hub + prévisions de prix validées."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pandas as pd

from src.agro.indicators import HUBS, NASA_INDICATORS, normalize_hub

ZONE_TITLE = "Pré-diagnostic agro-climatique de zone"
RESOLUTION_NOTICE = (
    "Résolution zonale (hub régional) : ces indicateurs décrivent la zone autour de la ville, pas une parcelle. "
    "Pour un diagnostic de terrain avant achat, utilisez l'audit Agronome PRO."
)
MAX_STALENESS_MONTHS = 3
_MIN_HISTORY = 3  # années minimales pour situer une valeur dans son historique saisonnier

_LABELS = {
    "root_zone_soil_wetness": "Humidité du sol (zone racinaire)",
    "surface_soil_wetness": "Humidité du sol (surface)",
    "photosynthetically_active_radiation": "Rayonnement photosynthétique (PAR)",
}


def _months_between(ref: str, today: date) -> int:
    y, m = int(ref[:4]), int(ref[5:7])
    return (today.year - y) * 12 + (today.month - m)


def _provenance(row: pd.Series) -> dict[str, Any]:
    return {
        "source": row["source"], "license": row["license"], "reference_date": row["reference_date"],
        "spatial_resolution": row["spatial_resolution"], "confidence_level": row["confidence_level"],
    }


def hub_indicators(ind_df: pd.DataFrame, hub: str, *, today: Optional[date] = None) -> list[dict]:
    """Dernière valeur mensuelle NASA POWER du hub, située dans l'historique du même mois civil."""
    today = today or date.today()
    out: list[dict] = []
    sub = ind_df[(ind_df["region"] == hub) & (ind_df["indicator"].isin(NASA_INDICATORS))]
    for indicator, grp in sub.groupby("indicator"):
        grp = grp.sort_values("reference_date")
        last = grp.iloc[-1]
        same_month = grp[(grp["reference_date"].str[5:7] == last["reference_date"][5:7])
                         & (grp["reference_date"] != last["reference_date"])]["value"]
        hist = None
        if len(same_month) >= _MIN_HISTORY:
            hist = {
                "years_compared": int(len(same_month)),
                "mean": round(float(same_month.mean()), 3),
                "min": round(float(same_month.min()), 3),
                "max": round(float(same_month.max()), 3),
                "percentile": round(float((same_month < last["value"]).mean() * 100), 0),
            }
        age = _months_between(last["reference_date"], today)
        out.append({
            "indicator": indicator, "label": _LABELS.get(indicator, indicator), "unit": last["unit"],
            "value": round(float(last["value"]), 3), "history_same_month": hist,
            "months_since_reference": age, "stale": age > MAX_STALENESS_MONTHS,
            "provenance": _provenance(last),
        })
    return sorted(out, key=lambda d: d["indicator"])


def hub_price_forecasts(forecast_df: Optional[pd.DataFrame], hub: str, *, limit: int = 8) -> list[dict]:
    """Prévisions de prix validées (déjà filtrées par fraîcheur) de la province du hub, avec l'erreur historique réelle."""
    if forecast_df is None or forecast_df.empty or "province" not in forecast_df.columns:
        return []
    province = HUBS[hub].lower()
    df = forecast_df[forecast_df["province"].astype(str).str.lower() == province]
    out = []
    for r in df.to_dict(orient="records"):
        last = pd.to_numeric(r.get("value", r.get("last_observed_price")), errors="coerce")
        mae = pd.to_numeric(r.get("hist_mae"), errors="coerce")
        fc = pd.to_numeric(r.get("forecast_t1"), errors="coerce")
        if pd.isna(last) or pd.isna(fc) or pd.isna(mae) or last <= 0:
            continue  # pas de prévision sans erreur historique mesurée
        out.append({
            "commodity": r.get("commodity_std"), "market": r.get("market_name"),
            "last_observed_month": str(r.get("last_observed_month")), "forecast_month": str(r.get("forecast_month")),
            "last_observed_price": round(float(last), 1), "forecast_t1": round(float(fc), 1),
            "hist_error_pct": round(float(mae) / float(last) * 100, 1),
            "forecast_quality": r.get("forecast_quality") or "standard",
            "interval_status": r.get("interval_status") or "uncalibrated",
            "error_definition": "Erreur absolue moyenne historique du modèle, rapportée au dernier prix observé (en %).",
            "source": r.get("source"),
        })
    out.sort(key=lambda d: d["hist_error_pct"])
    return out[:limit]


def build_zone_prediagnosis(
    ind_df: pd.DataFrame, hub: str, forecast_df: Optional[pd.DataFrame] = None, *, today: Optional[date] = None,
) -> dict[str, Any]:
    name = normalize_hub(hub)
    if name is None:
        raise KeyError(f"Hub inconnu : {hub!r}")
    indicators = hub_indicators(ind_df, name, today=today)
    if not indicators:
        raise LookupError(f"Aucun indicateur disponible pour le hub {name}.")
    return {
        "title": ZONE_TITLE, "hub": name, "region": HUBS[name], "country_code": "TCD",
        "indicators": indicators, "price_forecasts": hub_price_forecasts(forecast_df, name),
        "resolution_notice": RESOLUTION_NOTICE, "pro_audit_available": True,
        "disclaimer": "Information d'aide à la décision issue de modèles satellitaires ; ce n'est ni une analyse de parcelle ni un conseil agronomique.",
    }
