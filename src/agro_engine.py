"""Moteur agro-climatique déterministe (V1) : anomalies d'humidité des sols et alertes de déficit hydrique.

Principes :
- uniquement les indicateurs réellement ingérés (humidité racinaire, humidité de surface, PAR) ;
- AUCUNE température ni précipitation en V1 (absentes du jeu de données) ;
- anomalie = écart à la normale 2020–2023 du MÊME mois calendaire, calculée seulement si ≥ 3 années de référence ;
- les seuils d'alerte sont des repères de lecture indicatifs (non calibrés sur des rendements) et sont exposés dans la réponse.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Optional

from src.agro_indicators import (
    HUB_PROVINCE,
    HUBS,
    NATIONAL,
    build_provenance,
    canonical_region,
    national_indicator_key,
    regional_indicator_key,
)

BASELINE_YEARS: tuple[int, int] = (2020, 2023)
MIN_BASELINE_YEARS = 3
MODERATE_DEFICIT_PCT = -20.0
SEVERE_DEFICIT_PCT = -35.0
STALE_AFTER_MONTHS = 3
WETNESS_KEYS = ("root_zone_wetness", "surface_wetness")
ROAD_TORTUOSITY_FACTOR = 1.25
WORLD_BANK_DEFAULT_YIELD_KG_HA = 834.6

# Coordonnées GPS des 12 pôles provinciaux (lat, lon)
HUB_COORDINATES: dict[str, tuple[float, float]] = {
    "N'Djamena": (12.1348, 15.0557),
    "Moundou": (8.5667, 16.0833),
    "Sarh": (9.1429, 18.3923),
    "Abeche": (13.8292, 20.8324),
    "Bongor": (10.2806, 15.3722),
    "Doba": (8.6500, 16.8500),
    "Koumra": (8.9126, 17.5539),
    "Pala": (9.3642, 14.9046),
    "Mongo": (12.1844, 18.6930),
    "Ati": (13.2154, 18.3353),
    "Mao": (14.1212, 15.3103),
    "Bol": (13.4586, 14.7147),
}

ZONE_TITLE = "Pré-diagnostic agro-climatique de zone"

LIMITATIONS = (
    "Données satellitaires modélisées au niveau d'un pôle urbain/provincial : ce n'est pas une analyse de parcelle.",
    "Cette version ne contient ni température ni précipitations : aucun résultat n'en est déduit.",
    "Les alertes de déficit hydrique sont des repères indicatifs fondés sur l'écart à la normale 2020–2023 du même mois.",
    "Ne remplace ni une analyse de sol en laboratoire ni une visite de terrain.",
)

INDICATOR_LABELS_FR = {
    "root_zone_wetness": "Humidité de la zone racinaire",
    "surface_wetness": "Humidité de surface du sol",
    "par": "Rayonnement photosynthétiquement actif (PAR)",
}


def _year_month(iso_date: str) -> tuple[int, int]:
    return int(iso_date[:4]), int(iso_date[5:7])


def _months_between(iso_date: str, today: date) -> int:
    y, m = _year_month(iso_date)
    return (today.year - y) * 12 + (today.month - m)


def compute_monthly_anomalies(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute à chaque point : normale du mois (moyenne 2020–2023), écart absolu et en %, nombre d'années de référence."""
    by_month: dict[int, list[float]] = {}
    for p in series:
        y, m = _year_month(p["reference_date"])
        if BASELINE_YEARS[0] <= y <= BASELINE_YEARS[1]:
            by_month.setdefault(m, []).append(float(p["value"]))
    out: list[dict[str, Any]] = []
    for p in sorted(series, key=lambda r: r["reference_date"]):
        _, m = _year_month(p["reference_date"])
        base = by_month.get(m, [])
        item = {"reference_date": p["reference_date"], "value": float(p["value"]), "unit": p.get("unit", "")}
        if len(base) >= MIN_BASELINE_YEARS:
            mean = sum(base) / len(base)
            item.update({
                "baseline_mean": round(mean, 6),
                "baseline_years": len(base),
                "anomaly_abs": round(float(p["value"]) - mean, 6),
                "anomaly_pct": round((float(p["value"]) - mean) / mean * 100.0, 2) if mean > 0 else None,
            })
        else:
            item.update({"baseline_mean": None, "baseline_years": len(base), "anomaly_abs": None, "anomaly_pct": None})
        out.append(item)
    return out


def deficit_level(anomaly_pct: Optional[float]) -> Optional[str]:
    if anomaly_pct is None:
        return None
    if anomaly_pct <= SEVERE_DEFICIT_PCT:
        return "severe"
    if anomaly_pct <= MODERATE_DEFICIT_PCT:
        return "moderate"
    return None


def water_deficit_alerts(region: str, anomalies_by_key: dict[str, list[dict[str, Any]]], today: Optional[date] = None) -> list[dict[str, Any]]:
    """Alerte sur la dernière observation de chaque indice d'humidité si elle est nettement sous la normale du mois."""
    today = today or date.today()
    alerts: list[dict[str, Any]] = []
    for key in WETNESS_KEYS:
        points = anomalies_by_key.get(key) or []
        if not points:
            continue
        last = points[-1]
        level = deficit_level(last.get("anomaly_pct"))
        if level is None:
            continue
        label = "sévère" if level == "severe" else "modéré"
        alerts.append({
            "region": region,
            "indicator_key": key,
            "indicator_label": INDICATOR_LABELS_FR[key],
            "reference_date": last["reference_date"],
            "value": last["value"],
            "baseline_mean": last["baseline_mean"],
            "anomaly_pct": last["anomaly_pct"],
            "level": level,
            "stale": _months_between(last["reference_date"], today) > STALE_AFTER_MONTHS,
            "message": (
                f"{INDICATOR_LABELS_FR[key]} inférieure de {abs(last['anomaly_pct']):.0f} % à la normale "
                f"{BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} du même mois (déficit {label})."
            ),
            "thresholds_pct": {"moderate": MODERATE_DEFICIT_PCT, "severe": SEVERE_DEFICIT_PCT},
        })
    return alerts


def _national_block(national_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in national_rows:
        by_key.setdefault(national_indicator_key(r["indicator"]), []).append(r)
    indicators = []
    for key, items in sorted(by_key.items()):
        items.sort(key=lambda r: r["reference_date"])
        last = items[-1]
        indicators.append({
            "key": key,
            "indicator": last["indicator"],
            "unit": last["unit"],
            "latest": {"reference_date": last["reference_date"], "value": last["value"]},
            "series": [{"reference_date": r["reference_date"], "value": r["value"]} for r in items],
        })
    return {"indicators": indicators, "provenance": build_provenance(national_rows)}


def build_zone_profile(
    region: str,
    regional_rows: list[dict[str, Any]],
    national_rows: list[dict[str, Any]],
    today: Optional[date] = None,
) -> dict[str, Any]:
    today = today or date.today()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in regional_rows:
        key = regional_indicator_key(r["indicator"])
        if key:
            grouped.setdefault(key, []).append(r)
    series: dict[str, list[dict[str, Any]]] = {}
    anomalies: dict[str, list[dict[str, Any]]] = {}
    latest: dict[str, dict[str, Any]] = {}
    for key, items in grouped.items():
        points = compute_monthly_anomalies(items)
        series[key] = points
        anomalies[key] = points
        last_row = max(items, key=lambda r: r["reference_date"])
        latest[key] = {
            "label": INDICATOR_LABELS_FR[key],
            "unit": last_row["unit"],
            "reference_date": last_row["reference_date"],
            "value": last_row["value"],
        }
    last_dates = [v["reference_date"] for v in latest.values()]
    stale = bool(last_dates) and _months_between(max(last_dates), today) > STALE_AFTER_MONTHS

    # Détection de faux démarrage de semis : humidité de surface au-dessus de la normale alors que la zone racinaire reste déficitaire.
    surf_pts = series.get("surface_wetness") or []
    root_pts = series.get("root_zone_wetness") or []
    false_sowing_start = False
    if surf_pts and root_pts:
        s_anom = surf_pts[-1].get("anomaly_pct")
        r_anom = root_pts[-1].get("anomaly_pct")
        if isinstance(s_anom, (int, float)) and isinstance(r_anom, (int, float)):
            false_sowing_start = bool(s_anom > 5.0 and r_anom < -5.0)

    # Nombre d'années critiques (humidité racinaire < 0.45 en juillet-août).
    critical_by_year: dict[int, list[float]] = {}
    for p in root_pts:
        y, m = _year_month(p["reference_date"])
        if m in (7, 8):
            critical_by_year.setdefault(y, []).append(float(p["value"]))
    critical_july_aug_years = sum(
        1 for vals in critical_by_year.values() if vals and (sum(vals) / len(vals)) < 0.45
    )

    nat_block = _national_block(national_rows)
    yield_2020_2024 = [
        float(r["value"])
        for r in national_rows
        if national_indicator_key(r["indicator"]) == "cereal_yield" and 2020 <= int(r["reference_date"][:4]) <= 2024
    ]
    cereal_yield_mean = round(sum(yield_2020_2024) / len(yield_2020_2024), 1) if yield_2020_2024 else None

    return {
        "title": ZONE_TITLE,
        "region": region,
        "province": HUB_PROVINCE.get(region),
        "indicator_labels": {k: INDICATOR_LABELS_FR[k] for k in series},
        "series": series,
        "latest": latest,
        "baseline": {"years": list(BASELINE_YEARS), "min_years_required": MIN_BASELINE_YEARS},
        "alerts": water_deficit_alerts(region, anomalies, today),
        "hydric_risk_signals": {
            "false_sowing_start": false_sowing_start,
            "critical_july_aug_years": critical_july_aug_years,
            "observed_july_aug_years": len(critical_by_year),
            "cereal_yield_mean_2020_2024_kg_ha": cereal_yield_mean,
        },
        "stale": stale,
        "provenance": build_provenance(regional_rows),
        "national": nat_block,
        "limitations": list(LIMITATIONS),
    }


def build_zones_overview(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Liste des pôles couverts et fraîcheur, à partir des lignes régionales + nationales."""
    zones: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["region"] == NATIONAL:
            continue
        z = zones.setdefault(r["region"], {"region": r["region"], "indicators": set(), "first": r["reference_date"], "last": r["reference_date"]})
        key = regional_indicator_key(r["indicator"])
        if key:
            z["indicators"].add(key)
        z["first"] = min(z["first"], r["reference_date"])
        z["last"] = max(z["last"], r["reference_date"])
    zone_list = [
        {
            "region": z["region"],
            "province": HUB_PROVINCE.get(z["region"]),
            "indicators": sorted(z["indicators"]),
            "first_reference_date": z["first"],
            "last_reference_date": z["last"],
        }
        for z in sorted(zones.values(), key=lambda z: z["region"])
    ]
    regional = [r for r in rows if r["region"] != NATIONAL]
    national = [r for r in rows if r["region"] == NATIONAL]
    return {
        "title": ZONE_TITLE,
        "data_available": bool(rows),
        "zones": zone_list,
        "provenance": {"regional": build_provenance(regional), "national": build_provenance(national)},
        "limitations": list(LIMITATIONS),
    }


# ---------------------------------------------------------------------------
# Étape 3 (P2) — Moteur Agronome PRO : Diagnostic de terrain & couplage prix
# ---------------------------------------------------------------------------

SUPPORTED_AGRO_CROPS: dict[str, dict[str, Any]] = {
    "millet": {
        "label_fr": "Mil",
        "commodity_std": "Millet",
        "ph_opt": (5.5, 7.5),
        "ph_tol": (5.0, 8.2),
        "preferred_textures": ("sandy", "sandy_loam", "loamy"),
        "min_wetness": 0.20,
    },
    "sorghum": {
        "label_fr": "Sorgho rouge",
        "commodity_std": "Sorghum (red)",
        "ph_opt": (5.5, 8.0),
        "ph_tol": (5.0, 8.5),
        "preferred_textures": ("loamy", "clay_loam", "clay", "sandy_loam"),
        "min_wetness": 0.25,
    },
    "maize": {
        "label_fr": "Maïs blanc",
        "commodity_std": "Maize (white)",
        "ph_opt": (5.8, 7.2),
        "ph_tol": (5.2, 7.8),
        "preferred_textures": ("loamy", "sandy_loam", "silty"),
        "min_wetness": 0.35,
    },
    "groundnut_raw": {
        "label_fr": "Arachide",
        "commodity_std": "Groundnuts (shelled)",
        "ph_opt": (5.5, 7.0),
        "ph_tol": (5.0, 7.6),
        "preferred_textures": ("sandy", "sandy_loam", "loamy"),
        "min_wetness": 0.25,
    },
}

_LAB_SOIL_KEYS = ("ph", "texture", "nitrogen", "phosphorus", "potassium", "organic_matter")


def has_lab_soil_measurements(lab_soil_inputs: Optional[dict[str, Any]]) -> bool:
    if not isinstance(lab_soil_inputs, dict):
        return False
    for k in _LAB_SOIL_KEYS:
        val = lab_soil_inputs.get(k)
        if val is not None and str(val).strip() != "":
            return True
    return False


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance orthodromique (vol d'oiseau) en kilomètres via la formule de Haversine."""
    r_earth_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    return 2.0 * r_earth_km * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def compute_gps_logistics(
    gps_lat: Optional[float],
    gps_lon: Optional[float],
    *,
    province_hub: Optional[str] = None,
) -> dict[str, Any]:
    """Calcule les distances routières estimées (Haversine × 1.25) et la décote bord-champ."""
    resolved_hub = canonical_region(province_hub) if province_hub else None
    if resolved_hub == NATIONAL:
        resolved_hub = None

    if gps_lat is None or gps_lon is None:
        return {
            "gps_provided": False,
            "gps_lat": None,
            "gps_lon": None,
            "closest_hub": resolved_hub,
            "selected_hub": resolved_hub,
            "distance_hub_haversine_km": None,
            "distance_hub_km": None,
            "distance_ndjamena_km": None,
            "road_tortuosity_factor": ROAD_TORTUOSITY_FACTOR,
            "farmgate_discount_pct": 0.0,
            "enclavement_label": "GPS non fourni (prix pôle sans décote bord-champ)",
            "remoteness_alert": False,
        }

    lat = float(gps_lat)
    lon = float(gps_lon)
    distances: list[tuple[str, float]] = []
    for hub, (h_lat, h_lon) in HUB_COORDINATES.items():
        distances.append((hub, haversine_km(lat, lon, h_lat, h_lon)))
    distances.sort(key=lambda item: item[1])
    closest_hub, min_hav_km = distances[0]

    target_hub = resolved_hub or closest_hub
    if target_hub in HUB_COORDINATES:
        th_lat, th_lon = HUB_COORDINATES[target_hub]
        selected_hav_km = haversine_km(lat, lon, th_lat, th_lon)
    else:
        selected_hav_km = min_hav_km

    d_hub_km = round(selected_hav_km * ROAD_TORTUOSITY_FACTOR, 1)
    ndj_lat, ndj_lon = HUB_COORDINATES["N'Djamena"]
    d_ndjamena_km = round(haversine_km(lat, lon, ndj_lat, ndj_lon) * ROAD_TORTUOSITY_FACTOR, 1)

    if d_hub_km <= 15.0:
        discount_pct = 8.0
        enclavement = "Faible enclavement (<= 15 km du pôle)"
        alert = False
    elif d_hub_km <= 50.0:
        discount_pct = 15.0
        enclavement = "Enclavement modéré (15–50 km du pôle)"
        alert = False
    else:
        discount_pct = 22.0
        enclavement = "Enclavement élevé (> 50 km — alerte éloignement logistique)"
        alert = True

    return {
        "gps_provided": True,
        "gps_lat": round(lat, 6),
        "gps_lon": round(lon, 6),
        "closest_hub": closest_hub,
        "selected_hub": target_hub,
        "distance_hub_haversine_km": round(selected_hav_km, 1),
        "distance_hub_km": d_hub_km,
        "distance_ndjamena_km": d_ndjamena_km,
        "road_tortuosity_factor": ROAD_TORTUOSITY_FACTOR,
        "farmgate_discount_pct": discount_pct,
        "enclavement_label": enclavement,
        "remoteness_alert": alert,
    }


def _historical_stress_min_price(hist_df: Any, commodity_std: str, province: Optional[str]) -> Optional[float]:
    """Prix minimum observé en 2024–2026 (WFP/FEWS NET) pour le scénario de stress sévère."""
    if hist_df is None or getattr(hist_df, "empty", True):
        return None
    if "commodity_std" not in hist_df.columns or "value" not in hist_df.columns:
        return None
    sub = hist_df[hist_df["commodity_std"] == commodity_std]
    if sub.empty:
        return None
    if "date" in sub.columns:
        recent = sub[sub["date"].astype(str).str.slice(0, 4).isin(["2024", "2025", "2026"])]
        if not recent.empty:
            sub = recent
    if province and "province" in sub.columns:
        psub = sub[sub["province"].astype(str).str.lower() == province.lower()]
        if not psub.empty:
            sub = psub
    vals = sub["value"].dropna()
    return round(float(vals.min()), 1) if not vals.empty else None


def _max_national_hub_price(forecast_df: Any, commodity_std: str) -> tuple[Optional[float], Optional[str]]:
    """Trouve le pôle le plus cher du pays pour la culture cible (bonus d'arbitrage inter-marchés)."""
    if forecast_df is None or getattr(forecast_df, "empty", True):
        return None, None
    if "commodity_std" not in forecast_df.columns or "predicted_price" not in forecast_df.columns:
        return None, None
    sub = forecast_df[forecast_df["commodity_std"] == commodity_std].dropna(subset=["predicted_price"])
    if sub.empty:
        return None, None
    by_prov = sub.groupby("province")["predicted_price"].mean()
    if by_prov.empty:
        return None, None
    best_prov = str(by_prov.idxmax())
    return round(float(by_prov.max()), 1), best_prov


def compute_verified_economics(
    *,
    crop_id: str,
    area_hectares: Optional[float],
    yield_kg_ha: float,
    yield_source: str,
    predicted_xaf_kg: Optional[float],
    mape_pct: Optional[float],
    stress_min_xaf_kg: Optional[float],
    farmgate_discount_pct: float,
    max_hub_price_xaf_kg: Optional[float] = None,
    max_hub_province: Optional[str] = None,
) -> dict[str, Any]:
    """Modèle économique & financier transparent avec formules vérifiables ligne par ligne."""
    area = float(area_hectares) if (area_hectares and area_hectares > 0) else 1.0
    area_assumed = not bool(area_hectares and area_hectares > 0)
    q_kg = round(area * float(yield_kg_ha), 1)
    disc_ratio = max(0.0, min(0.5, float(farmgate_discount_pct) / 100.0))
    mape_ratio = float(mape_pct) / 100.0 if isinstance(mape_pct, (int, float)) else 0.12

    if predicted_xaf_kg is None or predicted_xaf_kg <= 0:
        return {
            "crop_id": crop_id,
            "area_hectares": area,
            "area_assumed_1ha": area_assumed,
            "yield_kg_ha": round(float(yield_kg_ha), 1),
            "yield_source": yield_source,
            "production_kg": q_kg,
            "farmgate_discount_pct": round(float(farmgate_discount_pct), 1),
            "formula_text": f"{area:g} ha × {yield_kg_ha:.1f} kg/ha = {q_kg:,.1f} kg (prix ML indisponible)",
            "scenarios": [],
        }

    p_ml = float(predicted_xaf_kg)
    p_central = round(p_ml * (1.0 - disc_ratio), 1)
    p_low = round(p_central * max(0.0, 1.0 - mape_ratio), 1)
    p_high = round(p_central * (1.0 + mape_ratio), 1)

    raw_stress = float(stress_min_xaf_kg) if (stress_min_xaf_kg and stress_min_xaf_kg > 0) else round(p_ml * max(0.5, 1.0 - mape_ratio), 1)
    p_stress = round(raw_stress * (1.0 - disc_ratio), 1)

    ca_central = round(q_kg * p_central)
    ca_stress = round(q_kg * p_stress)
    ca_low = round(q_kg * p_low)
    ca_high = round(q_kg * p_high)

    arbitrage_bonus = None
    if max_hub_price_xaf_kg and max_hub_price_xaf_kg > p_ml and max_hub_province:
        spread = round(float(max_hub_price_xaf_kg) - p_ml, 1)
        arbitrage_bonus = {
            "target_province": max_hub_province,
            "target_price_xaf_kg": round(float(max_hub_price_xaf_kg), 1),
            "spread_xaf_kg": spread,
            "potential_gross_gain_xaf": round(q_kg * spread),
        }

    formula_text = (
        f"{area:g} ha × {yield_kg_ha:.1f} kg/ha × {p_ml:.1f} FCFA/kg "
        f"× (1 - {farmgate_discount_pct:.0f}%) = {ca_central:,} FCFA"
    ).replace(",", " ")

    scenarios = [
        {
            "id": "stress_floor",
            "label": "Plancher Stress (2024–2026)",
            "market_price_xaf_kg": round(raw_stress, 1),
            "farmgate_price_xaf_kg": p_stress,
            "gross_revenue_xaf": ca_stress,
        },
        {
            "id": "central_ml",
            "label": "Scénario Central (ML t+1)",
            "market_price_xaf_kg": round(p_ml, 1),
            "farmgate_price_xaf_kg": p_central,
            "gross_revenue_xaf": ca_central,
        },
    ]
    if arbitrage_bonus:
        ca_arb = round(q_kg * arbitrage_bonus["target_price_xaf_kg"])
        scenarios.append({
            "id": "inter_market_arbitrage",
            "label": f"Arbitrage Expédition ({arbitrage_bonus['target_province']})",
            "market_price_xaf_kg": arbitrage_bonus["target_price_xaf_kg"],
            "farmgate_price_xaf_kg": arbitrage_bonus["target_price_xaf_kg"],
            "gross_revenue_xaf": ca_arb,
        })

    return {
        "crop_id": crop_id,
        "area_hectares": area,
        "area_assumed_1ha": area_assumed,
        "yield_kg_ha": round(float(yield_kg_ha), 1),
        "yield_source": yield_source,
        "production_kg": q_kg,
        "predicted_market_xaf_kg": round(p_ml, 1),
        "farmgate_discount_pct": round(float(farmgate_discount_pct), 1),
        "farmgate_price_central_xaf_kg": p_central,
        "uncertainty_range_xaf_kg": [p_low, p_high],
        "uncertainty_revenue_range_xaf": [ca_low, ca_high],
        "stress_price_xaf_kg": p_stress,
        "ca_central_xaf": ca_central,
        "ca_stress_xaf": ca_stress,
        "mape_pct": round(mape_ratio * 100.0, 2),
        "arbitrage_bonus": arbitrage_bonus,
        "formula_text": formula_text,
        "scenarios": scenarios,
    }


def compute_weighted_score(
    *,
    zone: dict[str, Any],
    has_lab: bool,
    ph_val: Optional[float],
    texture_val: str,
    primary_crop_id: str,
    primary_market: Optional[dict[str, Any]],
    gps_logistics: dict[str, Any],
) -> dict[str, Any]:
    """Score composite pondéré sur 100 (40 Hydrique + 30 Pédologie + 30 Marché & Logistique)."""
    spec = SUPPORTED_AGRO_CROPS.get(primary_crop_id, SUPPORTED_AGRO_CROPS["millet"])
    strengths: list[str] = []
    vigilances: list[str] = []

    # 1. Sécurité Hydrique (40 pts) : humidité racinaire saison des pluies (juin-sept) & années critiques < 0.45
    root_series = (zone.get("series") or {}).get("root_zone_wetness") or []
    rainy_vals = [
        float(p["value"])
        for p in root_series
        if _year_month(p["reference_date"])[1] in (6, 7, 8, 9)
    ]
    rainy_mean = round(sum(rainy_vals) / len(rainy_vals), 3) if rainy_vals else None
    crit_years = int((zone.get("hydric_risk_signals") or {}).get("critical_july_aug_years") or 0)
    obs_years = int((zone.get("hydric_risk_signals") or {}).get("observed_july_aug_years") or 0)

    hydric_pts = 20.0
    if rainy_mean is not None:
        if rainy_mean >= 0.55:
            hydric_pts = 36.0
            strengths.append(f"Humidité racinaire saisonnière favorable ({rainy_mean:.2f} en juin–sept., NASA POWER).")
        elif rainy_mean >= 0.45:
            hydric_pts = 29.0
            strengths.append(f"Humidité racinaire correcte en saison des pluies ({rainy_mean:.2f}).")
        elif rainy_mean >= 0.30:
            hydric_pts = 21.0
            vigilances.append(f"Humidité racinaire modérée ({rainy_mean:.2f}) : privilégier les variétés rustiques.")
        else:
            hydric_pts = 12.0
            vigilances.append(f"Déficit hydrique structurel en saison des pluies ({rainy_mean:.2f} < 0.30).")
    hydric_pts = max(0.0, min(40.0, hydric_pts - min(12.0, crit_years * 2.5)))
    if crit_years >= 2:
        vigilances.append(f"{crit_years} année(s) critique(s) (< 0.45 en juil.–août) observée(s) sur {obs_years or 'la période'}.")

    # 2. Qualité Pédologique (30 pts)
    if not has_lab:
        soil_pts = 15.0
        soil_note = "Plafonné à 15/30 (mesures sol non fournies)"
        vigilances.append("Mesures de sol laboratoire absentes : score pédologique plafonné à 15/30.")
    else:
        soil_pts = 16.0
        soil_note = "Mesuré sur terrain / laboratoire"
        if ph_val is not None:
            if 5.8 <= ph_val <= 7.0:
                soil_pts += 8.0
                strengths.append(f"pH mesuré optimal ({ph_val:.1f}) pour les cultures cibles.")
            elif spec["ph_tol"][0] <= ph_val <= spec["ph_tol"][1]:
                soil_pts += 4.0
            else:
                soil_pts -= 6.0
                vigilances.append(f"pH mesuré hors zone optimale ({ph_val:.1f}).")
        if texture_val:
            if texture_val in spec["preferred_textures"]:
                soil_pts += 6.0
                strengths.append(f"Texture « {texture_val} » adaptée à la culture ({spec['label_fr']}).")
            else:
                soil_pts -= 3.0
                vigilances.append(f"Texture « {texture_val} » sub-optimale pour {spec['label_fr']}.")
        soil_pts = max(0.0, min(30.0, soil_pts))

    # 3. Attractivité Marché & Logistique (30 pts)
    mkt_pts = 15.0
    d_hub = gps_logistics.get("distance_hub_km")
    if isinstance(d_hub, (int, float)):
        if d_hub <= 15.0:
            mkt_pts += 8.0
            strengths.append(f"Excellente accessibilité logistique ({d_hub:.1f} km du pôle {gps_logistics.get('selected_hub')}).")
        elif d_hub <= 50.0:
            mkt_pts += 4.0
        else:
            mkt_pts -= 4.0
            vigilances.append(f"Parcelle enclavée ({d_hub:.1f} km du pôle) : décote bord-champ de 22 % appliquée.")
    if primary_market and isinstance(primary_market.get("predicted_xaf_kg"), (int, float)):
        chg = primary_market.get("change_pct")
        if isinstance(chg, (int, float)) and chg >= 0:
            mkt_pts += 7.0
        else:
            mkt_pts += 4.0
    mkt_pts = max(0.0, min(30.0, mkt_pts))

    total = round(hydric_pts + soil_pts + mkt_pts, 1)
    verdict = "Favorable" if total >= 70.0 else ("Modéré — À sécuriser" if total >= 50.0 else "Risque élevé")

    return {
        "total_score": total,
        "verdict": verdict,
        "rainy_season_root_wetness_mean": rainy_mean,
        "breakdown": {
            "hydric_security": {"score": round(hydric_pts, 1), "max": 40, "source": "NASA POWER Agro 2020–2026"},
            "soil_quality": {"score": round(soil_pts, 1), "max": 30, "note": soil_note},
            "market_logistics": {"score": round(mkt_pts, 1), "max": 30, "source": "WFP/FEWS NET + GPS"},
        },
        "strengths": strengths[:3],
        "vigilances": vigilances[:2],
    }


def _extract_crop_market_signals(
    forecast_df: Any,
    province: Optional[str],
    track_record: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, Any]]:
    """Extrait les prévisions de prix t+1 (XAF/kg) et le MAPE hors-temps pour les 4 cultures validées."""
    signals: dict[str, dict[str, Any]] = {}
    if forecast_df is None or getattr(forecast_df, "empty", True):
        return signals
    tr = track_record or {}
    for crop_id, meta in SUPPORTED_AGRO_CROPS.items():
        comm = meta["commodity_std"]
        sub = forecast_df[forecast_df["commodity_std"] == comm]
        if sub.empty:
            continue
        prov_sub = sub[sub["province"].astype(str).str.lower() == province.lower()] if province else sub.iloc[0:0]
        scope_df = prov_sub if not prov_sub.empty else sub
        scope_label = province if not prov_sub.empty else "National (moyenne marchés)"
        pred_col = "predicted_price" if "predicted_price" in scope_df.columns else None
        obs_col = "last_observed_price" if "last_observed_price" in scope_df.columns else ("value" if "value" in scope_df.columns else None)
        pred_val = float(scope_df[pred_col].dropna().mean()) if pred_col and not scope_df[pred_col].dropna().empty else None
        obs_val = float(scope_df[obs_col].dropna().mean()) if obs_col and not scope_df[obs_col].dropna().empty else None
        fc_month = str(scope_df["forecast_month"].dropna().iloc[0]) if "forecast_month" in scope_df.columns and not scope_df["forecast_month"].dropna().empty else None
        change_pct = round((pred_val - obs_val) / obs_val * 100.0, 1) if (pred_val and obs_val and obs_val > 0) else None
        rec = tr.get(comm) or {}
        mape = rec.get("mape_pct") if rec.get("mape_pct") is not None else rec.get("MAPE_pct")
        signals[crop_id] = {
            "commodity_std": comm,
            "scope": scope_label,
            "last_observed_xaf_kg": round(obs_val, 1) if obs_val is not None else None,
            "predicted_xaf_kg": round(pred_val, 1) if pred_val is not None else None,
            "change_pct": change_pct,
            "forecast_month": fc_month,
            "historical_mape_pct": round(float(mape), 2) if isinstance(mape, (int, float)) else None,
            "source": "FreeData.td / PAM-WFP (Delta-Ridge ML)",
        }
    return signals


def _latest_national_cereal_yield(national_rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    yields = [r for r in national_rows if national_indicator_key(r["indicator"]) == "cereal_yield"]
    if not yields:
        return None
    latest = max(yields, key=lambda r: r["reference_date"])
    return {"value_kg_ha": float(latest["value"]), "reference_date": latest["reference_date"], "source": latest["source"], "license": latest["license"]}


def evaluate_field_assessment(
    *,
    region: Optional[str] = None,
    regional_rows: list[dict[str, Any]],
    national_rows: list[dict[str, Any]],
    lab_soil_inputs: Optional[dict[str, Any]] = None,
    target_crops: Optional[list[str]] = None,
    area_hectares: Optional[float] = None,
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
    custom_yield_kg_ha: Optional[float] = None,
    forecast_df: Any = None,
    hist_df: Any = None,
    track_record: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Calcule un audit agronomique & économique vérifiable (GPS Haversine, NASA POWER, World Bank, WFP/FEWS NET)."""
    gps_logistics = compute_gps_logistics(gps_lat, gps_lon, province_hub=region)
    resolved_region = canonical_region(region) if region else gps_logistics.get("selected_hub")
    if not resolved_region or resolved_region == NATIONAL:
        resolved_region = gps_logistics.get("closest_hub") or "N'Djamena"

    zone = build_zone_profile(resolved_region, regional_rows, national_rows, today=today)
    province = zone.get("province")
    lab = dict(lab_soil_inputs or {})
    has_lab = has_lab_soil_measurements(lab)
    resolution_label = (
        "Diagnostic d'Audit Parcellaire & Marché (Pré-Achat)"
        if has_lab
        else "Pré-diagnostic Zonal & Économique (Mesures sol non fournies)"
    )
    confidence_short = "Terrain + Régional" if has_lab else "Régional uniquement"
    confidence_label = (
        "Terrain + Régional (Mesures labo fournies)"
        if has_lab
        else "Régional uniquement — Mesures sol non fournies"
    )

    requested = [c for c in (target_crops or list(SUPPORTED_AGRO_CROPS)) if c in SUPPORTED_AGRO_CROPS]
    if not requested:
        requested = list(SUPPORTED_AGRO_CROPS)

    root_wet = (zone.get("latest", {}).get("root_zone_wetness") or {}).get("value")
    market_signals = _extract_crop_market_signals(forecast_df, province, track_record=track_record)
    cereal_yield = _latest_national_cereal_yield(national_rows)
    wb_mean_yield = (zone.get("hydric_risk_signals") or {}).get("cereal_yield_mean_2020_2024_kg_ha")
    if custom_yield_kg_ha and custom_yield_kg_ha > 0:
        ref_yield = float(custom_yield_kg_ha)
        yield_source = "Rendement saisi par l'agronome"
    elif isinstance(wb_mean_yield, (int, float)) and wb_mean_yield > 0:
        ref_yield = float(wb_mean_yield)
        yield_source = "World Bank (moyenne officielle 2020–2024)"
    elif cereal_yield and cereal_yield.get("value_kg_ha"):
        ref_yield = float(cereal_yield["value_kg_ha"])
        yield_source = f"World Bank ({cereal_yield.get('reference_date', 'officiel')})"
    else:
        ref_yield = WORLD_BANK_DEFAULT_YIELD_KG_HA
        yield_source = "World Bank (moyenne nationale 2020–2024 : 834.6 kg/ha)"

    ph_val: Optional[float] = None
    if lab.get("ph") is not None and str(lab.get("ph")).strip() != "":
        try:
            ph_val = float(lab["ph"])
        except (TypeError, ValueError):
            ph_val = None
    texture_val = str(lab.get("texture") or "").strip().lower()
    om_val: Optional[float] = None
    if lab.get("organic_matter") is not None and str(lab.get("organic_matter")).strip() != "":
        try:
            om_val = float(lab["organic_matter"])
        except (TypeError, ValueError):
            om_val = None

    crop_results: list[dict[str, Any]] = []
    for crop_id in requested:
        spec = SUPPORTED_AGRO_CROPS[crop_id]
        score = 60.0
        limiting: list[str] = []
        criteria: list[dict[str, Any]] = []

        if isinstance(root_wet, (int, float)):
            if root_wet >= spec["min_wetness"]:
                score += 15.0
                criteria.append({"factor": "Humidité racinaire zonale", "status": "favorable", "value": round(float(root_wet), 3)})
            else:
                score -= 20.0
                limiting.append(f"Humidité racinaire zonale basse ({root_wet:.2f} < {spec['min_wetness']:.2f})")
                criteria.append({"factor": "Humidité racinaire zonale", "status": "limitant", "value": round(float(root_wet), 3)})

        if has_lab:
            if ph_val is not None:
                lo_opt, hi_opt = spec["ph_opt"]
                lo_tol, hi_tol = spec["ph_tol"]
                if lo_opt <= ph_val <= hi_opt:
                    score += 15.0
                    criteria.append({"factor": "pH du sol (labo)", "status": "optimal", "value": ph_val})
                elif lo_tol <= ph_val <= hi_tol:
                    score += 5.0
                    criteria.append({"factor": "pH du sol (labo)", "status": "tolérable", "value": ph_val})
                else:
                    score -= 25.0
                    limiting.append(f"pH hors plage ({ph_val:.1f}, attendu {lo_tol}–{hi_tol})")
                    criteria.append({"factor": "pH du sol (labo)", "status": "défavorable", "value": ph_val})
            if texture_val:
                if texture_val in spec["preferred_textures"]:
                    score += 10.0
                    criteria.append({"factor": "Texture du sol (labo)", "status": "adaptée", "value": texture_val})
                else:
                    score -= 10.0
                    limiting.append(f"Texture « {texture_val} » peu adaptée")
                    criteria.append({"factor": "Texture du sol (labo)", "status": "limitant", "value": texture_val})
            if om_val is not None:
                if om_val >= 1.5:
                    score += 5.0
                    criteria.append({"factor": "Matière organique (%)", "status": "correcte", "value": om_val})
                elif om_val < 0.8:
                    score -= 8.0
                    limiting.append(f"Matière organique faible ({om_val:.1f} %)")
                    criteria.append({"factor": "Matière organique (%)", "status": "faible", "value": om_val})
        else:
            limiting.append("Mesures labo non fournies : évaluation hydrique zonale uniquement.")

        final_score = max(0, min(100, int(round(score))))
        suitability_label = "Favorable" if final_score >= 70 else ("Modérée" if final_score >= 45 else "Défavorable")
        mkt = market_signals.get(crop_id)
        stress_min = _historical_stress_min_price(hist_df, spec["commodity_std"], province)
        max_hub_p, max_hub_prov = _max_national_hub_price(forecast_df, spec["commodity_std"])
        econ = compute_verified_economics(
            crop_id=crop_id,
            area_hectares=area_hectares,
            yield_kg_ha=ref_yield,
            yield_source=yield_source,
            predicted_xaf_kg=mkt.get("predicted_xaf_kg") if mkt else None,
            mape_pct=mkt.get("historical_mape_pct") if mkt else None,
            stress_min_xaf_kg=stress_min,
            farmgate_discount_pct=float(gps_logistics.get("farmgate_discount_pct") or 0.0),
            max_hub_price_xaf_kg=max_hub_p,
            max_hub_province=max_hub_prov,
        )
        indicative_revenue_xaf = econ.get("ca_central_xaf")

        crop_results.append({
            "crop_id": crop_id,
            "label_fr": spec["label_fr"],
            "suitability_score": final_score,
            "suitability_label": suitability_label,
            "limiting_factors": limiting,
            "criteria": criteria,
            "market_forecast": mkt,
            "verified_economics": econ,
            "indicative_gross_revenue_xaf": indicative_revenue_xaf,
        })

    crop_results.sort(key=lambda c: c["suitability_score"], reverse=True)
    primary_crop = crop_results[0] if crop_results else None
    weighted_score = compute_weighted_score(
        zone=zone,
        has_lab=has_lab,
        ph_val=ph_val,
        texture_val=texture_val,
        primary_crop_id=primary_crop["crop_id"] if primary_crop else "millet",
        primary_market=primary_crop.get("market_forecast") if primary_crop else None,
        gps_logistics=gps_logistics,
    )

    return {
        "title": resolution_label,
        "resolution_label": resolution_label,
        "confidence": confidence_short,
        "region": zone["region"],
        "province": province,
        "has_lab_measurements": has_lab,
        "confidence_level": confidence_label,
        "gps_logistics": gps_logistics,
        "weighted_score": weighted_score,
        "verified_economics": primary_crop.get("verified_economics") if primary_crop else None,
        "hydric_risk_signals": zone.get("hydric_risk_signals"),
        "zone_alerts": zone["alerts"],
        "zone_latest": zone["latest"],
        "crop_assessments": crop_results,
        "cereal_yield_reference": cereal_yield,
        "provenance": zone["provenance"],
        "national_provenance": zone["national"]["provenance"],
        "limitations": list(LIMITATIONS),
    }


def compare_agro_assessments(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Classe 2 à 4 terrains candidats par score composite décroissant et calcule les écarts différentiels."""
    ranked: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        scores = item.get("computed_scores") or item
        ws = scores.get("weighted_score") or {}
        gps = scores.get("gps_logistics") or {}
        econ = scores.get("verified_economics") or {}
        crops = scores.get("crop_assessments") or []
        best_crop = crops[0] if crops else {}
        mkt = best_crop.get("market_forecast") or {}
        ranked.append({
            "label": item.get("label") or f"Terrain {chr(65 + idx)}",
            "assessment_id": item.get("id") or item.get("assessment_id"),
            "region": scores.get("region") or item.get("province_hub"),
            "province": scores.get("province"),
            "resolution_label": scores.get("resolution_label"),
            "has_lab_measurements": bool(scores.get("has_lab_measurements")),
            "score_composite": float(ws.get("total_score") or 0.0),
            "verdict": ws.get("verdict") or "—",
            "distance_hub_km": gps.get("distance_hub_km"),
            "distance_ndjamena_km": gps.get("distance_ndjamena_km"),
            "farmgate_discount_pct": gps.get("farmgate_discount_pct"),
            "rainy_root_wetness": ws.get("rainy_season_root_wetness_mean"),
            "primary_crop": best_crop.get("label_fr") or best_crop.get("crop_id"),
            "predicted_xaf_kg": mkt.get("predicted_xaf_kg"),
            "ca_central_xaf": econ.get("ca_central_xaf"),
            "ca_stress_xaf": econ.get("ca_stress_xaf"),
        })

    ranked.sort(key=lambda r: r["score_composite"], reverse=True)
    leader = ranked[0] if ranked else None
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
        row["rank_label"] = "#1 Recommandé" if i == 0 else f"#{i + 1}"
        if leader and i > 0:
            row["delta_vs_best"] = {
                "score_diff": round(row["score_composite"] - leader["score_composite"], 1),
                "distance_km_diff": (
                    round(row["distance_hub_km"] - leader["distance_hub_km"], 1)
                    if isinstance(row.get("distance_hub_km"), (int, float))
                    and isinstance(leader.get("distance_hub_km"), (int, float))
                    else None
                ),
                "root_wetness_diff": (
                    round(row["rainy_root_wetness"] - leader["rainy_root_wetness"], 3)
                    if isinstance(row.get("rainy_root_wetness"), (int, float))
                    and isinstance(leader.get("rainy_root_wetness"), (int, float))
                    else None
                ),
                "price_xaf_kg_diff": (
                    round(row["predicted_xaf_kg"] - leader["predicted_xaf_kg"], 1)
                    if isinstance(row.get("predicted_xaf_kg"), (int, float))
                    and isinstance(leader.get("predicted_xaf_kg"), (int, float))
                    else None
                ),
                "ca_central_xaf_diff": (
                    int(row["ca_central_xaf"] - leader["ca_central_xaf"])
                    if isinstance(row.get("ca_central_xaf"), (int, float))
                    and isinstance(leader.get("ca_central_xaf"), (int, float))
                    else None
                ),
            }
        else:
            row["delta_vs_best"] = None

    any_no_lab = any(not r["has_lab_measurements"] for r in ranked)
    title = (
        "Pré-diagnostic Zonal & Économique (Mesures sol non fournies)"
        if any_no_lab
        else "Diagnostic d'Audit Parcellaire & Marché (Pré-Achat)"
    )
    return {
        "title": title,
        "count": len(ranked),
        "recommended": leader,
        "comparison_table": ranked,
        "sources": [
            "NASA POWER Agro (Public Domain)",
            "World Bank (CC BY 4.0)",
            "WFP (CC BY-IGO 3.0)",
            "FEWS NET (Attribution Required)",
        ],
    }


def validate_field_assessment_qa(assessment: dict[str, Any]) -> dict[str, Any]:
    """Porte QA (6 dimensions) avant génération du PDF co-brandé Agronome PRO."""
    scores = assessment.get("computed_scores") or {}
    has_lab = bool(scores.get("has_lab_measurements"))
    blockers: list[str] = []
    if not has_lab:
        blockers.append(
            "Mesures de sol laboratoire absentes : un « Diagnostic de terrain (pré-achat) » PDF exige au moins un paramètre mesuré (pH, texture, NPK ou matière organique)."
        )
    if not assessment.get("province_hub"):
        blockers.append("Pôle régional manquant.")
    if not scores.get("crop_assessments"):
        blockers.append("Aucune culture cible évaluée.")
    prov = scores.get("provenance") or {}
    if not prov.get("sources") or not prov.get("licenses"):
        blockers.append("Provenance (source/licence) incomplète.")

    dimensions = {
        "data_quality": "pass" if has_lab else "fail",
        "traceability": "pass" if (prov.get("sources") and assessment.get("report_verification_code")) else "fail",
        "completeness": "pass" if scores.get("crop_assessments") else "fail",
        "transparency": "pass" if scores.get("limitations") else "fail",
        "compliance": "pass",
        "coherence": "pass",
    }
    return {
        "can_deliver_pdf": len(blockers) == 0,
        "blockers": blockers,
        "dimensions": dimensions,
    }


