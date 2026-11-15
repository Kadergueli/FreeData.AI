"""Famille A (3/3) — Étude saisonnière avancée (offre premium).

Produit un dossier structuré pour un produit (et une province) :
- calendrier d'achat / vente et indice mensuel ;
- comparaison des provinces (où le creux est le plus bas, où le pic est le plus haut) ;
- backtest de la stratégie « acheter au creux, vendre au pic » sur les années passées, avec les mois choisis
  SANS regarder l'année évaluée (leave-years-out) : le taux de réussite n'est donc pas gonflé par l'avenir.

Aucun coût de stockage n'est supposé : s'il est fourni par l'utilisateur, le rendement net est calculé en plus.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.seasonality import MONTHS_FR, SERIES_KEYS, deviation_table, seasonal_calendar

MIN_CYCLES = 8  # en dessous, aucun taux de réussite n'est annoncé
MIN_YEARS = 3   # cycles couvrant moins de 3 années : un seul exercice ne prouve rien (hasard de la saison)


def _monthly_province_prices(kg: pd.DataFrame, commodity: str, province: Optional[str]) -> pd.DataFrame:
    sub = kg[(kg["commodity_std"] == commodity) & kg["value"].notna() & (kg["value"] > 0)]
    if province:
        sub = sub[sub["province"] == province]
    return sub.groupby(["province", "year_month"], as_index=False)["value"].mean()


def summarize_cycles(cycles: list, storage_cost_pct_month: Optional[float] = None) -> dict:
    """Résume des cycles [rendement %, durée (mois), mois d'achat, mois de vente, année]. Recalculable avec un coût de stockage."""
    if len(cycles) < MIN_CYCLES:
        return {"status": "insufficient_data", "n_cycles": len(cycles), "cycles": cycles}
    df = pd.DataFrame(cycles, columns=["ret", "gap", "buy", "sell", "year"])
    if df["year"].nunique() < MIN_YEARS:
        return {"status": "insufficient_data", "n_cycles": len(cycles), "n_years": int(df["year"].nunique()), "cycles": cycles}
    out = {
        "status": "ok",
        "n_cycles": int(len(df)),
        "n_years": int(df["year"].nunique()),
        "hit_rate_pct": float((df["ret"] > 0).mean() * 100.0),
        "median_return_pct": float(df["ret"].median()),
        "p10_return_pct": float(df["ret"].quantile(0.10)),
        "p90_return_pct": float(df["ret"].quantile(0.90)),
        "typical_buy_month": int(df["buy"].mode().iloc[0]),
        "typical_sell_month": int(df["sell"].mode().iloc[0]),
        "typical_gap_months": int(df["gap"].mode().iloc[0]),
        "in_sample": False,
        "cycles": cycles,
    }
    if storage_cost_pct_month is not None:
        net = df["ret"] - df["gap"] * float(storage_cost_pct_month)
        out.update({
            "storage_cost_pct_month": float(storage_cost_pct_month),
            "net_hit_rate_pct": float((net > 0).mean() * 100.0),
            "net_median_return_pct": float(net.median()),
        })
    return out


def storage_backtest(kg_df: pd.DataFrame, commodity: str, province: Optional[str] = None,
                     storage_cost_pct_month: Optional[float] = None, dev: Optional[pd.DataFrame] = None) -> dict:
    """Rejoue, année par année, « acheter au mois le moins cher, revendre au mois le plus cher qui suit »."""
    prices = _monthly_province_prices(kg_df, commodity, province)
    if prices.empty:
        return {"status": "insufficient_data", "n_cycles": 0, "cycles": []}
    years = sorted(prices["year_month"].dt.year.unique())
    lookup = prices.set_index(["province", "year_month"])["value"]
    if dev is None:
        dev = deviation_table(kg_df[kg_df["commodity_std"] == commodity])
    dev_c = dev[dev["commodity_std"] == commodity]
    cycles = []
    for y in years:
        # Le calendrier est appris sans l'année y ni y+1 (l'année de vente), ni les 6 mois voisins dont la tendance
        # (moyenne centrée sur 12 mois) les aurait touchés : aucune fuite d'information.
        lo, hi = int(y) * 12 + 1 - 6, (int(y) + 1) * 12 + 12 + 6
        cal = seasonal_calendar(None, commodity, province, dev=dev_c[~dev_c["ordinal"].between(lo, hi)])
        if cal.get("status") != "ok":
            continue
        bm, sm = cal["buy_months"][0], cal["sell_months"][0]
        gap = (sm - bm) % 12
        if gap == 0:
            continue
        buy_p = pd.Period(year=int(y), month=bm, freq="M")
        sell_p = buy_p + gap
        for prov in prices["province"].unique():
            pb, ps = lookup.get((prov, buy_p)), lookup.get((prov, sell_p))
            if pb is None or ps is None or pb <= 0:
                continue
            cycles.append([round(float(ps / pb - 1.0) * 100.0, 2), int(gap), int(bm), int(sm), int(y)])
    return summarize_cycles(cycles, storage_cost_pct_month)


def with_storage_cost(study: dict, storage_cost_pct_month: Optional[float]) -> dict:
    """Copie de l'étude dont la stratégie de stockage tient compte d'un coût mensuel (calculé à partir des cycles stockés)."""
    st = study.get("storage_strategy") or {}
    cycles = st.get("cycles")
    if study.get("status") != "ok" or cycles is None:
        return study
    return {**study, "storage_strategy": summarize_cycles(cycles, storage_cost_pct_month)}


class StudyBook:
    """Accès aux études saisonnières : précalculées (tables Gold) ou calculées à la demande depuis l'historique complet."""

    def __init__(self, studies: Optional[list] = None, kg_df: Optional[pd.DataFrame] = None):
        self._stored = {(s["commodity"], s.get("scope_province")): s for s in (studies or []) if s.get("status") == "ok"}
        self._kg = kg_df
        self._cache: dict = {}
        self._dev: Optional[pd.DataFrame] = None

    @property
    def has_data(self) -> bool:
        return bool(self._stored) or (self._kg is not None and not self._kg.empty)

    def get(self, commodity: str, province: Optional[str] = None, light: bool = False) -> Optional[dict]:
        """Étude de la province demandée, sinon nationale ; None si aucune n'est exploitable.

        `light=True` : calendrier seul (sans rejouer la stratégie de stockage) pour les réponses du chat.
        """
        for prov in ((province, None) if province else (None,)):
            if (commodity, prov) in self._stored:
                return self._stored[(commodity, prov)]
            if self._kg is not None:
                key = (commodity, prov, light)
                if key not in self._cache:
                    if len(self._cache) > 200:
                        self._cache.clear()
                    if self._dev is None:
                        self._dev = deviation_table(self._kg)
                    self._cache[key] = build_seasonal_study(self._kg, commodity, prov, with_strategy=not light,
                                                            comparison=not light, dev=self._dev)
                if self._cache[key].get("status") == "ok" and self._cache[key].get("scope_province") == prov:
                    return self._cache[key]
        return None


def province_comparison(kg_df: pd.DataFrame, commodity: str, min_points: int = 30, top: int = 8,
                        dev: Optional[pd.DataFrame] = None) -> list[dict]:
    rows = []
    for prov in sorted(kg_df.loc[kg_df["commodity_std"] == commodity, "province"].dropna().unique()):
        cal = seasonal_calendar(kg_df, commodity, prov, min_points=min_points, dev=dev)
        if cal.get("status") != "ok":
            continue
        rows.append({
            "province": prov,
            "buy_months": cal["buy_months"], "sell_months": cal["sell_months"],
            "buy_discount_pct": cal["buy_discount_pct"], "sell_premium_pct": cal["sell_premium_pct"],
            "amplitude_pct": cal["amplitude_pct"], "reliable": cal["reliable"],
        })
    rows.sort(key=lambda r: (not r["reliable"], -r["amplitude_pct"]))
    return rows[:top]


def build_seasonal_study(kg_df: pd.DataFrame, commodity: str, province: Optional[str] = None,
                         storage_cost_pct_month: Optional[float] = None, with_strategy: bool = True,
                         comparison: bool = True, dev: Optional[pd.DataFrame] = None) -> dict:
    if dev is None:
        dev = deviation_table(kg_df[kg_df["commodity_std"] == commodity])
    cal = seasonal_calendar(kg_df, commodity, province, dev=dev)
    scope = province
    if cal.get("status") != "ok" and province:
        cal, scope = seasonal_calendar(kg_df, commodity, None, dev=dev), None
    if cal.get("status") != "ok":
        return {"status": "insufficient_data", "commodity": commodity, "province": province}
    profile = cal.pop("profile")
    return {
        "status": "ok",
        "commodity": commodity,
        "requested_province": province,
        "scope_province": scope,
        "calendar": {k: v for k, v in cal.items() if k not in ("status", "commodity", "province")},
        "profile": [
            {"month": int(r.month), "label": MONTHS_FR[int(r.month) - 1], "index": round(float(r["index"]), 3),
             "pct_vs_avg": round(float(r.pct_vs_avg), 1), "consistency": round(float(r.consistency), 2), "n": int(r.n)}
            for _, r in profile.dropna(subset=["index"]).iterrows()
        ],
        "provinces": province_comparison(kg_df, commodity, dev=dev) if (comparison and not province) else [],
        "storage_strategy": (storage_backtest(kg_df, commodity, scope, storage_cost_pct_month, dev=dev)
                             if with_strategy else {"status": "not_computed", "n_cycles": 0}),
        "caveats": [
            "Moyennes historiques : elles décrivent le passé, pas une garantie pour la prochaine saison.",
            *(["Historique court : chaque mois n'a été observé que sur "
               f"{cal.get('min_years_observed', 0)} année(s) ; le calendrier repose sur très peu de cycles."]
              if cal.get("min_years_observed", 0) < 3 else []),
            "Les mois d'achat/vente de la stratégie sont choisis sans regarder l'année évaluée.",
            "Hors coûts de transport, pertes, financement ; le coût de stockage n'est pris en compte que s'il est fourni.",
        ],
    }


def study_markdown(study: dict) -> str:
    if study.get("status") != "ok":
        return (f"# Étude saisonnière — {study.get('commodity')}\n\nHistorique insuffisant pour une étude fiable.\n")
    c, m = study["calendar"], lambda xs: " et ".join(MONTHS_FR[i - 1] for i in sorted(xs))
    where = study["scope_province"] or "toutes provinces suivies"
    out = [f"# Étude saisonnière — {study['commodity']} ({where})", "",
           f"- Achat favorable : **{m(c['buy_months'])}** ({c['buy_discount_pct']:+.0f} % vs moyenne annuelle)",
           f"- Vente favorable : **{m(c['sell_months'])}** ({c['sell_premium_pct']:+.0f} %)",
           f"- Amplitude creux‑pic : {c['amplitude_pct']:.0f} % · fiabilité : {'élevée' if c['reliable'] else 'faible'}", "",
           "## Indice mensuel (1,00 = moyenne annuelle)", "", "| Mois | Indice | Écart | Régularité |", "| :-- | --: | --: | --: |"]
    out += [f"| {r['label']} | {r['index']:.2f} | {r['pct_vs_avg']:+.1f} % | {r['consistency']*100:.0f} % |" for r in study["profile"]]
    st = study["storage_strategy"]
    out += ["", "## Stratégie « acheter au creux, vendre au pic » (rejouée sur le passé)", ""]
    if st["status"] == "not_computed":
        out.append("Non calculée pour cette étude.")
    elif st["status"] != "ok":
        ny = st.get("n_years")
        out.append(f"Pas assez d'historique pour annoncer un taux de réussite ({st['n_cycles']} cycles"
                   f"{f' sur {ny} année(s)' if ny is not None else ''} ; il faut au moins {MIN_YEARS} années).")
    else:
        out += [f"- {st['n_cycles']} cycles sur {st['n_years']} années : gain positif dans **{st['hit_rate_pct']:.0f} %** des cas",
                f"- Rendement brut médian {st['median_return_pct']:+.0f} % (10 % des pires cas : {st['p10_return_pct']:+.0f} %, "
                f"10 % des meilleurs : {st['p90_return_pct']:+.0f} %) sur ~{st['typical_gap_months']} mois"]
        if "net_hit_rate_pct" in st:
            out.append(f"- Avec {st['storage_cost_pct_month']:.1f} %/mois de coûts de stockage : gain net positif dans "
                       f"{st['net_hit_rate_pct']:.0f} % des cas, médiane {st['net_median_return_pct']:+.0f} %")
    if study["provinces"]:
        out += ["", "## Provinces comparées", "", "| Province | Achat | Vente | Amplitude | Fiable |", "| :-- | :-- | :-- | --: | :-: |"]
        out += [f"| {p['province']} | {m(p['buy_months'])} | {m(p['sell_months'])} | {p['amplitude_pct']:.0f} % | "
                f"{'oui' if p['reliable'] else 'non'} |" for p in study["provinces"]]
    out += ["", "## Limites", ""] + [f"- {x}" for x in study["caveats"]]
    return "\n".join(out) + "\n"


def build_all_studies(kg_df: pd.DataFrame, min_province_points: int = 30) -> list[dict]:
    """Toutes les études exploitables : une nationale par produit + une par (produit, province) suffisamment fournie.

    Sert au traitement mensuel hors ligne (scripts/update_seasonality.py) : l'API n'a alors plus qu'à lire.
    """
    out = []
    dev_all = deviation_table(kg_df)  # un seul calcul pour toutes les études
    for comm in sorted(kg_df["commodity_std"].dropna().unique()):
        dev = dev_all[dev_all["commodity_std"] == comm]
        nat = build_seasonal_study(kg_df, comm, dev=dev)
        if nat.get("status") == "ok":
            out.append(nat)
        for prov in sorted(kg_df.loc[kg_df["commodity_std"] == comm, "province"].dropna().unique()):
            st = build_seasonal_study(kg_df, comm, prov, comparison=False, dev=dev)
            if st.get("status") == "ok" and st["scope_province"] == prov:
                out.append(st)
    return out
