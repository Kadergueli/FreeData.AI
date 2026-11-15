"""Contrôle complet de la famille A en UNE commande, en lecture seule (rien n'est envoyé à Supabase).

    python -m scripts.check_family_a            # données par défaut du projet (Supabase en lecture, ou CSV local)
    python -m scripts.check_family_a --csv freedatatd-markets-full.csv

Écrit dans le dossier `reports/` : backtest_family_a.md (le modèle bat-il le prix du mois dernier ?),
seasonality_studies.json (études prêtes à publier) et affiche un résumé à lire.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.backtest import report_markdown, run_backtest, summarize
from src.data_loader import load_clean_markets
from src.season_study import build_all_studies


def _say(msg: str) -> None:
    print(msg, flush=True)


def run(kg, out_dir: Path, n_origins: int = 12, verbose: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if verbose:
        _say(f"[1/3] Backtest sur {n_origins} mois (le modèle est relancé à chaque mois : quelques minutes possibles)...")
    res = run_backtest(kg, n_origins=n_origins)
    summary = summarize(res)
    (out_dir / "backtest_family_a.md").write_text(report_markdown(summary, n_origins), encoding="utf-8")
    if verbose:
        _say(f"      terminé en {time.time() - t0:.0f} s -> {out_dir / 'backtest_family_a.md'}")
        _say("[2/3] Études saisonnières (tous produits et provinces)...")
    t1 = time.time()
    studies = build_all_studies(kg)
    rows = [{"commodity_std": s["commodity"], "province": s.get("scope_province") or "", "payload": s} for s in studies]
    (out_dir / "seasonality_studies.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    if verbose:
        _say(f"      terminé en {time.time() - t1:.0f} s -> {out_dir / 'seasonality_studies.json'}")
    reliable = sum(1 for s in studies if s["calendar"]["reliable"])
    return {"summary": summary, "n_studies": len(studies), "n_reliable": reliable}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--origins", type=int, default=12)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    _say("[0/3] Chargement des données...")
    kg = load_clean_markets(args.csv)
    if kg is None or len(kg) == 0:
        raise SystemExit("Aucune donnée chargée : indique --csv chemin_du_fichier.csv ou configure Supabase (.env).")
    _say(f"      {len(kg):,} relevés, {kg['commodity_std'].nunique()} produits, {kg['province'].nunique()} provinces.".replace(",", " "))
    r = run(kg, Path(args.out), args.origins, verbose=True)
    _say("[3/3] Terminé.")
    print("\n=== VERDICT DU BACKTEST ===")
    print(r["summary"]["verdict"])
    print(f"\n=== ÉTUDES SAISONNIÈRES ===\n{r['n_studies']} études, dont {r['n_reliable']} à saisonnalité fiable.")
    print(f"\nFichiers écrits dans {args.out}/ (rien envoyé à Supabase).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
