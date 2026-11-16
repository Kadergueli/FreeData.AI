"""Détection mensuelle des anomalies de prix (famille B).

    python -m scripts.update_anomalies                  # calcule et écrit un JSON local (rien n'est envoyé)
    python -m scripts.update_anomalies --apply          # envoie dans table_ml_anomalies (sql/07 appliqué)

N'écrit QUE dans table_ml_anomalies. Seuls les `--months` derniers mois sont publiés (6 par défaut).
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.anomalies import detect_anomalies, recent_anomalies
from src.config import settings
from src.data_loader import load_clean_markets

TABLE = "table_ml_anomalies"
FIELDS = ["source", "province", "market_name", "commodity_std", "kind", "severity", "month", "value", "reference",
          "change_pct", "score"]


def to_rows(anom) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for rec in anom[FIELDS].to_dict("records"):
        row = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rec.items()}
        row["generated_at"] = now
        rows.append(row)
    return rows


def push(rows: list[dict]) -> None:
    key = settings.write_key
    endpoint = (f"{settings.supabase_url.rstrip('/')}/rest/v1/{TABLE}"
                "?on_conflict=source,province,market_name,commodity_std,month,kind")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates"}
    for i in range(0, len(rows), 200):
        requests.post(endpoint, headers=headers, json=rows[i:i + 200], timeout=60).raise_for_status()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--apply", action="store_true", help="envoie vers Supabase (sinon JSON local)")
    ap.add_argument("--out", default="anomalies.json")
    args = ap.parse_args(argv)

    kg = load_clean_markets(args.csv)
    anom = recent_anomalies(detect_anomalies(kg), months=args.months)
    rows = to_rows(anom)
    print(f"{len(rows)} anomalies sur les {args.months} derniers mois "
          f"({anom['kind'].value_counts().to_dict() if len(anom) else {}}).")
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
