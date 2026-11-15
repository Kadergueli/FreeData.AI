"""Famille A (1/2) — Saisonnalité des prix : profils, calendrier d'achat/déstockage et dérive saisonnière.

Aucun entraînement lourd : des moyennes par mois calendaire, rétrécies vers le niveau produit quand les
données locales sont rares. Tout est calculé uniquement à partir des relevés fournis, ce qui permet au
backtest de n'utiliser que le passé (aucune fuite d'information).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

SERIES_KEYS = ["source", "province", "market_name", "commodity_std"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]


def _with_ordinal(kg_df: pd.DataFrame) -> pd.DataFrame:
    df = kg_df[SERIES_KEYS + ["year_month", "value"]].dropna(subset=["value"]).copy()
    df = df[df["value"] > 0]
    df["ordinal"] = df["year_month"].dt.year * 12 + df["year_month"].dt.month
    df["month"] = df["year_month"].dt.month
    return df.sort_values(SERIES_KEYS + ["ordinal"])


# ----------------------------------------------------------------------------
# 1. Dérive saisonnière (candidat de prévision t+1)
# ----------------------------------------------------------------------------
def seasonal_drift_table(kg_df: pd.DataFrame, shrink_k: float = 6.0) -> dict:
    """Rendement logarithmique moyen « mois précédent -> mois m », par (produit, province, m).

    Le niveau local est rétréci vers la moyenne du produit (poids `shrink_k` observations fictives) :
    une province avec 3 observations ne doit pas dicter sa saisonnalité.
    Retour : {"local": {(commodity, province): array(12)}, "commodity": {commodity: array(12)}, "global": array(12)}
    """
    df = _with_ordinal(kg_df)
    grp = df.groupby(SERIES_KEYS)
    df["prev_ord"] = grp["ordinal"].shift(1)
    df["prev_val"] = grp["value"].shift(1)
    df = df[(df["ordinal"] - df["prev_ord"]) == 1].copy()  # seulement des mois consécutifs
    if df.empty:
        return {"local": {}, "commodity": {}, "global": np.zeros(12)}
    df["lr"] = np.log(df["value"] / df["prev_val"])
    df["lr"] = df["lr"].clip(-0.7, 0.7)  # un relevé aberrant ne doit pas dominer un mois

    def _mean12(sub: pd.DataFrame):
        s = sub.groupby("month")["lr"].agg(["sum", "count"]).reindex(range(1, 13), fill_value=0)
        return s["sum"].to_numpy(float), s["count"].to_numpy(float)

    g_sum, g_n = _mean12(df)
    g_mean = np.divide(g_sum, np.maximum(g_n, 1))
    comm_tab, local_tab = {}, {}
    for comm, sub in df.groupby("commodity_std"):
        s, n = _mean12(sub)
        comm_tab[comm] = (s + shrink_k * g_mean) / (n + shrink_k)
    for (comm, prov), sub in df.groupby(["commodity_std", "province"]):
        s, n = _mean12(sub)
        base = comm_tab[comm]
        local_tab[(comm, prov)] = (s + shrink_k * base) / (n + shrink_k)
    return {"local": local_tab, "commodity": comm_tab, "global": g_mean}


def seasonal_drift_forecast(last_value: float, target_month: int, table: dict, commodity: str, province: str,
                            weight: float = 1.0) -> float:
    """Prix(t+1) = dernier prix × exp(weight × dérive saisonnière du mois cible)."""
    arr = table["local"].get((commodity, province))
    if arr is None:
        arr = table["commodity"].get(commodity, table["global"])
    return float(last_value * np.exp(weight * arr[target_month - 1]))


# ----------------------------------------------------------------------------
# 2. Profil saisonnier & calendrier d'achat / déstockage
# ----------------------------------------------------------------------------
def deviation_table(kg_df: pd.DataFrame, min_obs: int = 24) -> pd.DataFrame:
    """Écart de chaque relevé à sa tendance (log prix moins moyenne mobile centrée sur 12 mois), pour toutes les séries.

    Calculé UNE fois puis réutilisé : tout le reste (profils, calendriers, backtests) n'est qu'un regroupement de ce tableau.
    Colonnes : source, province, market_name, commodity_std, ordinal (année*12+mois), month, year, dev.
    """
    df = _with_ordinal(kg_df)
    out = []
    for key, g in df.groupby(SERIES_KEYS, sort=False):
        g = g.drop_duplicates("ordinal", keep="last")
        if len(g) < min_obs:
            continue
        o = g["ordinal"].to_numpy()
        full = np.full(int(o[-1] - o[0]) + 1, np.nan)
        full[o - o[0]] = np.log(g["value"].to_numpy(float))
        ser = pd.Series(full)
        dev = (ser - ser.rolling(12, center=True, min_periods=10).mean()).to_numpy()
        ords = np.arange(o[0], o[-1] + 1)
        ok = ~np.isnan(dev)
        n = int(ok.sum())
        out.append(pd.DataFrame({
            "source": key[0], "province": key[1], "market_name": key[2], "commodity_std": key[3],
            "ordinal": ords[ok], "month": (ords[ok] - 1) % 12 + 1, "year": (ords[ok] - 1) // 12, "dev": dev[ok],
        }, index=range(n)))
    cols = SERIES_KEYS + ["ordinal", "month", "year", "dev"]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=cols)


def seasonal_profile(kg_df: Optional[pd.DataFrame], commodity: str, province: Optional[str] = None,
                     dev: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Indice saisonnier par mois calendaire (1.00 = prix moyen de l'année).

    Méthode : écart à la tendance (voir `deviation_table`), moyenné par mois sur toutes les séries et années.
    `consistency` = part des (série, année) où l'écart a le même signe que l'indice : 0,5 = bruit, 1,0 = toujours identique.
    `dev` : tableau d'écarts déjà calculé (évite de tout recalculer).
    """
    if dev is None:
        sub = kg_df[kg_df["commodity_std"] == commodity]
        if province:
            sub = sub[sub["province"] == province]
        dev = deviation_table(sub)
    d = dev[dev["commodity_std"] == commodity]
    if province:
        d = d[d["province"] == province]
    out = pd.DataFrame({"month": range(1, 13)})
    if d.empty:
        return out.assign(index=np.nan, pct_vs_avg=np.nan, consistency=np.nan, n=0, n_years=0)
    agg = d.groupby("month")["dev"].agg(["mean", "count"]).reindex(range(1, 13))
    same = np.sign(d["dev"].to_numpy()) == np.sign(d["month"].map(agg["mean"]).to_numpy())
    cons = pd.Series(same, index=d.index).groupby(d["month"]).mean().reindex(range(1, 13))
    mean = agg["mean"].to_numpy(float)
    mean = mean - np.nanmean(mean)  # centré : un indice moyen de 1.00
    out["index"] = np.exp(mean)
    out["pct_vs_avg"] = (out["index"] - 1.0) * 100.0
    out["consistency"] = cons.to_numpy(float)
    out["n"] = agg["count"].fillna(0).astype(int).to_numpy()
    # Nombre d'années distinctes où ce mois a été observé : avec 2-3 ans d'historique, un « motif » ne repose que sur 1 ou 2 saisons.
    out["n_years"] = d.groupby("month")["year"].nunique().reindex(range(1, 13)).fillna(0).astype(int).to_numpy()
    return out


def seasonal_calendar(kg_df: Optional[pd.DataFrame], commodity: str, province: str | None = None,
                      min_amplitude_pct: float = 6.0, min_consistency: float = 0.6, min_points: int = 30,
                      dev: Optional[pd.DataFrame] = None) -> dict:
    """Résumé exploitable : mois les moins chers (achat), les plus chers (vente/déstockage) et fiabilité."""
    prof = seasonal_profile(kg_df, commodity, province, dev=dev)
    valid = prof.dropna(subset=["index"])
    if valid.empty or valid["n"].min() < min_points // 4:
        return {"status": "insufficient_data", "commodity": commodity, "province": province, "profile": prof}
    order = valid.sort_values("index")
    buy, sell = order.head(2), order.tail(2).iloc[::-1]
    amplitude = (valid["index"].max() / valid["index"].min() - 1.0) * 100.0
    extremes = pd.concat([buy, sell])
    consistent = float(extremes["consistency"].mean())
    min_years = int(valid["n_years"].min())
    # Fiable seulement si chaque mois a été vu sur au moins 3 années différentes : avec 2 saisons, on ne peut pas distinguer une saisonnalité d'un hasard.
    reliable = bool(amplitude >= min_amplitude_pct and consistent >= min_consistency
                    and valid["n"].sum() >= min_points and min_years >= 3)
    return {
        "status": "ok",
        "commodity": commodity,
        "province": province,
        "profile": prof,
        "buy_months": [int(m) for m in buy["month"]],
        "sell_months": [int(m) for m in sell["month"]],
        "buy_discount_pct": float(buy["pct_vs_avg"].mean()),
        "sell_premium_pct": float(sell["pct_vs_avg"].mean()),
        "amplitude_pct": float(amplitude),
        "consistency": consistent,
        "reliable": reliable,
        "min_years_observed": min_years,
        "n_points": int(valid["n"].sum()),
    }
