"""Contrôle de la famille B en UNE commande, en lecture seule (rien n'est envoyé à Supabase).

    python -m scripts.check_family_b --csv freedatatd-markets-full.csv

Affiche les anomalies récentes, le taux d'alertes sur tes données et la capacité de détection mesurée par
chocs injectés (le détecteur retrouve-t-il un faux saut de +15 %, +25 %, +40 % glissé dans tes données ?).
Écrit reports/anomalies_family_b.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.anomalies import detect_anomalies, evaluate_detection, recent_anomalies
from src.data_loader import load_clean_markets


def report(anom, ev) -> str:
    rec = recent_anomalies(anom, 3)
    lines = ["# Famille B — Détection d'anomalies", "",
             f"- Anomalies sur tout l'historique : **{len(anom)}** ({anom['kind'].value_counts().to_dict() if len(anom) else {}})",
             f"- Anomalies des 3 derniers mois : **{len(rec)}**",
             f"- Taux d'alertes (sauts/divergences) sur les 12 derniers mois : **{ev['alert_rate_pct']:.2f} %** des relevés "
             "(borne haute des fausses alertes : tes données contiennent de vraies anomalies)", "",
             "## Détection de chocs injectés", "", "| Amplitude du choc | Injectés | Détectés | Taux |", "| :--- | ---: | ---: | ---: |"]
    for mag, d in ev["detection"].items():
        lines.append(f"| ±{mag * 100:.0f} % | {d['injected']} | {d['detected']} | {d['rate'] * 100:.0f} % |")
    lines += ["", "## Dernières anomalies fortes", ""]
    top = rec[rec["severity"] == "forte"].head(15)
    for r in top.itertuples():
        lines.append(f"- {r.month} — {r.commodity_std} ({r.province}, {r.market_name}) : {r.kind}, {r.change_pct:+.0f} %")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    print("[0/2] Chargement des données...", flush=True)
    kg = load_clean_markets(args.csv)
    if kg is None or len(kg) == 0:
        raise SystemExit("Aucune donnée chargée : indique --csv chemin_du_fichier.csv ou configure Supabase (.env).")
    print(f"      {len(kg):,} relevés.".replace(",", " "), flush=True)
    print("[1/2] Détection et validation par chocs injectés (quelques dizaines de secondes)...", flush=True)
    anom = detect_anomalies(kg)
    ev = evaluate_detection(kg)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "anomalies_family_b.md").write_text(report(anom, ev), encoding="utf-8")
    print("[2/2] Terminé.\n")
    print(report(anom, ev))
    print(f"Fichier écrit : {out / 'anomalies_family_b.md'} (rien envoyé à Supabase).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
