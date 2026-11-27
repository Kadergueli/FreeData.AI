"""Importe les variables climatiques NASA POWER/Copernicus déjà collectées.

La lecture de public.table_public est réservée au backend : RLS est activée et
aucune politique anon n'est définie. Le dry-run lit donc via SUPABASE_DB_URL
(transaction SQL READ ONLY), ou via SUPABASE_SERVICE_ROLE_KEY côté serveur.
La clé anon n'est volontairement jamais utilisée pour cette table.

Usage :
    python scripts/ingest_nasa_power_climate.py --dry-run
    SUPABASE_DB_URL=... python scripts/ingest_nasa_power_climate.py --apply

L'import ne copie que les 23 pôles/régions déjà couverts par AgroIndicatorStore.
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
from src.agro_indicators import AgroIndicatorStore, HUBS, REQUIRED_COLUMNS, SUPPORTED_REGIONS, canonical_region, validate_agro_dataframe

API_SOURCES = ("NASA POWER", "Copernicus ERA5-Land")
API_INDICATORS = (
    "Monthly precipitation",
    "Monthly mean temperature",
    "Monthly max temperature",
    "Monthly min temperature",
)
SELECT = "date_reference,indicateur,region,valeur,unite,source_api,secteur,licence"


def _fetch_source_rows_postgres() -> list[dict]:
    """Lit la table source dans une transaction PostgreSQL explicitement READ ONLY."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(settings.supabase_db_url, connect_timeout=10)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {SELECT} FROM public.table_public "
                "WHERE source_api = ANY(%s) AND secteur = %s AND indicateur = ANY(%s) "
                "ORDER BY date_reference ASC",
                (list(API_SOURCES), "environment", list(API_INDICATORS)),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        # La transaction ne contient que des SELECT et est toujours annulée à la fermeture.
        try:
            conn.rollback()
        finally:
            conn.close()


def _fetch_source_rows_service_role() -> list[dict]:
    """Lit via PostgREST avec la clé serveur, jamais avec la clé anon."""
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "Lecture de public.table_public impossible avec la clé anon : RLS est activée "
            "sans politique de lecture publique. Configurez SUPABASE_DB_URL (recommandé) "
            "ou SUPABASE_SERVICE_ROLE_KEY dans l'environnement local du script. "
            "Ne placez jamais la clé service_role dans le frontend."
        )
    endpoint = f"{settings.supabase_url.rstrip('/')}/rest/v1/table_public"
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Accept": "application/json",
    }
    indicator_filter = "in.(" + ",".join(f'"{name}"' for name in API_INDICATORS) + ")"
    source_filter = "in.(" + ",".join(f'"{name}"' for name in API_SOURCES) + ")"
    rows: list[dict] = []
    offset = 0
    while True:
        response = requests.get(
            endpoint,
            headers=headers,
            params={
                "select": SELECT,
                "source_api": source_filter,
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


def fetch_source_rows() -> list[dict]:
    """Privilégie PostgreSQL en lecture seule ; utilise PostgREST serveur en repli."""
    if settings.supabase_db_url:
        return _fetch_source_rows_postgres()
    return _fetch_source_rows_service_role()


def to_agro_dataframe(source_rows: list[dict]) -> pd.DataFrame:
    """Convertit les observations source en lignes contrôlables par AgroIndicatorStore."""
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict] = []
    for idx, item in enumerate(source_rows, start=1):
        region = canonical_region(str(item.get("region") or ""))
        if region not in SUPPORTED_REGIONS:
            continue
        source = str(item.get("source_api") or "").strip()
        if source not in set(API_SOURCES) or item.get("secteur") != "environment":
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
    return pd.DataFrame(rows, columns=["id", *REQUIRED_COLUMNS, "notes"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Import NASA POWER and Copernicus climate indicators into AgroIndicatorStore.")
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
                "Aucune observation ne correspond aux filtres dans public.table_public. "
                "La lecture utilise désormais un accès serveur ; vérifiez les filtres source_api, "
                "secteur et indicateur ainsi que les permissions PostgreSQL."
            )
        frame = to_agro_dataframe(source_rows)
        if frame.empty:
            examples = [
                {key: item.get(key) for key in ("region", "source_api", "secteur", "indicateur")}
                for item in source_rows[:5]
            ]
            raise RuntimeError(
                f"{len(source_rows)} observation(s) récupérée(s), mais aucune ne correspond aux "
                f"régions prises en charge. Exemples (métadonnées uniquement) : "
                f"{json.dumps(examples, ensure_ascii=False)}. Aucune écriture n'a été effectuée."
            )
        if args.apply:
            store = AgroIndicatorStore(database_url=settings.supabase_db_url)
            report = store.ingest_dataframe(frame, dry_run=False)
        else:
            # Validation pure : ne crée ni fichier SQLite local ni table de destination.
            _, report = validate_agro_dataframe(frame)
            report["dry_run"] = True
            report["written"] = 0
    except Exception as exc:
        print(f"IMPORT REFUSÉ : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report["source_rows_fetched"] = len(source_rows)
    report["nasa_power_hubs_in_scope"] = list(HUBS)
    report["copernicus_regions_in_scope"] = list(SUPPORTED_REGIONS)
    report["sources_in_scope"] = list(API_SOURCES)
    report["write_target"] = "SUPABASE_DB_URL" if args.apply else "none (dry-run)"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.apply:
        print(f"Total table_agro_indicators après import : {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
