"""Importe les variables climatiques NASA POWER déjà collectées dans table_public.

Cette extension réutilise l'écran Agriculture existant. Elle n'utilise PAS Open-Meteo
(Free API non-commerciale) ni FAOSTAT (restrictions de promotion commerciale).

Usage :
    python scripts/ingest_nasa_power_climate.py --dry-run
    SUPABASE_DB_URL=... python scripts/ingest_nasa_power_climate.py --apply

L'import ne copie que les 12 pôles déjà couverts par le diagnostic agricole.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.agro_indicators import AgroIndicatorStore, HUBS, REQUIRED_COLUMNS, SUPPORTED_REGIONS, canonical_region

API_INDICATORS = (
    "Monthly precipitation",
    "Monthly mean temperature",
    "Monthly max temperature",
    "Monthly min temperature",
)
SELECT = "date_reference,indicateur,region,valeur,unite,source_api,secteur,licence"


def fetch_source_rows() -> list[dict]:
    """Lit la table publique par pages sans utiliser de clé privilégiée."""
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL et SUPABASE_KEY publique sont requis.")
    endpoint = f"{settings.supabase_url.rstrip('/')}/rest/v1/table_public"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Accept": "application/json",
    }
    indicator_filter = 'in.(' + ",".join(f'"{name}"' for name in API_INDICATORS) + ')'
    rows: list[dict] = []
    offset = 0
    while True:
        response = requests.get(
            endpoint,
            headers=headers,
            params={
                "select": SELECT,
                "source_api": "in.(\"NASA POWER\",\"Copernicus ERA5-Land\")",
                "secteur": "eq.environment",
                "indicateur": indicator_filter,
                "order": "date_reference.asc",
                "limit": 1000,
                "offset": offset,
            },
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += len(batch)
    return rows


def to_agro_dataframe(source_rows: list[dict]) -> pd.DataFrame:
    """Convertit les observations source en lignes contrôlables par AgroIndicatorStore."""
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict] = []
    for idx, item in enumerate(source_rows, start=1):
        region = canonical_region(str(item.get("region") or ""))
        if region not in SUPPORTED_REGIONS:
            continue
        source = str(item.get("source_api") or "").strip()
        if source not in {"NASA POWER", "Copernicus ERA5-Land"} or item.get("secteur") != "environment":
            continue
        rows.append({
            "id": idx,
            "sector": "environment",
            "indicator": str(item.get("indicateur") or ""),
            "value": item.get("valeur"),
            "unit": str(item.get("unite") or ""),
            "reference_date": str(item.get("date_reference") or ""),
            "country_code": "TCD",
            "region": region,
            "source": source,
            "license": str(item.get("licence") or ""),
            "notes": f"{source} monthly climate indicator; imported from public.table_public.",
            "collected_at": collected_at,
            "spatial_resolution": "regional_city_hub",
            "confidence_level": "Satellite_Modeled_Regional",
        })
    # Garder le schéma même si aucune ligne ne passe les filtres : cela évite
    # une erreur trompeuse « colonnes obligatoires manquantes » sur un DataFrame vide.
    return pd.DataFrame(rows, columns=["id", *REQUIRED_COLUMNS, "notes"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Import NASA POWER climate indicators into AgroIndicatorStore.")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; no database writes (default).")
    parser.add_argument("--apply", action="store_true", help="Write validated rows to SUPABASE_DB_URL.")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("Choisissez --dry-run ou --apply, pas les deux.")
    if args.apply and not settings.supabase_db_url:
        parser.error("--apply exige SUPABASE_DB_URL pour éviter toute écriture locale accidentelle.")

    try:
        source_rows = fetch_source_rows()
        if not source_rows:
            raise RuntimeError(
                "Aucune observation ne correspond aux filtres de lecture dans public.table_public "
                "(source_api NASA POWER/Copernicus ERA5-Land, secteur environment et indicateurs "
                "climatiques mensuels). Vérifiez les valeurs réellement stockées dans source_api, "
                "secteur et indicateur ; aucune écriture n'a été effectuée."
            )
        frame = to_agro_dataframe(source_rows)
        if frame.empty:
            examples = [
                {key: item.get(key) for key in ("region", "source_api", "secteur", "indicateur")}
                for item in source_rows[:5]
            ]
            raise RuntimeError(
                f"{len(source_rows)} observation(s) récupérée(s), mais aucune ne correspond aux "
                f"régions prises en charge par AgroIndicatorStore. Exemples (métadonnées uniquement) : "
                f"{json.dumps(examples, ensure_ascii=False)}. Aucune écriture n'a été effectuée."
            )
        store = AgroIndicatorStore()
        report = store.ingest_dataframe(frame, dry_run=not args.apply)
    except Exception as exc:
        print(f"IMPORT REFUSÉ : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report["source_rows_fetched"] = len(source_rows)
    report["nasa_power_hubs_in_scope"] = list(HUBS)
    report["copernicus_regions_in_scope"] = list(SUPPORTED_REGIONS)
    report["sources_in_scope"] = ["NASA POWER", "Copernicus ERA5-Land"]
    report["write_target"] = "SUPABASE_DB_URL" if args.apply else "none (dry-run)"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.apply:
        print(f"Total table_agro_indicators après import : {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
