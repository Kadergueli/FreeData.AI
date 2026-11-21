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

from src.agro_site import site_profile, zonal_soil_estimate
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
    "Couverture spatiale : indicateurs satellitaires modélisés à l'échelle du pôle régional (maille urbaine/provinciale), ne constituant pas une mesure parcellaire.",
    "Périmètre des variables : jeu de données limité à l'humidité des sols (surface et zone racinaire) et au rayonnement PAR ; aucune variable de température ou de précipitations n'est intégrée.",
    "Indicateurs d'alerte : les seuils de déficit hydrique sont des repères statistiques indicatifs calculés par rapport à la normale mensuelle 2020–2023.",
    "Portée décisionnelle : ce pré-diagnostic zonal ne se substitue ni à une analyse physico-chimique en laboratoire ni à une expertise agronomique sur site.",
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
        "rz_opt": 0.45,
        "sigma": 0.22,
        "surf_opt": 0.42,
        "par_opt": 9.8,
    },
    "sorghum": {
        "label_fr": "Sorgho rouge",
        "commodity_std": "Sorghum (red)",
        "ph_opt": (5.5, 8.0),
        "ph_tol": (5.0, 8.5),
        "preferred_textures": ("loamy", "clay_loam", "clay", "sandy_loam"),
        "min_wetness": 0.25,
        "rz_opt": 0.58,
        "sigma": 0.18,
        "surf_opt": 0.54,
        "par_opt": 9.6,
    },
    "maize": {
        "label_fr": "Maïs blanc",
        "commodity_std": "Maize (white)",
        "ph_opt": (5.8, 7.2),
        "ph_tol": (5.2, 7.8),
        "preferred_textures": ("loamy", "sandy_loam", "silty"),
        "min_wetness": 0.35,
        "rz_opt": 0.72,
        "sigma": 0.15,
        "surf_opt": 0.66,
        "par_opt": 9.4,
    },
    "groundnut_raw": {
        "label_fr": "Arachide",
        "commodity_std": "Groundnuts (shelled)",
        "ph_opt": (5.5, 7.0),
        "ph_tol": (5.0, 7.6),
        "preferred_textures": ("sandy", "sandy_loam", "loamy"),
        "min_wetness": 0.25,
        "rz_opt": 0.60,
        "sigma": 0.16,
        "surf_opt": 0.55,
        "par_opt": 9.7,
    },
    "rice_local": {
        "label_fr": "Riz local",
        "commodity_std": "Rice (local)",
        "ph_opt": (5.5, 6.8),
        "ph_tol": (4.8, 7.5),
        "preferred_textures": ("clay", "clay_loam", "silty", "loamy"),
        "min_wetness": 0.45,
        "rz_opt": 0.78,
        "sigma": 0.14,
        "surf_opt": 0.72,
        "par_opt": 9.3,
    },
    "sesame": {
        "label_fr": "Sésame",
        "commodity_std": "Sesame",
        "ph_opt": (5.5, 7.5),
        "ph_tol": (5.0, 8.2),
        "preferred_textures": ("sandy", "sandy_loam", "loamy"),
        "min_wetness": 0.22,
        "rz_opt": 0.48,
        "sigma": 0.19,
        "surf_opt": 0.44,
        "par_opt": 9.8,
    },
    "cowpeas": {
        "label_fr": "Niébé (Haricot)",
        "commodity_std": "Beans (niebe)",
        "ph_opt": (5.5, 7.5),
        "ph_tol": (5.0, 8.0),
        "preferred_textures": ("sandy", "sandy_loam", "loamy"),
        "min_wetness": 0.22,
        "rz_opt": 0.50,
        "sigma": 0.19,
        "surf_opt": 0.46,
        "par_opt": 9.7,
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
            "farmgate_discount_pct": 8.0,
            "enclavement_label": "GPS non fourni (décote minimale 8 % appliquée par défaut)",
            "remoteness_alert": False,
            "idw_mode": "single_hub" if resolved_hub else "none",
            "idw_hubs": (
                [{"hub": resolved_hub, "province": HUB_PROVINCE.get(resolved_hub), "distance_km": 0.0, "road_distance_km": 0.0, "weight": 1.0, "weight_pct": 100.0}]
                if resolved_hub
                else []
            ),
        }

    lat = float(gps_lat)
    lon = float(gps_lon)
    distances: list[tuple[str, float]] = []
    for hub, (h_lat, h_lon) in HUB_COORDINATES.items():
        distances.append((hub, haversine_km(lat, lon, h_lat, h_lon)))
    distances.sort(key=lambda item: item[1])
    closest_hub, min_hav_km = distances[0]

    # Sélection des 3 pôles les plus proches et calcul des poids IDW (1/d^2)
    top3 = distances[:3]
    if min_hav_km <= 5.0:
        idw_mode = "direct_hub"
        idw_hubs = [
            {
                "hub": h,
                "province": HUB_PROVINCE.get(h),
                "distance_km": round(d, 1),
                "road_distance_km": round(d * ROAD_TORTUOSITY_FACTOR, 1),
                "weight": 1.0 if idx == 0 else 0.0,
                "weight_pct": 100.0 if idx == 0 else 0.0,
            }
            for idx, (h, d) in enumerate(top3)
        ]
    else:
        idw_mode = "idw_k3"
        raw_weights = [1.0 / max(d, 0.1) ** 2 for _, d in top3]
        total_w = sum(raw_weights) or 1.0
        idw_hubs = [
            {
                "hub": h,
                "province": HUB_PROVINCE.get(h),
                "distance_km": round(d, 1),
                "road_distance_km": round(d * ROAD_TORTUOSITY_FACTOR, 1),
                "weight": round(w / total_w, 4),
                "weight_pct": round((w / total_w) * 100.0, 1),
            }
            for (h, d), w in zip(top3, raw_weights)
        ]

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
        "idw_mode": idw_mode,
        "idw_hubs": idw_hubs,
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
    if "commodity_std" not in forecast_df.columns or "forecast_t1" not in forecast_df.columns:
        return None, None
    sub = forecast_df[forecast_df["commodity_std"] == commodity_std].dropna(subset=["forecast_t1"])
    if sub.empty:
        return None, None
    by_prov = sub.groupby("province")["forecast_t1"].mean()
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

    raw_stress = (
        min(float(stress_min_xaf_kg), p_ml)
        if (stress_min_xaf_kg and stress_min_xaf_kg > 0)
        else round(p_ml * max(0.5, 1.0 - mape_ratio), 1)
    )
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


ZONAL_SOIL_CAP = 22.0  # estimation SoilGrids de zone : jamais au niveau d'une mesure de parcelle (plafond sur 30)


def _soil_points(spec: dict[str, Any], ph: Optional[float], texture: str, om: Optional[float], *, label: str) -> tuple[float, list[dict[str, Any]], list[str]]:
    """Points pédologiques (base 17/30) d'une culture : pH, texture, matière organique. `label` = « labo » ou « SoilGrids, zonal »."""
    pts = 17.0
    criteria: list[dict[str, Any]] = []
    limiting: list[str] = []
    if ph is not None:
        lo_opt, hi_opt = spec["ph_opt"]
        lo_tol, hi_tol = spec["ph_tol"]
        if lo_opt <= ph <= hi_opt:
            pts += 6.0
            criteria.append({"factor": f"pH du sol ({label})", "status": "optimal", "value": ph})
        elif lo_tol <= ph <= hi_tol:
            pts += 2.0
            criteria.append({"factor": f"pH du sol ({label})", "status": "tolérable", "value": ph})
        else:
            pts -= 9.0
            limiting.append(f"pH hors plage ({ph:.1f}, attendu {lo_tol}–{hi_tol})")
            criteria.append({"factor": f"pH du sol ({label})", "status": "défavorable", "value": ph})
    if texture:
        if texture in spec["preferred_textures"]:
            pts += 4.5
            criteria.append({"factor": f"Texture du sol ({label})", "status": "adaptée", "value": texture})
        else:
            pts -= 4.5
            limiting.append(f"Texture « {texture} » peu adaptée")
            criteria.append({"factor": f"Texture du sol ({label})", "status": "limitant", "value": texture})
    if om is not None:
        if om >= 1.5:
            pts += 2.5
            criteria.append({"factor": f"Matière organique % ({label})", "status": "correcte", "value": om})
        elif om < 0.8:
            pts -= 4.0
            limiting.append(f"Matière organique faible ({om:.1f} %)")
            criteria.append({"factor": f"Matière organique % ({label})", "status": "faible", "value": om})
    return pts, criteria, limiting


def compute_weighted_score(
    *,
    zone: dict[str, Any],
    has_lab: bool,
    ph_val: Optional[float],
    texture_val: str,
    zonal_soil: Optional[dict[str, Any]] = None,
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
    if not has_lab and zonal_soil:
        raw, _c, _l = _soil_points(spec, zonal_soil["ph"], zonal_soil.get("texture") or "", zonal_soil.get("organic_matter_pct"), label="SoilGrids, zonal")
        soil_pts = max(3.0, min(ZONAL_SOIL_CAP, raw))
        soil_note = f"Estimé SoilGrids de la zone (plafonné à {ZONAL_SOIL_CAP:.0f}/30 : mesures labo requises pour le reste)"
        vigilances.append(f"Sol estimé par SoilGrids (pH zonal {zonal_soil['ph']:.1f}) : score pédologique plafonné à {ZONAL_SOIL_CAP:.0f}/30 sans mesures labo.")
    elif not has_lab:
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
        pred_col = "forecast_t1" if "forecast_t1" in scope_df.columns else None
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
            "source": "PAM-WFP (prévision FreeData.AI)",
        }
    return signals


def _latest_national_cereal_yield(national_rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    yields = [r for r in national_rows if national_indicator_key(r["indicator"]) == "cereal_yield"]
    if not yields:
        return None
    latest = max(yields, key=lambda r: r["reference_date"])
    return {"value_kg_ha": float(latest["value"]), "reference_date": latest["reference_date"], "source": latest["source"], "license": latest["license"]}


def _hub_climate_metrics(hub_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcule RZ_growing (juin-sept), Surf_growing, PAR moyen et années sèches (< 0.45 en juil-août) pour un pôle."""
    rz_vals: list[float] = []
    sf_vals: list[float] = []
    par_vals: list[float] = []
    crit_by_year: dict[int, list[float]] = {}
    for r in hub_rows:
        key = regional_indicator_key(r["indicator"])
        if not key:
            continue
        y, m = _year_month(r["reference_date"])
        val = float(r["value"])
        if key == "root_zone_wetness":
            if m in (6, 7, 8, 9):
                rz_vals.append(val)
            if m in (7, 8):
                crit_by_year.setdefault(y, []).append(val)
        elif key == "surface_wetness":
            if m in (6, 7, 8, 9):
                sf_vals.append(val)
        elif key == "par":
            par_vals.append(val)
    dry_years = sum(1 for vals in crit_by_year.values() if vals and (sum(vals) / len(vals)) < 0.45)
    return {
        "rz_growing": (sum(rz_vals) / len(rz_vals)) if rz_vals else None,
        "surf_growing": (sum(sf_vals) / len(sf_vals)) if sf_vals else None,
        "par_mean": (sum(par_vals) / len(par_vals)) if par_vals else None,
        "dry_years": float(dry_years),
    }


def compute_idw_interpolation(
    *,
    idw_hubs: list[dict[str, Any]],
    all_regional_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    forecast_df: Any = None,
    hist_df: Any = None,
    track_record: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Interpole les variables climatiques (NASA POWER) et les prix (WFP/FEWS NET) par IDW sur 3 pôles."""
    rows_by_hub: dict[str, list[dict[str, Any]]] = {}
    for r in (all_regional_rows or fallback_rows):
        reg = canonical_region(r.get("region"))
        if reg and reg != NATIONAL:
            rows_by_hub.setdefault(reg, []).append(r)

    weighted_climate: list[tuple[float, dict[str, Any]]] = []
    for h_info in idw_hubs:
        w = float(h_info.get("weight") or 0.0)
        if w <= 0:
            continue
        hub_name = h_info["hub"]
        h_rows = rows_by_hub.get(hub_name) or fallback_rows
        if h_rows:
            weighted_climate.append((w, _hub_climate_metrics(h_rows)))

    def _wavg(field: str) -> Optional[float]:
        num = 0.0
        den = 0.0
        for w, m in weighted_climate:
            val = m.get(field)
            if isinstance(val, (int, float)):
                num += w * float(val)
                den += w
        return round(num / den, 4) if den > 0 else None

    rz_parcel = _wavg("rz_growing")
    surf_parcel = _wavg("surf_growing")
    par_parcel = _wavg("par_mean")
    dry_years_idw = _wavg("dry_years") or 0.0

    # Prix IDW pondérés par les mêmes poids sur les 3 pôles
    idw_market: dict[str, dict[str, Any]] = {}
    tr = track_record or {}
    for crop_id, spec in SUPPORTED_AGRO_CROPS.items():
        comm = spec["commodity_std"]
        pred_num = pred_den = 0.0
        obs_num = obs_den = 0.0
        stress_num = stress_den = 0.0
        fc_month = None
        for h_info in idw_hubs:
            w = float(h_info.get("weight") or 0.0)
            if w <= 0:
                continue
            prov = h_info.get("province") or HUB_PROVINCE.get(h_info["hub"])
            sig = _extract_crop_market_signals(forecast_df, prov, track_record=tr).get(crop_id)
            if sig:
                if isinstance(sig.get("predicted_xaf_kg"), (int, float)):
                    pred_num += w * float(sig["predicted_xaf_kg"])
                    pred_den += w
                if isinstance(sig.get("last_observed_xaf_kg"), (int, float)):
                    obs_num += w * float(sig["last_observed_xaf_kg"])
                    obs_den += w
                fc_month = fc_month or sig.get("forecast_month")
            st = _historical_stress_min_price(hist_df, comm, prov)
            if isinstance(st, (int, float)):
                stress_num += w * float(st)
                stress_den += w

        pred_val = round(pred_num / pred_den, 1) if pred_den > 0 else None
        obs_val = round(obs_num / obs_den, 1) if obs_den > 0 else None
        stress_val = round(stress_num / stress_den, 1) if stress_den > 0 else None
        change_pct = round((pred_val - obs_val) / obs_val * 100.0, 1) if (pred_val and obs_val and obs_val > 0) else None
        rec = tr.get(comm) or {}
        mape = rec.get("mape_pct") if rec.get("mape_pct") is not None else rec.get("MAPE_pct")
        scope_label = (
            f"IDW ({', '.join(h['hub'] for h in idw_hubs if (h.get('weight') or 0) > 0)})"
            if len([h for h in idw_hubs if (h.get('weight') or 0) > 0]) > 1
            else (idw_hubs[0].get("province") if idw_hubs else "National")
        )
        if pred_val is not None or obs_val is not None:
            idw_market[crop_id] = {
                "commodity_std": comm,
                "scope": scope_label,
                "last_observed_xaf_kg": obs_val,
                "predicted_xaf_kg": pred_val,
                "stress_min_xaf_kg": stress_val,
                "change_pct": change_pct,
                "forecast_month": fc_month,
                "historical_mape_pct": round(float(mape), 2) if isinstance(mape, (int, float)) else None,
                "source": "FreeData.td / WFP-FEWS NET (IDW + Delta-Ridge ML)",
            }

    return {
        "rz_growing": rz_parcel,
        "surf_growing": surf_parcel,
        "par_mean": par_parcel,
        "dry_years": round(dry_years_idw, 2),
        "market_signals": idw_market,
    }


_SAHEL_PROVINCES = {"Kanem", "Lac", "Ouaddai", "Batha"}
_SOUDANO_SAHEL_PROVINCES = {"N'Djamena", "Guera", "Mayo-Kebbi Est", "Mayo-Kebbi Ouest"}
_SOUDAN_HUMID_PROVINCES = {"Logone Occidental", "Logone Oriental", "Mandoul", "Moyen-Chari"}


def _climatic_zone_for_province(province: Optional[str]) -> str:
    if province in _SAHEL_PROVINCES:
        return "sahel"
    if province in _SOUDAN_HUMID_PROVINCES:
        return "soudanienne"
    return "soudano_sahelienne"


def _calibrated_water_score(
    *,
    crop_id: str,
    zone_name: str,
    rz_val: float,
    dry_years: float,
    spec: dict[str, Any],
) -> tuple[float, Optional[str]]:
    """Calibre la composante Eau (0–50 pts) selon les zones climatiques du Tchad."""
    rz_opt = float(spec["rz_opt"])
    sigma = float(spec["sigma"])
    gauss_ratio = math.exp(-((rz_val - rz_opt) ** 2) / (2.0 * (sigma ** 2)))
    affinity = max(0.0, min(1.0, gauss_ratio - 0.06 * max(0.0, dry_years)))

    zone_bands: dict[str, dict[str, tuple[float, float]]] = {
        "sahel": {
            "millet": (42.0, 48.0),
            "sorghum": (36.0, 42.0),
            "groundnut_raw": (32.0, 38.0),
            "maize": (14.0, 22.0),
            "cowpeas": (38.0, 44.0),
            "sesame": (35.0, 41.0),
            "rice_local": (18.0, 26.0),
        },
        "soudano_sahelienne": {
            "millet": (43.0, 48.0),
            "sorghum": (43.0, 48.0),
            "groundnut_raw": (42.0, 47.0),
            "maize": (34.0, 39.0),
            "cowpeas": (40.0, 45.0),
            "sesame": (38.0, 44.0),
            "rice_local": (30.0, 38.0),
        },
        "soudanienne": {
            "maize": (44.0, 49.0),
            "groundnut_raw": (44.0, 49.0),
            "sorghum": (44.0, 49.0),
            "millet": (38.0, 42.0),
            "rice_local": (42.0, 48.0),
            "sesame": (38.0, 44.0),
            "cowpeas": (38.0, 44.0),
        },
    }
    lo, hi = zone_bands.get(zone_name, zone_bands["soudano_sahelienne"]).get(crop_id, (26.0, 40.0))
    score = round(lo + (hi - lo) * affinity, 1)
    if zone_name == "sahel" and crop_id == "maize":
        score = min(22.0, score)
        return score, "Maïs pluvial déconseillé sans irrigation d'appoint dans cette zone sahélienne"
    if zone_name == "soudano_sahelienne" and crop_id == "maize":
        return score, "Maïs pluvial en zone soudano-sahélienne : variétés hâtives (85–90 jours) requises"
    return score, None


def evaluate_field_assessment(
    *,
    region: Optional[str] = None,
    regional_rows: list[dict[str, Any]],
    national_rows: list[dict[str, Any]],
    all_regional_rows: Optional[list[dict[str, Any]]] = None,
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
    """Calcule un audit agronomique & économique différencié par culture (IDW GPS + Modèle Satellitaire 60 pts + Sol 40 pts)."""
    gps_logistics = compute_gps_logistics(gps_lat, gps_lon, province_hub=region)
    resolved_region = canonical_region(region) if region else gps_logistics.get("selected_hub")
    if not resolved_region or resolved_region == NATIONAL:
        resolved_region = gps_logistics.get("closest_hub") or "N'Djamena"

    zone = build_zone_profile(resolved_region, regional_rows, national_rows, today=today)
    province = zone.get("province")
    lab = dict(lab_soil_inputs or {})
    has_lab = has_lab_soil_measurements(lab)
    zonal_soil = zonal_soil_estimate(resolved_region)
    resolution_label = (
        "DIAGNOSTIC D'AUDIT PARCELLAIRE & MARCHÉ (PRÉ-ACHAT CERTIFIÉ)"
        if has_lab
        else "PRÉ-DIAGNOSTIC AGRO-CLIMATIQUE & ÉCONOMIQUE (MAILLE SATELLITAIRE GPS)"
    )
    confidence_short = "Satellite IDW + Labo" if has_lab else "Modèle Satellitaire IDW"
    confidence_label = (
        "Confiance Élevée : Satellite IDW + Mesures Labo Certifiées"
        if has_lab
        else (
            "Modèle Satellitaire IDW (Mesures labo non fournies)"
            if gps_logistics.get("gps_provided")
            else "Modèle Satellitaire Zonal (Mesures labo non fournies)"
        )
    )

    idw = compute_idw_interpolation(
        idw_hubs=gps_logistics.get("idw_hubs") or [],
        all_regional_rows=all_regional_rows or regional_rows,
        fallback_rows=regional_rows,
        forecast_df=forecast_df,
        hist_df=hist_df,
        track_record=track_record,
    )
    rz_parcel = idw.get("rz_growing")
    if rz_parcel is None:
        rz_parcel = (zone.get("latest", {}).get("root_zone_wetness") or {}).get("value")
    surf_parcel = idw.get("surf_growing")
    if surf_parcel is None:
        surf_parcel = (zone.get("latest", {}).get("surface_wetness") or {}).get("value")
    dry_years = float(idw.get("dry_years") or 0.0)

    requested = [c for c in (target_crops or list(SUPPORTED_AGRO_CROPS)) if c in SUPPORTED_AGRO_CROPS]
    if not requested:
        requested = list(SUPPORTED_AGRO_CROPS)

    market_signals = idw.get("market_signals") or _extract_crop_market_signals(forecast_df, province, track_record=track_record)
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

    climatic_zone = _climatic_zone_for_province(province)

    crop_results: list[dict[str, Any]] = []
    for crop_id in requested:
        spec = SUPPORTED_AGRO_CROPS[crop_id]
        limiting: list[str] = []
        criteria: list[dict[str, Any]] = []

        # A. Composante Agro-Climatique & Hydrique (0 à 50 points, calibrée par zone)
        if isinstance(rz_parcel, (int, float)):
            rz_val = float(rz_parcel)
            rz_opt = float(spec["rz_opt"])
            s_water, zone_note = _calibrated_water_score(
                crop_id=crop_id,
                zone_name=climatic_zone,
                rz_val=rz_val,
                dry_years=dry_years,
                spec=spec,
            )
            if zone_note:
                limiting.append(zone_note)
            elif rz_val < spec["min_wetness"]:
                limiting.append(f"Humidité racinaire basse ({rz_val:.2f} < {spec['min_wetness']:.2f})")
            criteria.append({
                "factor": "Agro-Climat & Hydrique NASA POWER (IDW)",
                "status": "favorable" if s_water >= 35.0 else ("modéré" if s_water >= 24.0 else "limitant"),
                "value": f"{s_water}/50 (RZ={rz_val:.2f}, opt={rz_opt:.2f}, zone={climatic_zone})",
            })
        else:
            s_water = 25.0

        # B. Composante Pédologique / Sol (0 à 30 points)
        if not has_lab and zonal_soil:
            raw, z_crit, z_lim = _soil_points(spec, zonal_soil["ph"], zonal_soil.get("texture") or "", zonal_soil.get("organic_matter_pct"), label="SoilGrids, zonal")
            s_soil = round(max(3.0, min(ZONAL_SOIL_CAP, raw)), 1)
            criteria.extend(z_crit)
            limiting.extend(z_lim)
            limiting.append(f"Sol estimé SoilGrids (zonal, plafonné à {ZONAL_SOIL_CAP:.0f}/30) : mesures labo requises pour un diagnostic de terrain.")
            criteria.append({"factor": "Estimation pédologique SoilGrids (zone)", "status": "estimé", "value": f"{s_soil}/30"})
        elif not has_lab:
            # Estimation satellitaire zonale (Surf/RZ + PAR), plafonnée à 15/30 pts
            if isinstance(surf_parcel, (int, float)) and isinstance(rz_parcel, (int, float)) and float(rz_parcel) > 0:
                ratio = float(surf_parcel) / float(rz_parcel)
                s_soil = round(max(9.0, min(15.0, 15.0 - abs(ratio - 0.95) * 8.0)), 1)
            else:
                s_soil = 12.0
            limiting.append("Estimé Satellite (Labo requis pour débloquer les 15 pts restants).")
            criteria.append({"factor": "Estimation pédologique satellitaire", "status": "estimé", "value": f"{s_soil}/30"})
        else:
            s_soil_raw = 17.0
            if ph_val is not None:
                lo_opt, hi_opt = spec["ph_opt"]
                lo_tol, hi_tol = spec["ph_tol"]
                if lo_opt <= ph_val <= hi_opt:
                    s_soil_raw += 6.0
                    criteria.append({"factor": "pH du sol (labo)", "status": "optimal", "value": ph_val})
                elif lo_tol <= ph_val <= hi_tol:
                    s_soil_raw += 2.0
                    criteria.append({"factor": "pH du sol (labo)", "status": "tolérable", "value": ph_val})
                else:
                    s_soil_raw -= 9.0
                    limiting.append(f"pH hors plage ({ph_val:.1f}, attendu {lo_tol}–{hi_tol})")
                    criteria.append({"factor": "pH du sol (labo)", "status": "défavorable", "value": ph_val})
            if texture_val:
                if texture_val in spec["preferred_textures"]:
                    s_soil_raw += 4.5
                    criteria.append({"factor": "Texture du sol (labo)", "status": "adaptée", "value": texture_val})
                else:
                    s_soil_raw -= 4.5
                    limiting.append(f"Texture « {texture_val} » peu adaptée")
                    criteria.append({"factor": "Texture du sol (labo)", "status": "limitant", "value": texture_val})
            if om_val is not None:
                if om_val >= 1.5:
                    s_soil_raw += 2.5
                    criteria.append({"factor": "Matière organique (%)", "status": "correcte", "value": om_val})
                elif om_val < 0.8:
                    s_soil_raw -= 4.0
                    limiting.append(f"Matière organique faible ({om_val:.1f} %)")
                    criteria.append({"factor": "Matière organique (%)", "status": "faible", "value": om_val})
            s_soil = round(max(3.0, min(30.0, s_soil_raw)), 1)

        # C. Composante Économique & Logistique Marché (0 à 20 points)
        mkt = market_signals.get(crop_id)
        d_hub = gps_logistics.get("distance_hub_km")
        s_mkt_raw = 11.0
        if isinstance(d_hub, (int, float)):
            if d_hub <= 15.0:
                s_mkt_raw += 5.0
            elif d_hub <= 50.0:
                s_mkt_raw += 2.5
            else:
                s_mkt_raw -= 3.0
        if mkt and isinstance(mkt.get("predicted_xaf_kg"), (int, float)):
            chg = mkt.get("change_pct")
            s_mkt_raw += 4.0 if (isinstance(chg, (int, float)) and chg >= 0) else 2.0
        s_mkt = round(max(4.0, min(20.0, s_mkt_raw)), 1)

        final_score = max(0, min(100, int(round(s_water + s_soil + s_mkt))))
        suitability_label = "Favorable" if final_score >= 70 else ("Modérée" if final_score >= 45 else "Défavorable")
        stress_min = (mkt or {}).get("stress_min_xaf_kg") or _historical_stress_min_price(hist_df, spec["commodity_std"], province)
        max_hub_p, max_hub_prov = _max_national_hub_price(forecast_df, spec["commodity_std"])
        disc_pct = float(gps_logistics.get("farmgate_discount_pct") or 8.0)
        econ = compute_verified_economics(
            crop_id=crop_id,
            area_hectares=area_hectares,
            yield_kg_ha=ref_yield,
            yield_source=yield_source,
            predicted_xaf_kg=mkt.get("predicted_xaf_kg") if mkt else None,
            mape_pct=mkt.get("historical_mape_pct") if mkt else None,
            stress_min_xaf_kg=stress_min,
            farmgate_discount_pct=disc_pct,
            max_hub_price_xaf_kg=max_hub_p,
            max_hub_province=max_hub_prov,
        )
        indicative_revenue_xaf = econ.get("ca_central_xaf")

        crop_results.append({
            "crop_id": crop_id,
            "label_fr": spec["label_fr"],
            "water_score": s_water,
            "satellite_score": s_water,
            "soil_score": s_soil,
            "market_score": s_mkt,
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

    # Unification stricte du bandeau résumé avec la meilleure culture (Eau /50 + Sol /30 + Marché /20)
    top_w = float(primary_crop["water_score"]) if primary_crop else 25.0
    top_s = float(primary_crop["soil_score"]) if primary_crop else 12.0
    top_m = float(primary_crop["market_score"]) if primary_crop else 11.0
    top_total = round(top_w + top_s + top_m, 1)
    top_verdict = "Favorable" if top_total >= 70.0 else ("Modéré — À sécuriser" if top_total >= 50.0 else "Risque élevé")

    strengths: list[str] = []
    vigilances: list[str] = []
    if isinstance(rz_parcel, (int, float)):
        if float(rz_parcel) >= 0.55:
            strengths.append(f"Humidité racinaire saisonnière favorable ({float(rz_parcel):.3f} en juin–sept., NASA POWER IDW).")
        else:
            vigilances.append(f"Humidité racinaire modérée/faible ({float(rz_parcel):.3f}) : privilégier des cycles courts (85–90 j).")
    if has_lab:
        if ph_val is not None and 5.8 <= ph_val <= 7.0:
            strengths.append(f"pH eau mesuré optimal ({ph_val:.1f}, norme 5.8–7.0).")
        elif ph_val is not None and ph_val < 5.5:
            vigilances.append(f"pH acide ({ph_val:.1f} < 5.5) : prévoir un amendement calcique (chaulage) avant labour.")
        if texture_val:
            strengths.append(f"Texture mesurée sur terrain : {texture_val}.")
    else:
        vigilances.append("Absence d'analyse physique de sol : réaliser 3 prélèvements composites (0–20 cm) avant engagement financier.")
    if isinstance(gps_logistics.get("distance_hub_km"), (int, float)):
        d_km = float(gps_logistics["distance_hub_km"])
        if d_km <= 20.0:
            strengths.append(f"Bonne accessibilité logistique ({d_km:.1f} km du pôle {gps_logistics.get('selected_hub')}).")
        elif d_km > 50.0:
            vigilances.append(f"Parcelle enclavée ({d_km:.1f} km du pôle) : décote bord-champ de 22 % appliquée.")

    soil_cross_check: Optional[dict[str, Any]] = None
    if has_lab and zonal_soil:
        soil_cross_check = {"zonal_ph": zonal_soil["ph"], "zonal_texture": zonal_soil.get("texture_usda"), "source": zonal_soil["provenance"]["source"]}
        if ph_val is not None:
            soil_cross_check["ph_gap"] = round(ph_val - zonal_soil["ph"], 2)
            if abs(ph_val - zonal_soil["ph"]) >= 1.0:
                vigilances.append(
                    f"pH mesuré ({ph_val:.1f}) éloigné de l'estimation zonale SoilGrids ({zonal_soil['ph']:.1f}) : vérifier le prélèvement ; la mesure de terrain prévaut."
                )
        if texture_val and zonal_soil.get("texture") and texture_val != zonal_soil["texture"]:
            soil_cross_check["texture_differs"] = True
    elif not has_lab and zonal_soil:
        vigilances.append(
            f"Sol de la zone estimé par SoilGrids (pH {zonal_soil['ph']:.1f}, texture {zonal_soil.get('texture_usda') or 'n/d'}) : indicatif, à confirmer par analyse."
        )

    weighted_score = {
        "total_score": top_total,
        "verdict": top_verdict,
        "rainy_season_root_wetness_mean": rz_parcel,
        "breakdown": {
            "hydric_security": {"score": top_w, "max": 50, "source": "NASA POWER Agro (IDW)"},
            "soil_quality": {
                "score": top_s,
                "max": 30,
                "note": (
                    "Mesuré sur terrain / labo" if has_lab
                    else (f"Estimé SoilGrids de la zone, plafonné à {ZONAL_SOIL_CAP:.0f}/30 (labo requis pour le reste)" if zonal_soil
                          else "Estimé Satellite (Labo requis pour débloquer les 15 pts restants)")
                ),
            },
            "market_logistics": {"score": top_m, "max": 20, "source": "WFP/FEWS NET + GPS"},
        },
        "strengths": strengths[:3],
        "vigilances": vigilances[:2],
    }

    # Bulletin Pédologique & Agro-Climatique (BLOC B + BLOC D)
    rz_latest_info = zone.get("zone_latest") or {} if "zone_latest" in zone else (zone.get("latest") or {})
    rz_norm = None
    rz_series = (zone.get("series") or {}).get("root_zone_wetness") or []
    rainy_norms = [float(p["baseline_mean"]) for p in rz_series if _year_month(p["reference_date"])[1] in (6, 7, 8, 9) and isinstance(p.get("baseline_mean"), (int, float))]
    if rainy_norms:
        rz_norm = round(sum(rainy_norms) / len(rainy_norms), 3)
    par_val = idw.get("par_mean") or ((rz_latest_info.get("par") or {}).get("value"))
    ratio_str = f"{(float(surf_parcel) / float(rz_parcel)):.2f}" if (isinstance(surf_parcel, (int, float)) and isinstance(rz_parcel, (int, float)) and float(rz_parcel) > 0) else "—"
    npk_parts = [f"{k.upper()}: {lab.get(k)}" for k in ("nitrogen", "phosphorus", "potassium") if lab.get(k) is not None and str(lab.get(k)).strip() != ""]
    lab_parameters = [
        {
            "parameter": "Humidité zone racinaire (Juin–Sept)",
            "value": f"{float(rz_parcel):.3f}" + (f" (Normale : {rz_norm:.3f})" if rz_norm else "") if isinstance(rz_parcel, (int, float)) else "—",
            "optimal": "0.55 – 0.75",
            "status": "Bon" if isinstance(rz_parcel, (int, float)) and float(rz_parcel) >= 0.55 else ("Modéré" if isinstance(rz_parcel, (int, float)) and float(rz_parcel) >= 0.40 else "Déficit"),
            "source": "NASA POWER Agro",
        },
        {
            "parameter": "Humidité de surface (0–5 cm)",
            "value": f"{float(surf_parcel):.3f}" if isinstance(surf_parcel, (int, float)) else "—",
            "optimal": "0.45 – 0.70",
            "status": "Bon" if isinstance(surf_parcel, (int, float)) and float(surf_parcel) >= 0.45 else "Déficit",
            "source": "NASA POWER Agro",
        },
        {
            "parameter": "Rayonnement solaire (PAR)",
            "value": f"{float(par_val):.1f} W/m²" if isinstance(par_val, (int, float)) else "—",
            "optimal": "8.5 – 10.5 W/m²",
            "status": "Bon" if isinstance(par_val, (int, float)) and 8.5 <= float(par_val) <= 10.5 else "Attention",
            "source": "NASA POWER Agro",
        },
        {
            "parameter": "Réaction du sol (pH eau)",
            "value": (
                f"{ph_val:.1f}" if ph_val is not None
                else (f"{zonal_soil['ph']:.1f} (estimation zonale SoilGrids)" if zonal_soil else "Non mesuré (0–20 cm)")
            ),
            "optimal": "5.8 – 7.0",
            "status": (
                ("Bon" if 5.8 <= ph_val <= 7.0 else "Attention") if ph_val is not None
                else (("Estimé — plutôt bon" if 5.8 <= zonal_soil["ph"] <= 7.0 else "Estimé — à surveiller") if zonal_soil else "À analyser")
            ),
            "source": "Labo / Terrain" if ph_val is not None else ("SoilGrids 2.0 (CC BY 4.0)" if zonal_soil else "Labo / Terrain"),
        },
        {
            "parameter": "Texture & Matière Organique",
            "value": (
                f"{texture_val or 'Texture N/A'}" + (f", MO {om_val:.1f} %" if om_val is not None else "")
                if (texture_val or om_val is not None)
                else (
                    f"{zonal_soil.get('texture_usda') or 'texture n/d'}"
                    + (f", MO ≈ {zonal_soil['organic_matter_pct']:.1f} % (estimation zonale SoilGrids)" if zonal_soil.get("organic_matter_pct") is not None else " (estimation zonale SoilGrids)")
                    if zonal_soil
                    else f"Estimé (Ratio Surf/RZ = {ratio_str})"
                )
            ),
            "optimal": "MO > 1.5 %",
            "status": ("Bon" if (om_val is not None and om_val >= 1.5) else ("Attention" if om_val is not None else "Estimé")) if (texture_val or om_val is not None) else "Estimé",
            "source": "Labo / Satellite",
        },
        {
            "parameter": "Éléments nutritifs (N-P-K)",
            "value": ", ".join(npk_parts) if npk_parts else "À analyser en laboratoire",
            "optimal": "Selon culture",
            "status": "Mesuré" if npk_parts else "À analyser",
            "source": "Labo / World Bank",
        },
    ]

    prescriptions: list[str] = []
    primary_label = (primary_crop or {}).get("label_fr") or "Culture principale"
    rz_str = f"{float(rz_parcel):.3f}" if isinstance(rz_parcel, (int, float)) else "N/A"
    diff_rz = f" ({float(rz_parcel) - rz_norm:+.3f} vs normale)" if (isinstance(rz_parcel, (int, float)) and rz_norm) else ""
    if climatic_zone == "soudanienne" and not (isinstance(rz_parcel, (int, float)) and float(rz_parcel) < 0.55) and dry_years < 1:
        cycle_rec = "privilégier des variétés améliorées à cycle intermédiaire (95–110 jours) avec semis groupé dès installation des pluies."
    else:
        cycle_rec = "privilégier des variétés hâtives (cycle court 85–90 jours) avec paillage de conservation pour sécuriser la fin de cycle."
    prescriptions.append(
        f"Conseil variétal & calendrier ({primary_label}) : {cycle_rec} (humidité racinaire {rz_str}{diff_rz})."
    )

    if not has_lab:
        prescriptions.append(
            "Protocole d'échantillonnage sol (labo non fourni) : réaliser 3 prélèvements composites à 0–20 cm de profondeur et demander en laboratoire : pH eau, granulométrie, carbone organique, N total, P assimilable et K échangeable."
        )
    elif ph_val is not None and ph_val < 5.5:
        prescriptions.append(f"Correction pédologique (pH acide {ph_val:.1f} < 5.5) : prévoir un amendement calcique (chaulage) avant labour et un apport organique.")
    elif ph_val is not None and ph_val > 7.8:
        prescriptions.append(f"Correction pédologique (pH alcalin {ph_val:.1f} > 7.8) : incorporer du compost / matière organique (> 1.5 %) pour tamponner le sol.")
    else:
        prescriptions.append("Suivi pédologique : paramètres mesurés compatibles ; maintenir une fumure organo-minérale fractionnée (N-P-K) au sarclage.")

    pecon = (primary_crop or {}).get("verified_economics") or {}
    fg_p = pecon.get("farmgate_price_central_xaf_kg")
    arb = pecon.get("arbitrage_bonus") or {}
    sel_hub = gps_logistics.get("selected_hub") or zone["region"]
    d_hub_km = gps_logistics.get("distance_hub_km")
    disc_val = gps_logistics.get("farmgate_discount_pct", 8)
    if fg_p is not None and arb.get("target_province") and arb.get("spread_xaf_kg"):
        gain_sac = round(float(arb["spread_xaf_kg"]) * 100.0)
        prescriptions.append(
            f"Commercialisation & logistique ({primary_label}) : prix bord-champ estimé à {fg_p} FCFA/kg ; le marché déficitaire le plus rémunérateur est {arb['target_province']} ({arb['target_price_xaf_kg']} FCFA/kg), soit un gain brut potentiel de +{gain_sac:,} FCFA par sac de 100 kg (hors transport).".replace(",", " ")
        )
    elif fg_p is not None:
        d_txt = f" ({d_hub_km:.1f} km du pôle {sel_hub})" if isinstance(d_hub_km, (int, float)) else f" (pôle {sel_hub})"
        prescriptions.append(
            f"Commercialisation & logistique ({primary_label}) : prix bord-champ estimé à {fg_p} FCFA/kg après décote logistique de -{disc_val}%{d_txt}."
        )

    if climatic_zone == "sahel":
        prescriptions.append(
            "Alerte climatique sahélienne : Maïs pluvial déconseillé sans irrigation d'appoint dans cette zone sahélienne ; sécuriser le bilan hydrique par zaï ou diguettes anti-érosives."
        )
    elif dry_years >= 1:
        prescriptions.append(
            f"Risque hydrique interannuel : {dry_years:g} année(s) critique(s) (< 0.45 en juil.–août) détectée(s) ; prévoir un semis échelonné et des diguettes anti-érosives."
        )

    return {
        "title": resolution_label,
        "resolution_label": resolution_label,
        "confidence": confidence_short,
        "region": zone["region"],
        "province": province,
        "has_lab_measurements": has_lab,
        "confidence_level": (
            "Satellite IDW + Labo Certifié"
            if has_lab
            else "Satellite IDW Uniquement — En attente d'analyse physique"
        ),
        "gps_logistics": gps_logistics,
        "idw_climate": {
            "rz_growing": rz_parcel,
            "surf_growing": surf_parcel,
            "par_mean": par_val,
            "dry_years": dry_years,
        },
        "weighted_score": weighted_score,
        "soil_basis": "lab" if has_lab else ("soilgrids_zonal" if zonal_soil else "satellite_proxy"),
        "soil_zonal_estimate": zonal_soil,
        "soil_cross_check": soil_cross_check,
        "site_profile": site_profile(resolved_region),
        "bulletin": {
            "lab_parameters": lab_parameters,
            "prescriptions": prescriptions,
        },
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
    """Porte QA (6 dimensions) : délivre le PDF en mode Pré-diagnostic Satellitaire OU Audit Parcellaire Certifié."""
    scores = assessment.get("computed_scores") or {}
    has_lab = bool(scores.get("has_lab_measurements"))
    blockers: list[str] = []
    warnings: list[str] = []
    if not has_lab:
        soil_basis = scores.get("soil_basis")
        soil_cap = 22 if soil_basis == "soilgrids_zonal" else 15 if soil_basis == "satellite_proxy" else None
        soil_method = (
            "estimation zonale SoilGrids"
            if soil_basis == "soilgrids_zonal"
            else "proxy satellitaire"
            if soil_basis == "satellite_proxy"
            else "estimation non caractérisée"
        )
        cap_text = f" (plafond du modèle : {soil_cap}/30 pts)" if soil_cap is not None else ""
        warnings.append(
            f"Mesures sol laboratoire non fournies : la composante sol repose sur une {soil_method}{cap_text} et doit être confirmée par une analyse physique."
        )
    if not assessment.get("province_hub"):
        blockers.append("Pôle régional manquant.")
    if not scores.get("crop_assessments"):
        blockers.append("Aucune culture cible évaluée.")
    prov = scores.get("provenance") or {}
    if not prov.get("sources") or not prov.get("licenses"):
        blockers.append("Provenance (source/licence) incomplète.")

    dimensions = {
        "data_quality": "pass" if has_lab else "estimated_satellite",
        "traceability": "pass" if (prov.get("sources") and assessment.get("report_verification_code")) else "fail",
        "completeness": "pass" if scores.get("crop_assessments") else "fail",
        "transparency": "pass" if scores.get("limitations") else "fail",
        "compliance": "pass",
        "coherence": "pass",
    }
    return {
        "can_deliver_pdf": len(blockers) == 0,
        "qa_mode": "CERTIFIED_FIELD_AUDIT" if has_lab else "SATELLITE_ESTIMATION",
        "qa_badge": "QA TERRAIN VALIDÉ" if has_lab else "ESTIMATION SATELLITAIRE GPS",
        "warnings": warnings,
        "blockers": blockers,
        "dimensions": dimensions,
    }


def build_campaign_radar(
    all_rows: list[dict[str, Any]],
    *,
    forecast_df: Any = None,
    hist_df: Any = None,
    track_record: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Radar National Agro-Marché : croise risque hydrique (NASA POWER), rendement (World Bank) et prix ML t+1 sur les 12 pôles."""
    national_rows = [r for r in all_rows if r.get("region") == NATIONAL]
    by_hub: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        reg = canonical_region(r.get("region"))
        if reg and reg != NATIONAL:
            by_hub.setdefault(reg, []).append(r)

    wb_yield = _latest_national_cereal_yield(national_rows)
    ref_yield = float(wb_yield["value_kg_ha"]) if (wb_yield and wb_yield.get("value_kg_ha")) else WORLD_BANK_DEFAULT_YIELD_KG_HA

    hubs_out: list[dict[str, Any]] = []
    for hub in sorted(by_hub.keys()):
        regional = by_hub[hub]
        zone = build_zone_profile(hub, regional, national_rows, today=today)
        province = zone.get("province") or HUB_PROVINCE.get(hub)
        risks = zone.get("hydric_risk_signals") or {}
        crit_years = int(risks.get("critical_july_aug_years") or 0)
        obs_years = int(risks.get("observed_july_aug_years") or 0)
        false_start = bool(risks.get("false_sowing_start"))
        dry_freq_pct = round(crit_years / obs_years * 100.0, 1) if obs_years > 0 else 0.0

        rz_pts = (zone.get("series") or {}).get("root_zone_wetness") or []
        rz_anom = rz_pts[-1].get("anomaly_pct") if rz_pts else None
        metrics = _hub_climate_metrics(regional)
        rz_grow = metrics.get("rz_growing")

        signals = _extract_crop_market_signals(forecast_df, province, track_record=track_record)
        best_crop: Optional[dict[str, Any]] = None
        any_price_spike = False
        for crop_id, spec in SUPPORTED_AGRO_CROPS.items():
            sig = signals.get(crop_id) or {}
            pred_p = sig.get("predicted_xaf_kg")
            chg = sig.get("change_pct")
            if isinstance(chg, (int, float)) and chg >= 10.0:
                any_price_spike = True
            if isinstance(rz_grow, (int, float)):
                w_sc = 50.0 * math.exp(-((float(rz_grow) - float(spec["rz_opt"])) ** 2) / (2.0 * (float(spec["sigma"]) ** 2))) - (4.0 * crit_years)
                w_sc = round(max(8.0, min(50.0, w_sc)), 1)
            else:
                w_sc = 25.0
            ca_ha = round(ref_yield * float(pred_p) * 0.92) if isinstance(pred_p, (int, float)) else None
            cand = {
                "crop_id": crop_id,
                "label_fr": spec["label_fr"],
                "water_score": w_sc,
                "predicted_xaf_kg": pred_p,
                "change_pct": chg,
                "ca_per_ha_xaf": ca_ha,
            }
            if best_crop is None or (
                (cand["ca_per_ha_xaf"] or 0) * (cand["water_score"] / 50.0)
                > (best_crop["ca_per_ha_xaf"] or 0) * (best_crop["water_score"] / 50.0)
            ):
                best_crop = cand

        hydric_stress = (isinstance(rz_anom, (int, float)) and float(rz_anom) <= MODERATE_DEFICIT_PCT) or false_start
        double_vuln = bool(hydric_stress and any_price_spike)
        if crit_years >= 3 or double_vuln:
            credit_risk = "Élevé"
        elif crit_years >= 1 or hydric_stress:
            credit_risk = "Modéré"
        else:
            credit_risk = "Maîtrisé"

        hubs_out.append({
            "region": hub,
            "province": province,
            "root_anomaly_pct": rz_anom,
            "false_sowing_start": false_start,
            "critical_july_aug_years": crit_years,
            "observed_july_aug_years": obs_years,
            "dry_year_freq_pct": dry_freq_pct,
            "double_vulnerability": double_vuln,
            "credit_risk_level": credit_risk,
            "best_crop": best_crop,
        })

    hubs_out.sort(key=lambda h: (h["double_vulnerability"], (h.get("best_crop") or {}).get("ca_per_ha_xaf") or 0), reverse=True)
    top_opp = max(hubs_out, key=lambda h: (h.get("best_crop") or {}).get("ca_per_ha_xaf") or 0) if hubs_out else None

    return {
        "title": "Radar National Agro-Marché (Alerte Précoce & Allocation Campagne)",
        "summary": {
            "hubs_count": len(hubs_out),
            "double_vulnerability_count": sum(1 for h in hubs_out if h["double_vulnerability"]),
            "top_opportunity_hub": top_opp["region"] if top_opp else None,
            "top_opportunity_crop": (top_opp.get("best_crop") or {}).get("label_fr") if top_opp else None,
            "top_opportunity_ca_ha_xaf": (top_opp.get("best_crop") or {}).get("ca_per_ha_xaf") if top_opp else None,
            "cereal_yield_ref_kg_ha": round(ref_yield, 1),
        },
        "hubs": hubs_out,
        "sources": [
            "NASA POWER Agro (Public Domain)",
            "World Bank (CC BY 4.0)",
            "WFP (CC BY-IGO 3.0)",
            "FEWS NET (Attribution Required)",
        ],
        "limitations": list(LIMITATIONS),
    }


