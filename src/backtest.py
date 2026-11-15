"""Famille A (2/2) — Banc d'essai honnête des prévisions t+1 (rolling origin).

Principe : pour chaque mois d'origine `o` des N derniers mois, on ne garde que les données <= o, on prévoit
le mois o+1 puis on compare à la valeur réellement observée. Aucune information du futur n'est utilisée.

Le modèle existant (`run_forecasting_pipeline`) est évalué TEL QUEL, sans modification, face à des règles
simples : si le modèle ne les bat pas, il n'apporte rien.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from src.forecasting import run_forecasting_pipeline
from src.seasonality import SERIES_KEYS, seasonal_drift_forecast, seasonal_drift_table

METHODS = ["naive", "seasonal_naive", "ma3", "seasonal_drift", "model"]
LABELS = {
    "naive": "Naïf (prix du dernier mois)",
    "seasonal_naive": "Saisonnier naïf (même mois l'an dernier)",
    "ma3": "Moyenne mobile 3 mois",
    "seasonal_drift": "Dérive saisonnière (dernier prix × saison)",
    "model": "Modèle FreeData (actuel)",
}


def _series_lookup(kg_df: pd.DataFrame) -> dict:
    """{clé de série: pd.Series(valeur) indexée par Period mensuel}."""
    out = {}
    for key, g in kg_df.dropna(subset=["value"]).groupby(SERIES_KEYS):
        s = g.drop_duplicates("year_month", keep="last").set_index("year_month")["value"].sort_index()
        out[key] = s
    return out


def run_backtest(
    kg_df: pd.DataFrame,
    n_origins: int = 12,
    min_history: int = 12,
    model_fn: Optional[Callable] = run_forecasting_pipeline,
    seasonal_weight: float = 1.0,
) -> pd.DataFrame:
    """Retourne un tableau long : une ligne par (série, origine, méthode) avec prévision et réalité."""
    max_ym = kg_df["year_month"].max()
    origins = [max_ym - k for k in range(n_origins, 0, -1)]  # o+1 <= max_ym
    series = _series_lookup(kg_df)
    records = []

    for o in origins:
        target = o + 1
        trunc = kg_df[kg_df["year_month"] <= o]
        sd_table = seasonal_drift_table(trunc)
        model_fc = {}
        if model_fn is not None:
            _, latest = model_fn(trunc)
            for _, r in latest.iterrows():
                key = (r["source"], r["province"], r["market_name"], r["commodity_std"])
                model_fc[key] = r
        for key, s in series.items():
            if o not in s.index or target not in s.index:
                continue  # il faut un dernier prix connu à l'origine ET une réalité à comparer
            past = s[s.index <= o]
            if len(past) < min_history:
                continue
            last, actual = float(past.iloc[-1]), float(s[target])
            base = {"source": key[0], "province": key[1], "market_name": key[2], "commodity_std": key[3],
                    "origin": str(o), "target": str(target), "last": last, "actual": actual}
            tail3 = past[past.index > o - 3]
            preds = {
                "naive": last,
                "ma3": float(tail3.mean()),
                "seasonal_drift": seasonal_drift_forecast(last, target.month, sd_table, key[3], key[1], seasonal_weight),
            }
            ly = target - 12
            if ly in s.index:
                preds["seasonal_naive"] = float(s[ly])
            for method, pred in preds.items():
                records.append({**base, "method": method, "forecast": pred, "ci_low": np.nan, "ci_high": np.nan})
            if model_fn is not None:
                r = model_fc.get(key)
                if r is not None and str(r["forecast_month"]) == str(target):
                    records.append({**base, "method": "model", "forecast": float(r["forecast_t1"]),
                                    "ci_low": float(r["ci_low_80"]), "ci_high": float(r["ci_high_80"])})
                else:  # le modèle n'a pas produit de prévision pour ce mois (ex. trou dans la série)
                    records.append({**base, "method": "model_missing", "forecast": np.nan, "ci_low": np.nan,
                                    "ci_high": np.nan})
    res = pd.DataFrame(records)
    if res.empty:
        return res
    res["abs_err"] = (res["forecast"] - res["actual"]).abs()
    res["pct_err"] = res["abs_err"] / res["actual"] * 100.0
    flat = (res["last"] * 0.01)  # variations < 1 % considérées comme « stable »
    move_a = np.sign(np.where((res["actual"] - res["last"]).abs() < flat, 0, res["actual"] - res["last"]))
    move_f = np.sign(np.where((res["forecast"] - res["last"]).abs() < flat, 0, res["forecast"] - res["last"]))
    res["direction_ok"] = (move_a == move_f)
    res["in_ci"] = (res["actual"] >= res["ci_low"]) & (res["actual"] <= res["ci_high"])
    return res


def _cluster_bootstrap_diff(df_a: pd.DataFrame, df_b: pd.DataFrame, n_boot: int = 1000, seed: int = 0):
    """IC 95 % de MAE(b) − MAE(a) en rééchantillonnant des SÉRIES entières (les mois d'une série sont liés)."""
    m = df_a.merge(df_b, on=SERIES_KEYS + ["origin"], suffixes=("_a", "_b"))
    if m.empty:
        return None
    m["d"] = m["abs_err_b"] - m["abs_err_a"]
    g = m.groupby(SERIES_KEYS)["d"].agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g)))
    boots = g[idx, 0].sum(axis=1) / g[idx, 1].sum(axis=1)
    return float(m["d"].mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)), len(m)


def summarize(res: pd.DataFrame) -> dict:
    """Métriques par méthode, sur le jeu COMMUN (mêmes séries et mois) pour comparer à armes égales."""
    if res.empty:
        return {"n_points": 0, "methods": pd.DataFrame(), "by_commodity": pd.DataFrame(), "coverage_model": 0.0,
                "verdict": "Pas assez de données pour un backtest."}
    ok = res[res["method"].isin(METHODS)].dropna(subset=["forecast"])
    keys = SERIES_KEYS + ["origin"]
    wanted = [m for m in ("naive", "ma3", "seasonal_drift", "model") if m in set(ok["method"])]
    common = None
    for m in wanted:
        k = ok.loc[ok["method"] == m, keys].drop_duplicates()
        common = k if common is None else common.merge(k, on=keys)
    common_ok = ok.merge(common, on=keys) if common is not None else ok

    naive_mae = common_ok.loc[common_ok["method"] == "naive", "abs_err"].mean()
    rows = []
    for m in [x for x in METHODS if x in set(ok["method"])]:
        sub = common_ok[common_ok["method"] == m] if m != "seasonal_naive" else ok[ok["method"] == m]
        rows.append({
            "method": m, "label": LABELS[m], "n": len(sub),
            "MAE_xaf_kg": sub["abs_err"].mean(),
            "MAPE_pct": sub["pct_err"].mean(),
            "vs_naive_pct": (sub["abs_err"].mean() / naive_mae - 1.0) * 100.0 if m != "seasonal_naive" else np.nan,
            "direction_acc_pct": sub["direction_ok"].mean() * 100.0,
            "ic80_coverage_pct": sub["in_ci"].mean() * 100.0 if m == "model" else np.nan,
        })
    methods = pd.DataFrame(rows)

    pivot = (
        common_ok.groupby(["commodity_std", "method"])["abs_err"].mean().unstack("method")
        if not common_ok.empty else pd.DataFrame()
    )
    by_comm = pd.DataFrame()
    if not pivot.empty and "naive" in pivot:
        by_comm = pd.DataFrame({m: (pivot[m] / pivot["naive"] - 1.0) * 100.0 for m in pivot.columns if m != "naive"})
        by_comm["n_series_months"] = common_ok[common_ok["method"] == "naive"].groupby("commodity_std").size()

    miss = res[res["method"] == "model_missing"]
    total_model = len(miss) + len(ok[ok["method"] == "model"])
    coverage = (1.0 - len(miss) / total_model) if total_model else float("nan")

    tests = {}
    cmp_naive = common_ok[common_ok["method"] == "naive"]
    for m in ("model", "seasonal_drift", "ma3"):
        if m in wanted:
            tests[m] = _cluster_bootstrap_diff(common_ok[common_ok["method"] == m], cmp_naive)

    verdict = _verdict(methods, tests, coverage)
    return {"n_points": int(len(cmp_naive)), "methods": methods, "by_commodity": by_comm,
            "coverage_model": coverage, "tests": tests, "verdict": verdict}


def _verdict(methods: pd.DataFrame, tests: dict, coverage: float) -> str:
    lines = []
    for m in ("model", "seasonal_drift", "ma3"):
        t = tests.get(m)
        if not t:
            continue
        mean_d, lo, hi, _ = t  # MAE(naïf) − MAE(m) : > 0 => m meilleur que le naïf
        name = LABELS[m]
        if lo > 0:
            lines.append(f"✅ {name} bat le naïf de façon statistiquement claire (gain moyen {mean_d:.1f} XAF/kg, IC95 [{lo:.1f} ; {hi:.1f}]).")
        elif hi < 0:
            lines.append(f"❌ {name} est PIRE que le naïf de façon claire (perte moyenne {-mean_d:.1f} XAF/kg, IC95 [{lo:.1f} ; {hi:.1f}]).")
        else:
            lines.append(f"➖ {name} n'est pas distinguable du naïf (écart {mean_d:+.1f} XAF/kg, IC95 [{lo:.1f} ; {hi:.1f}]).")
    if coverage == coverage and coverage < 0.95:
        lines.append(f"⚠️ Le modèle actuel ne produit une prévision pour le bon mois que dans {coverage*100:.0f} % des cas "
                     f"(trous dans les séries) : le reste n'est pas évalué ici.")
    best = methods[methods["method"] != "seasonal_naive"].sort_values("MAE_xaf_kg").head(1)
    if not best.empty:
        lines.append(f"Meilleure méthode sur le jeu commun : {best.iloc[0]['label']}.")
    return "\n".join(lines)


def report_markdown(summary: dict, n_origins: int, title: str = "Backtest — Famille A (prévision t+1)") -> str:
    if summary["n_points"] == 0:
        return f"# {title}\n\nPas assez de données.\n"
    m = summary["methods"].copy()
    f = lambda x, d=1: "—" if pd.isna(x) else f"{x:.{d}f}"
    out = [f"# {title}", "",
           f"Évaluation « rolling origin » sur les **{n_origins} derniers mois**, {summary['n_points']:,} comparaisons "
           f"(série × mois) communes à tous les modèles. Chaque prévision n'utilise que le passé.".replace(",", " "), "",
           "## Verdict", "", summary["verdict"], "",
           "## Erreur de prévision t+1 (plus bas = mieux)", "",
           "| Méthode | Comparaisons | MAE (XAF/kg) | MAPE % | vs naïf | Direction juste % | Couverture IC80 % |",
           "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for _, r in m.iterrows():
        out.append(f"| {r['label']} | {int(r['n']):,} | {f(r['MAE_xaf_kg'])} | {f(r['MAPE_pct'])} | "
                   f"{'—' if pd.isna(r['vs_naive_pct']) else f'{r['vs_naive_pct']:+.1f} %'} | {f(r['direction_acc_pct'], 0)} | "
                   f"{f(r['ic80_coverage_pct'], 0)} |".replace(",", " "))
    out += ["", "*« vs naïf » : écart de MAE avec la règle « le prix reste celui du mois dernier » (négatif = meilleur). "
            "Couverture IC80 : devrait être proche de 80 %.*", ""]
    bc = summary["by_commodity"]
    if not bc.empty:
        cols = [c for c in ("ma3", "seasonal_drift", "model") if c in bc.columns]
        out += ["## Par produit — écart de MAE vs naïf (négatif = meilleur)", "",
                "| Produit | " + " | ".join(LABELS[c] for c in cols) + " | Comparaisons |",
                "| :--- | " + " | ".join("---:" for _ in cols) + " | ---: |"]
        for comm, r in bc.sort_index().iterrows():
            out.append(f"| {comm} | " + " | ".join(f"{r[c]:+.1f} %" if pd.notna(r[c]) else "—" for c in cols)
                       + f" | {int(r['n_series_months']):,} |".replace(",", " "))
    cov = summary["coverage_model"]
    if cov == cov:
        out += ["", f"**Couverture du modèle actuel :** prévision au bon mois dans {cov*100:.0f} % des cas évaluables."]
    out += ["", "## Comment lire ce rapport", "",
            "- Le naïf est la barre à franchir : un modèle qui ne le bat pas n'apporte pas de valeur prévisionnelle.",
            "- Les IC95 du verdict viennent d'un bootstrap par série (les mois d'une même série sont corrélés).",
            "- Limites : horizon t+1 uniquement ; données mensuelles ; peu d'années d'historique par série."]
    return "\n".join(out) + "\n"
