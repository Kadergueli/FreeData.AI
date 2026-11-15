"""Backtest rolling-origin de la famille A.

    python -m scripts.run_backtest --csv chemin.csv --origins 12 --out docs/backtest_family_a.md

Lecture seule : ne touche ni à Supabase ni aux tables Gold ; n'écrit que le rapport Markdown.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.backtest import report_markdown, run_backtest, summarize
from src.data_loader import load_clean_markets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None, help="CSV des données (sinon source par défaut du projet)")
    ap.add_argument("--origins", type=int, default=12, help="nombre de mois d'origine évalués (défaut 12)")
    ap.add_argument("--out", default="docs/backtest_family_a.md")
    args = ap.parse_args(argv)

    df = load_clean_markets(args.csv)
    kg = df.rename(columns={"price_value": "value"}) if "value" not in df.columns else df
    if "year_month" not in kg.columns:
        kg = kg.assign(year_month=kg["month_date"].dt.to_period("M"))
    res = run_backtest(kg, n_origins=args.origins)
    summary = summarize(res)
    md = report_markdown(summary, args.origins)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(summary["verdict"])
    print(f"Rapport écrit : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
