"""Contrôle complet de la famille A en UNE commande, en lecture seule (rien n'est envoyé à Supabase).

    python -m scripts.check_family_a            # données par défaut du projet (Supabase en lecture, ou CSV local)
    python -m scripts.check_family_a --csv freedatatd-markets-full.csv

Écrit dans le dossier `reports/` : backtest_family_a.md (le modèle bat-il le prix du mois dernier ?),
seasonality_studies.json (études prêtes à publier) et affiche un résumé à lire.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.backtest import report_markdown, run_backtest, summarize
from src.data_loader import load_clean_markets
from src.season_study import build_all_studies


def run(kg, out_dir: Path, n_origins: int = 12) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = run_backtest(kg, n_origins=n_origins)
    summary = summarize(res)
    (out_dir / "backtest_family_a.md").write_text(report_markdown(summary, n_origins), encoding="utf-8")
    studies = build_all_studies(kg)
    rows = [{"commodity_std": s["commodity"], "province": s.get("scope_province") or "", "payload": s} for s in studies]
    (out_dir / "seasonality_studies.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    reliable = sum(1 for s in studies if s["calendar"]["reliable"])
    return {"summary": summary, "n_studies": len(studies), "n_reliable": reliable}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--origins", type=int, default=12)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    kg = load_clean_markets(args.csv)
    r = run(kg, Path(args.out), args.origins)
    print("\n=== VERDICT DU BACKTEST ===")
    print(r["summary"]["verdict"])
    print(f"\n=== ÉTUDES SAISONNIÈRES ===\n{r['n_studies']} études, dont {r['n_reliable']} à saisonnalité fiable.")
    print(f"\nFichiers écrits dans {args.out}/ (rien envoyé à Supabase).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
