"""Charge les indicateurs agro dans public.table_agro_indicators (Gold).

  python -m scripts.load_agro_indicators --nasa-csv chemin.csv [--worldbank-csv wb.csv] [--apply]

Sans --apply : validation seule (aucune écriture). Le CSV NASA est le format large « region, reference_date,
par_w_m2, root_zone_wetness, surface_wetness ». Le CSV Banque mondiale est long : indicator, year, value, unit.
Appliquer d'abord sql/16_gold_agro_indicators.sql.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from src.agro.indicators import CONFLICT_COLS, nasa_wide_to_rows, validate_rows, worldbank_long_to_rows


def build_rows(nasa_csv: str | None, wb_csv: str | None) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    warnings: list[str] = []
    if nasa_csv:
        r, w = nasa_wide_to_rows(pd.read_csv(nasa_csv))
        rows += r
        warnings += w
    if wb_csv:
        rows += worldbank_long_to_rows(pd.read_csv(wb_csv))
    errors = validate_rows(rows)
    if errors:
        raise ValueError(f"{len(errors)} erreur(s), première(s) : {errors[:5]}")
    return rows, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nasa-csv")
    ap.add_argument("--worldbank-csv")
    ap.add_argument("--apply", action="store_true", help="écrit dans Supabase (sinon validation seule)")
    args = ap.parse_args(argv)
    if not (args.nasa_csv or args.worldbank_csv):
        ap.error("fournir --nasa-csv et/ou --worldbank-csv")
    rows, warnings = build_rows(args.nasa_csv, args.worldbank_csv)
    for w in warnings:
        print("AVERTISSEMENT:", w)
    by = pd.Series([r["indicator"] for r in rows]).value_counts().to_dict()
    print(f"{len(rows)} lignes conformes : {by}")
    if not args.apply:
        print("Validation seule (ajouter --apply pour écrire).")
        return 0
    from scripts.update_predictions import _upsert_supabase_rest
    from src.config import settings
    if settings.data_backend != "supabase_rest" or not settings.supabase_service_key:
        print("SUPABASE_URL et SUPABASE_SERVICE_KEY requis pour --apply.", file=sys.stderr)
        return 2
    _upsert_supabase_rest("table_agro_indicators", rows, CONFLICT_COLS)
    print("Table table_agro_indicators mise à jour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
