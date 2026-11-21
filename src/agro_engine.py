"""Moteur agro-climatique déterministe (V1) : anomalies d'humidité des sols et alertes de déficit hydrique.

Principes :
- uniquement les indicateurs réellement ingérés (humidité racinaire, humidité de surface, PAR) ;
- AUCUNE température ni précipitation en V1 (absentes du jeu de données) ;
- anomalie = écart à la normale 2020–2023 du MÊME mois calendaire, calculée seulement si ≥ 3 années de référence ;
- les seuils d'alerte sont des repères de lecture indicatifs (non calibrés sur des rendements) et sont exposés dans la réponse.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from src.agro_indicators import (
    HUB_PROVINCE,
    NATIONAL,
    build_provenance,
    national_indicator_key,
    regional_indicator_key,
)

BASELINE_YEARS: tuple[int, int] = (2020, 2023)
MIN_BASELINE_YEARS = 3
MODERATE_DEFICIT_PCT = -20.0
SEVERE_DEFICIT_PCT = -35.0
STALE_AFTER_MONTHS = 3
WETNESS_KEYS = ("root_zone_wetness", "surface_wetness")

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
    region: str,
    regional_rows: list[dict[str, Any]],
    national_rows: list[dict[str, Any]],
    lab_soil_inputs: Optional[dict[str, Any]] = None,
    target_crops: Optional[list[str]] = None,
    area_hectares: Optional[float] = None,
    forecast_df: Any = None,
    track_record: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Calcule un diagnostic agronomique explicable croisant mesures labo (si fournies), humidité NASA POWER et prix."""
    zone = build_zone_profile(region, regional_rows, national_rows, today=today)
    province = zone.get("province")
    lab = dict(lab_soil_inputs or {})
    has_lab = has_lab_soil_measurements(lab)
    resolution_label = "Diagnostic de terrain (pré-achat)" if has_lab else "Pré-diagnostic de zone (indicatif)"
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
        indicative_revenue_xaf = None
        if area_hectares and area_hectares > 0 and mkt and mkt.get("predicted_xaf_kg") and cereal_yield and crop_id in ("millet", "sorghum", "maize"):
            indicative_revenue_xaf = round(float(area_hectares) * cereal_yield["value_kg_ha"] * float(mkt["predicted_xaf_kg"]))

        crop_results.append({
            "crop_id": crop_id,
            "label_fr": spec["label_fr"],
            "suitability_score": final_score,
            "suitability_label": suitability_label,
            "limiting_factors": limiting,
            "criteria": criteria,
            "market_forecast": mkt,
            "indicative_gross_revenue_xaf": indicative_revenue_xaf,
        })

    crop_results.sort(key=lambda c: c["suitability_score"], reverse=True)
    return {
        "title": resolution_label,
        "resolution_label": resolution_label,
        "confidence": confidence_short,
        "region": zone["region"],
        "province": province,
        "has_lab_measurements": has_lab,
        "confidence_level": confidence_label,
        "hydric_risk_signals": zone.get("hydric_risk_signals"),
        "zone_alerts": zone["alerts"],
        "zone_latest": zone["latest"],
        "crop_assessments": crop_results,
        "cereal_yield_reference": cereal_yield,
        "provenance": zone["provenance"],
        "national_provenance": zone["national"]["provenance"],
        "limitations": list(LIMITATIONS),
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


