"""Profil de site d'un pôle agricole : sol (SoilGrids) et climat (NASA POWER), plus moteur d'aptitude FAO prêt à l'emploi.

Données reprises de FreeData.td (app/crops). Sources et licences vérifiées le 22 nov. 2026 :
- SoilGrids 2.0 (ISRIC) : CC BY 4.0 (usage commercial permis, attribution obligatoire) ;
- NASA POWER : NASA indique « no restrictions on the use of these data » (citation demandée ; ne pas suggérer
  l'aval de la NASA) ;
- FAO EcoCrop : NON livré. Les conditions de la FAO interdisent d'utiliser ses jeux de données « for or in
  conjunction with the promotion of a commercial enterprise » ; tant que la FAO ne l'autorise pas par écrit, le
  fichier `requirements.json` reste absent et le moteur d'aptitude est inactif (`engine_available() == False`).

Fonctions pures, sans réseau. Aucune valeur n'est inventée : un pôle sans donnée renvoie None.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from src.agro_indicators import canonical_region

DATA_DIR = Path(__file__).with_name("agro_site_data")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
DAYS = (31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
WET_MONTH_MM = 50  # un mois est « humide » à partir de 50 mm
GERMINATION_MM = 20
SOIL_MAX_PENALTY = 0.4  # choix de modélisation (non FAO) : le pH retire au plus 40 % du score climatique
VERDICTS = [(0.8, "very_suitable"), (0.6, "suitable"), (0.4, "marginal"), (0.0, "unsuitable")]

SOIL_PROVENANCE = {
    "source": "SoilGrids 2.0 (ISRIC)", "license": "CC BY 4.0",
    "attribution": "Poggio et al. 2021, ISRIC – World Soil Information, https://www.isric.org/explore/soilgrids",
    "spatial_resolution": "regional_city_hub", "confidence_level": "Satellite_Modeled_Regional",
    "note": "Moyenne pondérée 0-30 cm au point central de la zone (ou médiane des points voisins si le centre est masqué).",
}
CLIMATE_PROVENANCE = {
    "source": "NASA POWER (climatologie mensuelle)", "license": "NASA : aucune restriction d'usage, citation requise",
    "attribution": "NASA Prediction of Worldwide Energy Resources (POWER), https://power.larc.nasa.gov/",
    "spatial_resolution": "regional_city_hub", "confidence_level": "Satellite_Modeled_Regional",
    "note": "Moyenne mensuelle au point central de la zone ; la période de la moyenne n'est pas précisée dans le fichier source.",
}


def _load(name: str) -> dict[str, dict[str, Any]]:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    regions = json.loads(path.read_text(encoding="utf-8")).get("regions", {})
    out: dict[str, dict[str, Any]] = {}
    for key, value in regions.items():
        hub = canonical_region(key)
        if hub and hub != "national":
            out[hub] = value
    return out


@lru_cache(maxsize=1)
def _soils() -> dict[str, dict[str, Any]]:
    return _load("soils.json")


@lru_cache(maxsize=1)
def _climate() -> dict[str, dict[str, Any]]:
    return _load("climate.json")


def rainy_season(rain_mm_day: dict[str, float], temp_c: dict[str, float]) -> dict[str, Any]:
    """Saison des pluies à partir de 12 moyennes mensuelles. Sans mois humide : saison vide, pluie/température de l'année."""
    monthly = [float(rain_mm_day[m]) * DAYS[i] for i, m in enumerate(MONTHS)]
    temps = [float(temp_c[m]) for m in MONTHS]
    wet = [i for i, mm in enumerate(monthly) if mm >= WET_MONTH_MM]
    annual = sum(monthly)
    if wet:
        rain = sum(monthly[i] for i in wet)
        temp = sum(temps[i] for i in wet) / len(wet)
        days = sum(DAYS[i] for i in wet)
    else:
        rain, temp, days = annual, sum(temps) / 12, 0.0
    return {"rain_mm": round(rain, 1), "temp_mean_c": round(temp, 2), "season_days": round(days),
            "annual_rain_mm": round(annual, 1), "wet_months": [MONTHS[i] for i in wet]}


def site_profile(region: str) -> Optional[dict[str, Any]]:
    """Sol + climat du pôle, avec provenance. None si le lieu n'est pas un des pôles connus ou sans aucune donnée."""
    hub = canonical_region(region)
    if hub is None or hub == "national":
        return None
    soil, climate = _soils().get(hub), _climate().get(hub)
    if not soil and not climate:
        return None
    out: dict[str, Any] = {"hub": hub, "soil": None, "climate": None}
    if soil:
        out["soil"] = {
            "ph": soil.get("ph"), "clay_pct": soil.get("clay_pct"), "sand_pct": soil.get("sand_pct"),
            "organic_carbon_g_kg": soil.get("organic_carbon_g_kg"), "approx_distance_km": soil.get("approx_distance_km"),
            "provenance": SOIL_PROVENANCE,
        }
    if climate:
        out["climate"] = {
            "monthly_rain_mm": {m: round(float(climate["rain_mm_day"][m]) * DAYS[i], 1) for i, m in enumerate(MONTHS)},
            "monthly_temp_c": {m: round(float(climate["temp_c"][m]), 2) for m in MONTHS},
            "rainy_season": rainy_season(climate["rain_mm_day"], climate["temp_c"]),
            "provenance": CLIMATE_PROVENANCE,
        }
    return out


# ── Moteur d'aptitude FAO (inactif tant que les besoins des cultures ne sont pas licenciés) ──────────────────

def trapezoid(x: float, abs_min: float, opt_min: float, opt_max: float, abs_max: float) -> float:
    if x <= abs_min or x >= abs_max:
        return 0.0
    if opt_min <= x <= opt_max:
        return 1.0
    return (x - abs_min) / (opt_min - abs_min) if x < opt_min else (abs_max - x) / (abs_max - opt_max)


def verdict_for(score: float) -> str:
    return next(name for threshold, name in VERDICTS if score >= threshold)


@lru_cache(maxsize=1)
def load_requirements() -> dict[str, dict[str, Any]]:
    path = DATA_DIR / "requirements.json"
    return json.loads(path.read_text(encoding="utf-8")).get("crops", {}) if path.exists() else {}


def engine_available() -> bool:
    return bool(load_requirements())


def assess_crop(crop: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Le climat décide (facteur le plus limitant : pluie, température, durée de saison) ; le pH retire au plus 40 %."""
    season = (profile.get("climate") or {}).get("rainy_season")
    ph = (profile.get("soil") or {}).get("ph")
    factors: dict[str, dict[str, float]] = {}
    unknown: list[str] = []
    if season:
        factors["rain_mm"] = {"value": season["rain_mm"], "score": round(trapezoid(season["rain_mm"], *crop["rain_mm"]), 3)}
        factors["temp_mean_c"] = {"value": season["temp_mean_c"], "score": round(trapezoid(season["temp_mean_c"], *crop["temp_mean_c"]), 3)}
        factors["season_days"] = {"value": season["season_days"],
                                  "score": round(min(1.0, season["season_days"] / crop["cycle_days"][0]), 3)}
    else:
        unknown += ["rain_mm", "temp_mean_c"]
    if ph is not None:
        factors["ph"] = {"value": float(ph), "score": round(trapezoid(float(ph), *crop["ph"]), 3)}
    else:
        unknown.append("ph")
    core = [f for f in factors if f != "ph"]
    if not core:
        return {"score": None, "verdict": "unknown", "limiting": None, "factors": factors, "unknown": unknown}
    limiting = min(core, key=lambda f: factors[f]["score"])
    climate_score = factors[limiting]["score"]
    ph_score = factors["ph"]["score"] if "ph" in factors else 1.0
    score = round(climate_score * (1 - SOIL_MAX_PENALTY * (1 - ph_score)), 3)
    return {"score": score, "verdict": verdict_for(score), "limiting": limiting, "factors": factors, "unknown": unknown}


def sowing_calendar(crop: dict[str, Any], profile: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    """12 mois de semis pluvial : climat du cycle qui suit, comparé aux besoins de la culture."""
    climate = profile.get("climate")
    if not climate:
        return None
    rain = [climate["monthly_rain_mm"][m] for m in MONTHS]
    temp = [climate["monthly_temp_c"][m] for m in MONTHS]
    low, high = crop["cycle_days"]
    n = max(1, round((low + high) / 2 / 30.4))
    out = []
    for start in range(12):
        window = [(start + k) % 12 for k in range(n)]
        score = 0.0 if rain[start] < GERMINATION_MM else min(
            trapezoid(sum(rain[i] for i in window), *crop["rain_mm"]),
            trapezoid(sum(temp[i] for i in window) / n, *crop["temp_mean_c"]))
        out.append({"month": start + 1, "score": round(score, 3), "verdict": verdict_for(score), "cycle_end": window[-1] + 1})
    return out
