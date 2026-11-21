"""Évaluation de terrain (Agronome PRO) : validation des mesures de sol, QA gate sur le titre, co-branding."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from src.agro.indicators import normalize_hub
from src.agro.zone import RESOLUTION_NOTICE, ZONE_TITLE

TITLE_FIELD = "Diagnostic de terrain (pré-achat)"
TITLE_ZONE_ONLY = "Pré-diagnostic Zonal Uniquement"

SOIL_TEXTURES = ("sable", "sablo-limoneux", "limon", "limono-argileux", "argile")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f<>]")
MAX_SAMPLE_AGE_DAYS = 730


def _clean(text: Any, limit: int) -> str:
    return _CTRL_RE.sub(" ", str(text or "")).strip()[:limit]


def parse_soil(raw: Optional[dict], *, today: Optional[date] = None) -> tuple[dict, bool]:
    """Valide les mesures de sol. Retourne (mesures propres, complètes?). Valeur fournie mais invalide -> ValueError."""
    today = today or date.today()
    raw = raw or {}
    soil: dict[str, Any] = {}
    errors: list[str] = []

    ph = raw.get("ph")
    if ph not in (None, ""):
        try:
            ph = float(ph)
            if not 3.0 <= ph <= 10.0:
                raise ValueError
            soil["ph"] = round(ph, 2)
        except (TypeError, ValueError):
            errors.append("pH hors plage (3,0 à 10,0)")
    om = raw.get("organic_matter_pct")
    if om not in (None, ""):
        try:
            om = float(om)
            if not 0.0 <= om <= 25.0:
                raise ValueError
            soil["organic_matter_pct"] = round(om, 2)
        except (TypeError, ValueError):
            errors.append("matière organique hors plage (0 à 25 %)")
    tex = raw.get("texture")
    if tex not in (None, ""):
        if str(tex).lower() not in SOIL_TEXTURES:
            errors.append(f"texture inconnue (attendu : {', '.join(SOIL_TEXTURES)})")
        else:
            soil["texture"] = str(tex).lower()
    sd = raw.get("sampling_date")
    if sd not in (None, ""):
        try:
            d = date.fromisoformat(str(sd)[:10])
            if d > today:
                errors.append("date de prélèvement dans le futur")
            elif (today - d).days > MAX_SAMPLE_AGE_DAYS:
                errors.append("prélèvement de plus de 24 mois : refaire une mesure")
            else:
                soil["sampling_date"] = d.isoformat()
        except ValueError:
            errors.append("date de prélèvement invalide (AAAA-MM-JJ)")
    lab = _clean(raw.get("lab_name"), 80)
    if lab:
        soil["lab_name"] = lab
    if errors:
        raise ValueError("; ".join(errors))
    complete = "ph" in soil and "sampling_date" in soil and ("organic_matter_pct" in soil or "texture" in soil)
    return soil, complete


def parse_branding(raw: Optional[dict]) -> dict:
    raw = raw or {}
    color = str(raw.get("primary_color") or "")
    return {
        "organization_name": _clean(raw.get("organization_name"), 80),
        "agronomist_name": _clean(raw.get("agronomist_name"), 80),
        "primary_color": color if _COLOR_RE.match(color) else "#1B5E20",
    }


def _ph_band(ph: float) -> str:
    if ph < 5.5:
        return "acide"
    if ph < 6.5:
        return "légèrement acide"
    if ph <= 7.5:
        return "proche de la neutralité"
    return "alcalin"


def _om_band(om: float) -> str:
    return "faible" if om < 1 else "moyenne" if om < 3 else "élevée"


def build_field_assessment(
    zone: dict, soil_raw: Optional[dict], branding_raw: Optional[dict] = None, *,
    crop: Optional[str] = None, today: Optional[date] = None,
) -> dict[str, Any]:
    """Assemble l'évaluation. `zone` = build_zone_prediagnosis(). Aucune valeur n'est inventée."""
    hub = normalize_hub(zone.get("hub"))
    if hub is None:
        raise KeyError("Hub inconnu")
    soil, complete = parse_soil(soil_raw, today=today)
    title = TITLE_FIELD if complete else TITLE_ZONE_ONLY

    findings: list[str] = []
    if "ph" in soil:
        findings.append(f"pH mesuré {soil['ph']} : sol {_ph_band(soil['ph'])} (repère générique, non spécifique à une culture).")
    if "organic_matter_pct" in soil:
        findings.append(f"Matière organique {soil['organic_matter_pct']} % : teneur {_om_band(soil['organic_matter_pct'])} (repère générique).")
    for ind in zone["indicators"]:
        h = ind.get("history_same_month")
        if h and ind["indicator"] == "root_zone_soil_wetness":
            findings.append(
                f"Humidité racinaire de la zone ({ind['value']}) : {int(h['percentile'])}e percentile des {h['years_compared']} "
                f"mêmes mois observés depuis 2020 (moyenne {h['mean']})."
            )

    all_prov = all(
        all(i["provenance"].get(k) for k in ("source", "license", "reference_date", "spatial_resolution", "confidence_level"))
        for i in zone["indicators"]
    )
    stale = [i["label"] for i in zone["indicators"] if i["stale"]]
    checks = [
        {"code": "provenance_complete", "ok": all_prov, "detail": "Source, licence, date, résolution et confiance présentes sur chaque indicateur."},
        {"code": "soil_measures_complete", "ok": complete, "detail": "pH + date de prélèvement + (matière organique ou texture)."},
        {"code": "zone_data_fresh", "ok": not stale, "detail": "Indicateurs satellitaires de moins de 3 mois." if not stale else f"Indicateurs anciens : {', '.join(stale)}."},
        {"code": "no_temperature_precipitation", "ok": not any("temp" in i["indicator"] or "precip" in i["indicator"] for i in zone["indicators"]),
         "detail": "Aucune température ni précipitation en V1."},
    ]
    if not all_prov:
        raise ValueError("Provenance incomplète : évaluation refusée.")
    return {
        "title": title, "downgraded": not complete,
        "downgrade_reason": None if complete else "Mesures de sol absentes ou incomplètes : seul le pré-diagnostic de zone est délivré.",
        "hub": hub, "region": zone["region"], "crop": _clean(crop, 60) or None,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zone_title": ZONE_TITLE, "zone_indicators": zone["indicators"], "soil": soil, "findings": findings,
        "resolution_notice": RESOLUTION_NOTICE, "branding": parse_branding(branding_raw),
        "qa": {"status": "passed" if complete and all(c["ok"] for c in checks) else "downgraded" if not complete else "warning", "checks": checks},
        "disclaimer": "Document d'aide à la décision. Il ne remplace ni une analyse agronomique de terrain ni un titre foncier.",
    }
