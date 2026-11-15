"""Traitement mensuel des études saisonnières (famille A, offre premium).

    python -m scripts.update_seasonality                  # calcule et écrit un JSON local (rien n'est envoyé)
    python -m scripts.update_seasonality --apply          # envoie dans table_ml_seasonality_studies (sql/05 appliqué)

N'écrit QUE dans table_ml_seasonality_studies ; ne touche pas aux tables de prévisions ni au Credit Passport.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

from src.config import settings
from src.data_loader import load_clean_markets
from src.backtest import run_backtest, track_record_by_commodity
from src.season_study import build_all_studies

TABLE = "table_ml_seasonality_studies"


def to_rows(studies: list[dict], track_records: list[dict] | None = None) -> list[dict]:
    rows = []
    for t in track_records or []:
        rows.append({"kind": "track_record", "commodity_std": t["commodity"], "province": "", "payload": t})
    for s in studies:
        rows.append({
            "kind": "seasonality",
            "commodity_std": s["commodity"],
            "province": s.get("scope_province") or "",
            "payload": s,
        })
    return rows


def push(rows: list[dict]) -> None:
    key = settings.write_key
    endpoint = f"{settings.supabase_url.rstrip('/')}/rest/v1/{TABLE}?on_conflict=kind,commodity_std,province"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates"}
    for i in range(0, len(rows), 100):
        resp = requests.post(endpoint, headers=headers, json=rows[i:i + 100], timeout=60)
        resp.raise_for_status()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--apply", action="store_true", help="envoie les études vers Supabase (sinon JSON local)")
    ap.add_argument("--out", default="seasonality_studies.json")
    args = ap.parse_args(argv)

    kg = load_clean_markets(args.csv)
    studies = build_all_studies(kg)
    n_origins = 12
    track = track_record_by_commodity(run_backtest(kg, n_origins=n_origins), n_origins)
    rows = to_rows(studies, track)
    print(f"{len(studies)} études saisonnières et {len(track)} bilans de fiabilité par produit.")
    if args.apply:
        if settings.data_backend != "supabase_rest":
            raise SystemExit("--apply exige DATA_BACKEND=supabase_rest.")
        push(rows)
        print(f"Écrit dans {TABLE}.")
    else:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"Mode lecture seule : {args.out} écrit, rien envoyé (ajouter --apply pour publier).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
