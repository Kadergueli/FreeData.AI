"""Ingestion contrôlée de freedatatd-agriculture-commercial-clean.csv dans table_agro_indicators.

Usage :
    python scripts/ingest_agro_indicators.py --csv chemin/vers/freedatatd-agriculture-commercial-clean.csv --dry-run
    python scripts/ingest_agro_indicators.py --csv chemin/vers/freedatatd-agriculture-commercial-clean.csv

Sans SUPABASE_DB_URL, l'ingestion écrit dans une base SQLite locale (data/freedata_agro.db) : pour la production,
exporter SUPABASE_DB_URL (base PostgreSQL de Render/Supabase) avant de lancer la commande sans --dry-run.
Le fichier est refusé en entier si une ligne est non conforme (source/licence interdite, région inconnue, valeur nulle…).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agro_indicators import AgroIndicatorStore, AgroIngestError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestion des indicateurs agricoles (NASA POWER Agro + World Bank).")
    parser.add_argument("--csv", required=True, help="Chemin du CSV propre commercial.")
    parser.add_argument("--dry-run", action="store_true", help="Valide le fichier sans rien écrire.")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"Fichier introuvable : {csv_path}", file=sys.stderr)
        return 2
    try:
        store = AgroIndicatorStore()
        report = store.ingest_csv(str(csv_path), dry_run=args.dry_run)
    except AgroIngestError as exc:
        print("INGESTION REFUSÉE — corrigez le fichier :", file=sys.stderr)
        for problem in exc.problems[:50]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not args.dry_run:
        print(f"Lignes présentes en base après ingestion : {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

