"""Indicateurs agricoles du Tchad (table_agro_indicators) : ingestion stricte et lecture.

Sources autorisées dans le moteur :
- NASA POWER Agro (domaine public U.S. Government / NASA) : humidité des sols et PAR ;
- NASA POWER (CC BY 4.0 dans le catalogue FreeData) : précipitations et températures mensuelles ;
- World Bank (CC BY 4.0) : macro-agriculture nationale, annuel.

Open-Meteo Free API (usage non commercial uniquement) et FAOSTAT (restrictions de promotion commerciale) sont exclus du pipeline commercial.
Toute ligne ingérée porte source, licence, date de référence, résolution spatiale et niveau de confiance.
Aucune donnée n'est jamais inventée : l'ingestion est « tout ou rien » et rapporte chaque anomalie du fichier.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src import db as _db

SECTOR = "agriculture"
COUNTRY_CODE = "TCD"
NATIONAL = "national"

# Les 12 pôles couverts par NASA POWER Agro (graphie canonique).
HUBS: tuple[str, ...] = (
    "Abeche", "Ati", "Bol", "Bongor", "Doba", "Koumra",
    "Mao", "Mongo", "Moundou", "N'Djamena", "Pala", "Sarh",
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "sector", "indicator", "value", "unit", "reference_date", "country_code", "region",
    "source", "license", "collected_at", "spatial_resolution", "confidence_level",
)

# source -> (préfixe de licence attendu, résolution spatiale, niveau de confiance)
SOURCE_RULES: dict[str, tuple[str, str, str]] = {
    "nasa power agro": ("public domain", "regional_city_hub", "Satellite_Modeled_Regional"),
    "nasa power": ("cc by 4.0", "regional_city_hub", "Satellite_Modeled_Regional"),
    "world bank": ("cc by 4.0", "national", "Official_Macro_National"),
}
SOURCE_CANONICAL = {
    "nasa power agro": "NASA POWER Agro",
    "nasa power": "NASA POWER",
    "world bank": "World Bank",
}

# Indicateurs régionaux NASA POWER Agro reconnus (préfixe normalisé -> clé technique).
REGIONAL_INDICATOR_KEYS: tuple[tuple[str, str], ...] = (
    ("root zone soil wetness", "root_zone_wetness"),
    ("surface soil wetness", "surface_wetness"),
    ("photosynthetically active radiation", "par"),
    ("monthly precipitation", "precipitation_daily_mean"),
    ("monthly mean temperature", "temperature_mean"),
    ("monthly max temperature", "temperature_max"),
    ("monthly min temperature", "temperature_min"),
)

_NATIONAL_ALIASES = {"national", "tchad", "chad", "tcd", "country"}


class AgroIngestError(ValueError):
    """Fichier refusé : contient au moins une ligne ou une colonne non conforme."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("Ingestion refusée : " + " | ".join(problems[:5]) + (" …" if len(problems) > 5 else ""))


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(text))


_HUB_BY_KEY = {_alnum(h): h for h in HUBS}

# Province de rattachement de chaque pôle, telle qu'écrite dans le jeu de données (« Ville (Province) »).
HUB_PROVINCE: dict[str, str] = {
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
_REGION_RE = re.compile(r"^\s*([^()]+?)\s*(?:\(([^()]+)\))?\s*$")


def parse_region(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Analyse « Moundou (Logone Occidental) » -> ("Moundou", "Logone Occidental") ; « national » -> ("national", None).

    Retourne (None, None) si le pôle est inconnu ou si la province entre parenthèses ne correspond pas au pôle.
    """
    match = _REGION_RE.match(str(raw or ""))
    if not match:
        return None, None
    name, province = match.group(1), match.group(2)
    key = _alnum(name)
    if key in _NATIONAL_ALIASES and province is None:
        return NATIONAL, None
    hub = _HUB_BY_KEY.get(key)
    if hub is None:
        return None, None
    if province is not None and _alnum(province) != _alnum(HUB_PROVINCE[hub]):
        return None, None
    return hub, HUB_PROVINCE[hub]


def canonical_region(raw: str) -> Optional[str]:
    """Retourne le pôle canonique (ex. « Abéché (Ouaddaï) » -> « Abeche »), « national », ou None si inconnu."""
    return parse_region(raw)[0]


def regional_indicator_key(indicator: str) -> Optional[str]:
    folded = _fold(indicator)
    for prefix, key in REGIONAL_INDICATOR_KEYS:
        if folded.startswith(prefix):
            return key
    return None


def national_indicator_key(indicator: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _fold(indicator)).strip("_")
    return slug[:80]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if value is pd.NaT:
            return True
    except Exception:  # pragma: no cover
        pass
    return str(value).strip() == ""


def validate_agro_dataframe(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Valide intégralement le fichier. Lève AgroIngestError listant les problèmes ; sinon (lignes propres, rapport)."""
    lowered = {str(c).strip().lower(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c not in lowered]
    if missing:
        raise AgroIngestError([f"Colonnes obligatoires manquantes : {', '.join(missing)}"])
    work = df.rename(columns={orig: low for low, orig in lowered.items()})
    dropped = [c for c in ("source_url",) if c in work.columns]
    work = work.drop(columns=dropped, errors="ignore")

    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    for pos, rec in enumerate(work.to_dict("records"), start=2):  # ligne 1 = en-tête CSV
        def bad(msg: str) -> None:
            if len(problems) < 200:
                problems.append(f"ligne {pos} : {msg}")

        if any(_blank(rec.get(c)) for c in REQUIRED_COLUMNS):
            blanks = [c for c in REQUIRED_COLUMNS if _blank(rec.get(c))]
            bad(f"valeur manquante ({', '.join(blanks)})")
            continue
        src_key = _fold(rec["source"])
        if src_key not in SOURCE_RULES:
            bad(f"source non autorisée en production : « {rec['source']} »")
            continue
        expected_sector = "environment" if src_key == "nasa power" else SECTOR
        if _fold(rec["sector"]) != expected_sector:
            bad(f"secteur « {rec['sector']} » ≠ {expected_sector}")
            continue
        if str(rec["country_code"]).strip().upper() != COUNTRY_CODE:
            bad(f"pays « {rec['country_code']} » ≠ TCD")
            continue
        lic_prefix, spatial, confidence = SOURCE_RULES[src_key]
        if not _fold(rec["license"]).startswith(lic_prefix):
            bad(f"licence « {rec['license']} » incompatible avec la source {SOURCE_CANONICAL[src_key]}")
            continue
        if str(rec["spatial_resolution"]).strip() != spatial or str(rec["confidence_level"]).strip() != confidence:
            bad(f"résolution/confiance incohérentes avec la source {SOURCE_CANONICAL[src_key]}")
            continue
        region = canonical_region(rec["region"])
        if region is None:
            bad(f"région inconnue ou province incohérente « {rec['region']} »")
            continue
        if spatial == "regional_city_hub" and region == NATIONAL:
            bad("donnée NASA POWER rattachée au niveau national")
            continue
        if spatial == "national" and region != NATIONAL:
            bad("donnée World Bank rattachée à une ville")
            continue
        if spatial == "regional_city_hub" and regional_indicator_key(str(rec["indicator"])) is None:
            bad(f"indicateur régional non reconnu : « {rec['indicator']} »")
            continue
        try:
            value = float(rec["value"])
        except (TypeError, ValueError):
            bad(f"valeur non numérique « {rec['value']} »")
            continue
        if not math.isfinite(value):
            bad("valeur non finie")
            continue
        ind_key = regional_indicator_key(str(rec["indicator"])) if spatial == "regional_city_hub" else None
        if ind_key in ("root_zone_wetness", "surface_wetness") and not (-1e-9 <= value <= 1 + 1e-9):
            bad(f"indice d'humidité hors de l'intervalle physique [0, 1] : {value}")
            continue
        if ind_key == "par" and value < 0:
            bad(f"rayonnement négatif : {value}")
            continue
        if ind_key == "precipitation_daily_mean" and (value < 0 or value > 100):
            bad(f"précipitations moyennes quotidiennes hors plage [0, 100] mm/jour : {value}")
            continue
        if ind_key in ("temperature_mean", "temperature_max", "temperature_min") and not (-20 <= value <= 70):
            bad(f"température hors plage plausible [-20, 70] °C : {value}")
            continue
        ref = pd.to_datetime(rec["reference_date"], errors="coerce")
        if pd.isna(ref):
            bad(f"date de référence invalide « {rec['reference_date']} »")
            continue
        collected = pd.to_datetime(rec["collected_at"], errors="coerce")
        if pd.isna(collected):
            bad(f"collected_at invalide « {rec['collected_at']} »")
            continue
        try:
            rid = int(rec["id"]) if "id" in rec and not _blank(rec.get("id")) else pos - 1
        except (TypeError, ValueError):
            bad(f"id non entier « {rec.get('id')} »")
            continue
        rows.append({
            "id": rid,
            "sector": expected_sector,
            "indicator": str(rec["indicator"]).strip(),
            "value": value,
            "unit": str(rec["unit"]).strip(),
            "reference_date": ref.date().isoformat(),
            "country_code": COUNTRY_CODE,
            "region": region,
            "source": SOURCE_CANONICAL[src_key],
            "license": str(rec["license"]).strip(),
            "notes": "" if _blank(rec.get("notes")) else str(rec["notes"]).strip(),
            "collected_at": collected.isoformat(timespec="seconds"),
            "spatial_resolution": spatial,
            "confidence_level": confidence,
        })
    if problems:
        raise AgroIngestError(problems)

    # Doublons sur la clé naturelle : on garde la dernière occurrence (et on le rapporte).
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for r in rows:
        unique[(r["indicator"], r["region"], r["reference_date"], r["source"])] = r
    clean = list(unique.values())
    by_source: dict[str, int] = {}
    by_indicator: dict[str, int] = {}
    for r in clean:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        by_indicator[r["indicator"]] = by_indicator.get(r["indicator"], 0) + 1
    dates = sorted(r["reference_date"] for r in clean)
    report = {
        "rows_in": int(len(df)),
        "rows_valid": len(clean),
        "duplicates_collapsed": len(rows) - len(clean),
        "dropped_columns": dropped,
        "by_source": by_source,
        "by_indicator": by_indicator,
        "regions": sorted({r["region"] for r in clean}),
        "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None},
    }
    return clean, report


class AgroIndicatorStore:
    """Stockage SQLite (local) ou PostgreSQL (schéma privé freedata_app) des indicateurs agricoles."""

    _COLUMNS = (
        "id", "sector", "indicator", "value", "unit", "reference_date", "country_code", "region",
        "source", "license", "notes", "collected_at", "spatial_resolution", "confidence_level",
    )

    def __init__(self, db_path: Optional[str] = None, *, database_url: Optional[str] = None, schema: Optional[str] = None) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = (
            _db.validate_schema(schema)
            if schema
            else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        )
        self.db_path = Path(db_path or os.getenv("FREEDATA_AGRO_DB_PATH", "data/freedata_agro.db"))
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
                CREATE TABLE IF NOT EXISTS table_agro_indicators (
                    id INTEGER NOT NULL,
                    sector TEXT NOT NULL DEFAULT 'agriculture',
                    indicator TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    reference_date TEXT NOT NULL,
                    country_code TEXT NOT NULL DEFAULT 'TCD',
                    region TEXT NOT NULL,
                    source TEXT NOT NULL,
                    license TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    collected_at TEXT NOT NULL,
                    spatial_resolution TEXT NOT NULL,
                    confidence_level TEXT NOT NULL,
                    PRIMARY KEY (indicator, region, reference_date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_agro_ind_region
                    ON table_agro_indicators(region, indicator, reference_date);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    # --- Ingestion -----------------------------------------------------------------
    def ingest_dataframe(self, df: pd.DataFrame, *, dry_run: bool = False, chunk_size: int = 50) -> dict[str, Any]:
        rows, report = validate_agro_dataframe(df)
        report["dry_run"] = bool(dry_run)
        if dry_run:
            report["written"] = 0
            return report
        cols = ", ".join(self._COLUMNS)
        one = "(" + ", ".join("?" for _ in self._COLUMNS) + ")"
        update = ", ".join(
            f"{c} = excluded.{c}"
            for c in self._COLUMNS
            if c not in ("indicator", "region", "reference_date", "source")
        )
        with self._connect() as conn:
            for start in range(0, len(rows), max(1, chunk_size)):
                chunk = rows[start:start + chunk_size]
                params: list[Any] = []
                for r in chunk:
                    params.extend(r[c] for c in self._COLUMNS)
                conn.execute(
                    f"INSERT INTO table_agro_indicators ({cols}) VALUES {', '.join([one] * len(chunk))} "
                    f"ON CONFLICT (indicator, region, reference_date, source) DO UPDATE SET {update}",
                    params,
                )
        report["written"] = len(rows)
        return report

    def ingest_csv(self, path: str, *, dry_run: bool = False) -> dict[str, Any]:
        df = pd.read_csv(path)
        return self.ingest_dataframe(df, dry_run=dry_run)

    # --- Lecture -------------------------------------------------------------------
    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM table_agro_indicators").fetchone()
        return int(row["n"]) if row else 0

    def rows(self, *, region: Optional[str] = None, spatial_resolution: Optional[str] = None) -> list[dict[str, Any]]:
        sql = f"SELECT {', '.join(self._COLUMNS)} FROM table_agro_indicators"
        clauses: list[str] = []
        params: list[Any] = []
        if region:
            clauses.append("region = ?")
            params.append(region)
        if spatial_resolution:
            clauses.append("spatial_resolution = ?")
            params.append(spatial_resolution)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY indicator, region, reference_date"
        with self._connect() as conn:
            fetched = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in fetched]

    def regional_rows(self, region: str) -> list[dict[str, Any]]:
        return self.rows(region=region, spatial_resolution="regional_city_hub")

    def national_rows(self) -> list[dict[str, Any]]:
        return self.rows(region=NATIONAL, spatial_resolution="national")


def build_provenance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bloc de provenance obligatoire : source(s), licence(s), période, résolution spatiale, confiance."""
    if not rows:
        return {"sources": [], "licenses": [], "reference_period": None, "spatial_resolution": [], "confidence_level": []}
    dates = sorted(r["reference_date"] for r in rows)
    return {
        "sources": sorted({r["source"] for r in rows}),
        "licenses": sorted({r["license"] for r in rows}),
        "reference_period": {"first": dates[0], "last": dates[-1]},
        "spatial_resolution": sorted({r["spatial_resolution"] for r in rows}),
        "confidence_level": sorted({r["confidence_level"] for r in rows}),
    }

