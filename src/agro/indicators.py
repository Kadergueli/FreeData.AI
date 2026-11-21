"""Indicateurs agro-climatiques (Gold public) : 12 hubs, NASA POWER mensuel + Banque mondiale annuel.

Règles (spec « zéro donnée inventée ») :
- chaque ligne porte source, licence, reference_date, spatial_resolution et confidence_level ;
- aucune ligne sans valeur numérique ; pas de température ni de précipitations en V1 ;
- Open-Meteo Agro-Climate et FAOSTAT sont exclus de ce pipeline.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

SECTOR = "agriculture"
COUNTRY = "TCD"

# Libellés de licence. À confirmer auprès des conditions d'utilisation officielles avant publication
# commerciale : une seule constante à modifier, aucune autre ligne du code n'en dépend.
LICENSE_NASA = "Public Domain (U.S. Government / NASA)"
LICENSE_WB = "CC BY 4.0"

SOURCE_NASA = "NASA POWER (Agroclimatology)"
SOURCE_WB = "World Bank Open Data"

RES_HUB = "regional_city_hub"
RES_NATIONAL = "national"
CONF_SAT = "Satellite_Modeled_Regional"
CONF_OFFICIAL = "Official_Macro_National"

# 12 hubs : nom -> province (libellés sans accents, comme la table Gold des prix).
HUBS: dict[str, str] = {
    "Abeche": "Ouaddai",
    "Ati": "Batha",
    "Bol": "Lac",
    "Bongor": "Mayo-Kebbi Est",
    "Doba": "Logone Oriental",
    "Koumra": "Mandoul",
    "Mao": "Kanem",
    "Mongo": "Guera",
    "Moundou": "Logone Occidental",
    "N'Djamena": "N'Djamena",
    "Pala": "Mayo-Kebbi Ouest",
    "Sarh": "Moyen-Chari",
}

# colonne du CSV NASA -> (indicateur publié, unité)
NASA_COLUMNS: dict[str, tuple[str, str]] = {
    "root_zone_wetness": ("root_zone_soil_wetness", "fraction (0-1)"),
    "surface_wetness": ("surface_soil_wetness", "fraction (0-1)"),
    "par_w_m2": ("photosynthetically_active_radiation", "W/m2"),
}

# Banque mondiale : liste blanche (V1). Rien d'autre n'est accepté.
WB_INDICATORS: frozenset[str] = frozenset({
    "cereal_production", "cereal_yield", "crop_production_index", "food_production_index",
    "agricultural_land_area", "agricultural_land_share", "arable_land_share", "forest_area_share",
    "fertilizer_consumption", "agriculture_value_added_pct_gdp", "employment_in_agriculture",
})

NASA_INDICATORS: frozenset[str] = frozenset(v[0] for v in NASA_COLUMNS.values())
ALL_INDICATORS = NASA_INDICATORS | WB_INDICATORS

_ALLOWED_LICENSES = frozenset({LICENSE_NASA, LICENSE_WB})
_ALLOWED_RES = frozenset({RES_HUB, RES_NATIONAL})
_ALLOWED_CONF = frozenset({CONF_SAT, CONF_OFFICIAL})

REQUIRED_FIELDS = (
    "sector", "indicator", "value", "unit", "reference_date", "country_code",
    "region", "source", "license", "collected_at", "spatial_resolution", "confidence_level",
)

CONFLICT_COLS = "indicator,region,reference_date,source"


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)).strip().lower()


_HUB_BY_FOLD = {_fold(h): h for h in HUBS}
_LABEL_RE = re.compile(r"^\s*(?P<hub>.+?)\s*\((?P<prov>.+)\)\s*$")


def normalize_hub(label: Any) -> Optional[str]:
    """« Abeche (Ouaddai) », « Abéché » ou « abeche » -> « Abeche » ; None si ce n'est pas l'un des 12 hubs."""
    if not isinstance(label, str):
        return None
    m = _LABEL_RE.match(label)
    name = m.group("hub") if m else label
    return _HUB_BY_FOLD.get(_fold(name))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nasa_wide_to_rows(df: pd.DataFrame, *, collected_at: Optional[str] = None) -> tuple[list[dict], list[str]]:
    """CSV large (région, mois, 3 colonnes) -> lignes longues conformes. Retourne (lignes, avertissements)."""
    missing = {"region", "reference_date", *NASA_COLUMNS} - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes : {sorted(missing)}")
    stamp = collected_at or _now_iso()
    rows: list[dict] = []
    warnings: list[str] = []
    unknown: set[str] = set()
    for rec in df.to_dict(orient="records"):
        hub = normalize_hub(rec["region"])
        if hub is None:
            unknown.add(str(rec["region"]))
            continue
        ref = pd.to_datetime(rec["reference_date"], errors="coerce")
        if pd.isna(ref):
            warnings.append(f"date invalide ignorée pour {hub}: {rec['reference_date']!r}")
            continue
        for col, (indicator, unit) in NASA_COLUMNS.items():
            val = pd.to_numeric(rec[col], errors="coerce")
            if pd.isna(val) or val <= -990:  # -999 = valeur manquante NASA POWER
                continue
            rows.append({
                "sector": SECTOR, "indicator": indicator, "value": round(float(val), 4), "unit": unit,
                "reference_date": ref.strftime("%Y-%m-01"), "country_code": COUNTRY, "region": hub,
                "source": SOURCE_NASA, "license": LICENSE_NASA, "notes": "Moyenne mensuelle, grille NASA POWER autour du hub.",
                "collected_at": stamp, "spatial_resolution": RES_HUB, "confidence_level": CONF_SAT,
            })
    if unknown:
        warnings.append(f"régions hors des 12 hubs ignorées : {sorted(unknown)}")
    return rows, warnings


def worldbank_long_to_rows(df: pd.DataFrame, *, collected_at: Optional[str] = None) -> list[dict]:
    """CSV long (indicator, year, value, unit) -> lignes nationales ; indicateurs hors liste blanche rejetés."""
    missing = {"indicator", "year", "value", "unit"} - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes : {sorted(missing)}")
    stamp = collected_at or _now_iso()
    rows: list[dict] = []
    for rec in df.to_dict(orient="records"):
        ind = str(rec["indicator"]).strip()
        if ind not in WB_INDICATORS:
            raise ValueError(f"Indicateur Banque mondiale non autorisé en V1 : {ind!r}")
        val = pd.to_numeric(rec["value"], errors="coerce")
        year = pd.to_numeric(rec["year"], errors="coerce")
        if pd.isna(val) or pd.isna(year):
            continue
        rows.append({
            "sector": SECTOR, "indicator": ind, "value": float(val), "unit": str(rec["unit"]),
            "reference_date": f"{int(year)}-01-01", "country_code": COUNTRY, "region": "Tchad",
            "source": SOURCE_WB, "license": LICENSE_WB, "notes": "",
            "collected_at": stamp, "spatial_resolution": RES_NATIONAL, "confidence_level": CONF_OFFICIAL,
        })
    return rows


def validate_rows(rows: Iterable[dict]) -> list[str]:
    """Liste d'erreurs (vide = conforme). Refuse toute ligne sans provenance complète ou hors périmètre V1."""
    errors: list[str] = []
    seen: set[tuple] = set()
    for i, r in enumerate(rows):
        for f in REQUIRED_FIELDS:
            if r.get(f) in (None, "") or (isinstance(r.get(f), float) and pd.isna(r.get(f))):
                errors.append(f"ligne {i}: champ obligatoire absent « {f} »")
        if "source_url" in r:
            errors.append(f"ligne {i}: « source_url » n'est pas publié (champ vide interdit)")
        if r.get("sector") != SECTOR or r.get("country_code") != COUNTRY:
            errors.append(f"ligne {i}: secteur/pays inattendus")
        if r.get("indicator") not in ALL_INDICATORS:
            errors.append(f"ligne {i}: indicateur hors périmètre V1 « {r.get('indicator')} »")
        if r.get("license") not in _ALLOWED_LICENSES:
            errors.append(f"ligne {i}: licence non autorisée « {r.get('license')} »")
        if r.get("spatial_resolution") not in _ALLOWED_RES or r.get("confidence_level") not in _ALLOWED_CONF:
            errors.append(f"ligne {i}: résolution spatiale / niveau de confiance invalide")
        is_nasa = r.get("indicator") in NASA_INDICATORS
        if is_nasa and (r.get("source") != SOURCE_NASA or r.get("license") != LICENSE_NASA
                        or r.get("spatial_resolution") != RES_HUB or r.get("confidence_level") != CONF_SAT
                        or r.get("region") not in HUBS):
            errors.append(f"ligne {i}: ligne NASA incohérente (source/licence/résolution/hub)")
        if not is_nasa and (r.get("source") != SOURCE_WB or r.get("license") != LICENSE_WB
                            or r.get("spatial_resolution") != RES_NATIONAL or r.get("confidence_level") != CONF_OFFICIAL):
            errors.append(f"ligne {i}: ligne Banque mondiale incohérente")
        key = (r.get("indicator"), r.get("region"), r.get("reference_date"), r.get("source"))
        if key in seen:
            errors.append(f"ligne {i}: doublon {key}")
        seen.add(key)
    return errors


def load_nasa_csv(path: str | Path) -> tuple[list[dict], list[str]]:
    rows, warnings = nasa_wide_to_rows(pd.read_csv(path))
    errs = validate_rows(rows)
    if errs:
        raise ValueError("; ".join(errs[:5]))
    return rows, warnings


def indicators_frame(rows: Optional[Iterable[dict]]) -> pd.DataFrame:
    """Lignes Gold -> DataFrame typé ; les lignes non conformes sont écartées (jamais affichées sans provenance)."""
    cols = list(REQUIRED_FIELDS) + ["notes"]
    df = pd.DataFrame(list(rows or []))
    if df.empty or not set(REQUIRED_FIELDS) <= set(df.columns):
        return pd.DataFrame(columns=cols)
    if "notes" not in df.columns:
        df["notes"] = ""
    df = df[cols].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["reference_date"] = df["reference_date"].astype(str).str[:10]
    ok = df["value"].notna() & df["indicator"].isin(ALL_INDICATORS) & df["license"].isin(_ALLOWED_LICENSES)
    ok &= df["spatial_resolution"].isin(_ALLOWED_RES) & df["confidence_level"].isin(_ALLOWED_CONF)
    return df[ok].reset_index(drop=True)
