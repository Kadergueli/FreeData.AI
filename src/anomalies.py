"""Famille B — Détection d'anomalies de prix (calcul hors ligne, fonctions pures).

Trois familles de signaux, toutes calculées uniquement avec le PASSÉ de chaque série (aucune fuite) :

1. **jump** — saut mensuel atypique : variation log du mois comparée à l'historique de la série
   (médiane et MAD, donc peu sensibles aux valeurs extrêmes passées).
2. **divergence** — un marché s'écarte de ses pairs : écart log entre le prix de la série et la médiane
   du même produit le même mois (autres marchés), comparé à l'historique de cet écart.
3. **stale / stopped** — qualité des données : valeur figée plusieurs mois de suite, ou série arrêtée.

Seuils volontairement prudents : l'historique réel est court (≤ 34 mois), donc une anomalie est un
SIGNAL À VÉRIFIER, jamais un verdict. La validation se fait par chocs injectés (voir `evaluate_detection`).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.seasonality import SERIES_KEYS

MIN_HISTORY = 6          # variations passées minimum pour juger la suivante
Z_THRESHOLD = 3.5        # score robuste minimal
SCALE_FLOOR = 0.03       # échelle plancher (évite les scores énormes sur des séries très plates)
MIN_MOVE = 0.10          # variation minimale (10 %) pour parler de saut
MIN_DIVERGENCE = 0.15    # écart minimal (15 %) à la position habituelle parmi les pairs
MIN_PEERS = 4            # séries du même produit nécessaires pour définir « la médiane des pairs »
STALE_RUN = 4            # mois identiques consécutifs = série figée
STOPPED_GAP = 3          # mois sans relevé = série arrêtée
STRONG_Z = 5.0
STRONG_MOVE = 0.30

COLUMNS = SERIES_KEYS + ["kind", "severity", "month", "value", "reference", "change_pct", "score"]


def _clean(kg_df: pd.DataFrame) -> pd.DataFrame:
    df = kg_df[SERIES_KEYS + ["year_month", "value"]].dropna(subset=["value"]).copy()
    df = df[df["value"] > 0]
    df["ordinal"] = df["year_month"].dt.year * 12 + df["year_month"].dt.month
    df = df.sort_values(SERIES_KEYS + ["ordinal"]).drop_duplicates(SERIES_KEYS + ["ordinal"], keep="last")
    return df


def _robust_z(hist: np.ndarray, x: float) -> tuple[float, float]:
    """(z robuste de x par rapport à hist, centre). Échelle plancher SCALE_FLOOR."""
    center = float(np.median(hist))
    scale = max(1.4826 * float(np.median(np.abs(hist - center))), SCALE_FLOOR)
    return (x - center) / scale, center


def _severity(z: float, move: float) -> str:
    return "forte" if abs(z) >= STRONG_Z or abs(move) >= STRONG_MOVE else "modérée"


def _row(key, kind, severity, ordinal, value, reference, change_pct, score) -> dict:
    year, month0 = divmod(int(ordinal) - 1, 12)
    return dict(zip(SERIES_KEYS, key)) | {
        "kind": kind, "severity": severity, "month": f"{year:04d}-{month0 + 1:02d}",
        "value": float(value), "reference": float(reference), "change_pct": float(change_pct), "score": float(score),
    }


# ----------------------------------------------------------------------------
# 1. Sauts de prix
# ----------------------------------------------------------------------------
def jump_anomalies(kg_df: pd.DataFrame, z_threshold: float = Z_THRESHOLD, min_move: float = MIN_MOVE) -> list[dict]:
    out = []
    for key, g in _clean(kg_df).groupby(SERIES_KEYS):
        ords, vals = g["ordinal"].to_numpy(), g["value"].to_numpy(float)
        if len(vals) < MIN_HISTORY + 2:
            continue
        consecutive = np.diff(ords) == 1
        lr = np.log(vals[1:] / vals[:-1])
        hist: list[float] = []
        for i in range(len(lr)):
            if not consecutive[i]:
                continue
            if len(hist) >= MIN_HISTORY:
                z, _ = _robust_z(np.asarray(hist), lr[i])
                move = float(np.expm1(lr[i]))
                if abs(z) >= z_threshold and abs(move) >= min_move:
                    out.append(_row(key, "jump", _severity(z, move), ords[i + 1], vals[i + 1], vals[i], move * 100, z))
            hist.append(float(lr[i]))
    return out


# ----------------------------------------------------------------------------
# 2. Divergence entre marchés (mouvement propre à un marché, pas commun à tous)
# ----------------------------------------------------------------------------
def divergence_anomalies(kg_df: pd.DataFrame, z_threshold: float = Z_THRESHOLD,
                         min_divergence: float = MIN_DIVERGENCE) -> list[dict]:
    """Variation du mois d'une série moins la variation médiane des autres séries du même produit.

    Un choc commun à tous les marchés (saison, carburant) n'est pas une divergence ; un marché qui bouge seul l'est.
    """
    out = []
    df = _clean(kg_df)
    for _comm, sub in df.groupby("commodity_std"):
        piv = sub.pivot_table(index="ordinal", columns=SERIES_KEYS, values="value", aggfunc="last").sort_index()
        if piv.shape[1] < MIN_PEERS:
            continue
        full = piv.reindex(range(int(piv.index.min()), int(piv.index.max()) + 1))
        lr = np.log(full / full.shift(1))          # NaN si le mois précédent manque : mois consécutifs seulement
        n_ret = lr.notna().sum(axis=1)
        peer_med = lr.median(axis=1).where(n_ret >= MIN_PEERS)
        rel = lr.sub(peer_med, axis=0)
        for key in rel.columns:
            r = rel[key].dropna()
            if len(r) <= MIN_HISTORY:
                continue
            ords, vals = r.index.to_numpy(), r.to_numpy(float)
            for i in range(MIN_HISTORY, len(vals)):
                z, center = _robust_z(vals[:i], vals[i])
                gap = float(np.expm1(vals[i] - center))
                if abs(z) >= z_threshold and abs(gap) >= min_divergence:
                    cur = float(full.loc[ords[i], key])
                    prev = float(full.loc[ords[i] - 1, key])
                    ref = prev * float(np.exp(peer_med.loc[ords[i]]))  # prix attendu s'il avait suivi les autres marchés
                    out.append(_row(key, "divergence", _severity(z, gap), ords[i], cur, ref, gap * 100, z))
    return out


# ----------------------------------------------------------------------------
# 3. Qualité des données
# ----------------------------------------------------------------------------
def quality_issues(kg_df: pd.DataFrame) -> list[dict]:
    df = _clean(kg_df)
    if df.empty:
        return []
    end = int(df["ordinal"].max())
    out = []
    for key, g in df.groupby(SERIES_KEYS):
        ords, vals = g["ordinal"].to_numpy(), g["value"].to_numpy(float)
        gap = end - int(ords[-1])
        if gap >= STOPPED_GAP:
            out.append(_row(key, "stopped", "modérée", ords[-1], vals[-1], vals[-1], 0.0, gap))
            continue
        run = 1
        while run < len(vals) and np.isclose(vals[-1 - run], vals[-1]) and ords[-run] - ords[-1 - run] == 1:
            run += 1
        if run >= STALE_RUN:
            out.append(_row(key, "stale", "modérée", ords[-1], vals[-1], vals[-1], 0.0, run))
    return out


# ----------------------------------------------------------------------------
# Assemblage
# ----------------------------------------------------------------------------
def detect_anomalies(kg_df: pd.DataFrame) -> pd.DataFrame:
    """Toutes les anomalies de l'historique, une ligne par (série, mois, type) ; jump+divergence fusionnés."""
    rows = jump_anomalies(kg_df) + divergence_anomalies(kg_df) + quality_issues(kg_df)
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    key = SERIES_KEYS + ["month"]
    both = df[df["kind"].isin(["jump", "divergence"])]
    dup = both.duplicated(key, keep=False)
    merged = []
    for _, g in both[dup].groupby(key):
        top = g.sort_values("score", key=lambda s: s.abs(), ascending=False).iloc[0].copy()
        top["kind"] = "jump+divergence"
        top["severity"] = "forte" if (g["severity"] == "forte").any() else "modérée"
        merged.append(top)
    rest = pd.concat([both[~dup], df[~df["kind"].isin(["jump", "divergence"])]], ignore_index=True)
    out = pd.concat([rest, pd.DataFrame(merged)], ignore_index=True) if merged else rest
    return out[COLUMNS].sort_values(["month", "score"], ascending=[False, False], key=lambda s: s.abs() if s.name == "score" else s,
                                    ignore_index=True)


def recent_anomalies(anom: pd.DataFrame, months: int = 3) -> pd.DataFrame:
    """Anomalies des `months` derniers mois présents dans le tableau."""
    if anom.empty:
        return anom
    last = pd.Period(str(anom["month"].max()), freq="M")
    cutoff = str(last - (months - 1))
    return anom[anom["month"] >= cutoff].reset_index(drop=True)


# ----------------------------------------------------------------------------
# Validation par chocs injectés
# ----------------------------------------------------------------------------
def inject_shocks(kg_df: pd.DataFrame, n: int, magnitude: float, seed: int = 0, window_months: int = 12):
    """Multiplie la valeur de `n` (série, mois) récents par (1 ± magnitude). Retourne (df modifié, {(clé, mois)})."""
    rng = np.random.default_rng(seed)
    df = kg_df.copy().reset_index(drop=True)
    d = _clean(df)
    end = int(d["ordinal"].max())
    counts = d.groupby(SERIES_KEYS)["ordinal"].transform("size")
    cand = d[(counts >= MIN_HISTORY + 4) & (d["ordinal"] > end - window_months)]
    # il faut un mois précédent consécutif
    prev_ok = cand.merge(d[SERIES_KEYS + ["ordinal"]].assign(ordinal=lambda x: x["ordinal"] + 1),
                         on=SERIES_KEYS + ["ordinal"], how="inner")
    if prev_ok.empty:
        return df, set()
    pick = prev_ok.sample(n=min(n, len(prev_ok)), random_state=int(rng.integers(0, 2**31 - 1)))
    pick = pick.drop_duplicates(SERIES_KEYS)
    truth = set()
    for r in pick.itertuples(index=False):
        sign = 1.0 if rng.random() < 0.5 else -1.0
        mask = ((df[SERIES_KEYS[0]] == r.source) & (df["province"] == r.province) & (df["market_name"] == r.market_name)
                & (df["commodity_std"] == r.commodity_std)
                & (df["year_month"].dt.year * 12 + df["year_month"].dt.month == r.ordinal))
        df.loc[mask, "value"] = df.loc[mask, "value"] * (1.0 + sign * magnitude)
        year, month0 = divmod(int(r.ordinal) - 1, 12)
        truth.add((r.source, r.province, r.market_name, r.commodity_std, f"{year:04d}-{month0 + 1:02d}"))
    return df, truth


def evaluate_detection(kg_df: pd.DataFrame, magnitudes=(0.15, 0.25, 0.40), n: int = 150, seed: int = 0,
                       window_months: int = 12) -> dict:
    """Taux de détection par amplitude de choc + taux d'alertes sur les données telles quelles.

    Les données réelles contiennent de vraies anomalies : « alertes sur données brutes » est donc une borne
    HAUTE du taux de fausses alertes, pas une mesure exacte.
    """
    base = detect_anomalies(kg_df)
    d = _clean(kg_df)
    end = int(d["ordinal"].max())
    series_months = int(((d["ordinal"] > end - window_months)).sum())
    recent = base[base["kind"].isin(["jump", "divergence", "jump+divergence"])]
    cutoff_year, cutoff_m0 = divmod(end - window_months, 12)
    cutoff = f"{cutoff_year:04d}-{cutoff_m0 + 1:02d}"
    n_alerts = int((recent["month"] > cutoff).sum())
    out = {"series_months": series_months, "alerts_on_raw_data": n_alerts,
           "alert_rate_pct": 100.0 * n_alerts / max(series_months, 1), "detection": {}}
    for mag in magnitudes:
        shocked, truth = inject_shocks(kg_df, n, mag, seed=seed, window_months=window_months)
        if not truth:
            out["detection"][mag] = {"injected": 0, "detected": 0, "rate": float("nan")}
            continue
        found = detect_anomalies(shocked)
        found = found[found["kind"].isin(["jump", "divergence", "jump+divergence"])]
        flagged = set(map(tuple, found[SERIES_KEYS + ["month"]].itertuples(index=False, name=None)))
        hit = len(truth & flagged)
        out["detection"][mag] = {"injected": len(truth), "detected": hit, "rate": hit / len(truth)}
    return out
