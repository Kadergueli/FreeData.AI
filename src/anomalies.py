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
# 1 + 2. Sauts de prix et divergences entre marchés (un seul passage de calcul)
# ----------------------------------------------------------------------------
TARGET_RATE = 0.03       # part visée de séries-mois signalés par type de signal (étalonnage par produit)
MIN_CALIBRATION = 60     # contrôles minimum d'un produit pour étalonner son seuil
CALIBRATION_CAP = 2.0    # l'étalonnage ne relève jamais le seuil au-delà de 2 × la base (les vraies anomalies faussent le quantile)
COMMON_SHARE = 0.5       # un saut dont ≥ 50 % est partagé par la médiane des marchés est un mouvement général


def _checks(kg_df: pd.DataFrame) -> pd.DataFrame:
    """Un contrôle par (série, mois) ayant assez d'historique : z du saut, z de la divergence, mouvement des pairs.

    Chaque z n'utilise que le passé de la série (aucune fuite). Les contrôles ne sont PAS encore filtrés : l'étalonnage
    des seuils par produit se fait ensuite sur leur distribution réelle.
    """
    rows = []
    for comm, sub in _clean(kg_df).groupby("commodity_std"):
        piv = sub.pivot_table(index="ordinal", columns=SERIES_KEYS, values="value", aggfunc="last").sort_index()
        full = piv.reindex(range(int(piv.index.min()), int(piv.index.max()) + 1))
        lr = np.log(full / full.shift(1))                  # NaN si le mois précédent manque : mois consécutifs seulement
        have_peers = lr.notna().sum(axis=1) >= MIN_PEERS
        peer_med = lr.median(axis=1).where(have_peers)
        rel = lr.sub(peer_med, axis=0)
        for key in full.columns:
            own = lr[key].dropna()
            rel_s = rel[key].dropna()
            z_j, z_d, gap = {}, {}, {}
            if len(own) > MIN_HISTORY:
                o_ord, o_val = own.index.to_numpy(), own.to_numpy(float)
                for i in range(MIN_HISTORY, len(o_val)):
                    z_j[int(o_ord[i])] = _robust_z(o_val[:i], o_val[i])[0]
            if len(rel_s) > MIN_HISTORY:
                r_ord, r_val = rel_s.index.to_numpy(), rel_s.to_numpy(float)
                for i in range(MIN_HISTORY, len(r_val)):
                    z, center = _robust_z(r_val[:i], r_val[i])
                    z_d[int(r_ord[i])] = z
                    gap[int(r_ord[i])] = float(np.expm1(r_val[i] - center))
            for ordinal in set(z_j) | set(z_d):
                cur = float(full.loc[ordinal, key])
                prev = float(full.loc[ordinal - 1, key])
                pm = peer_med.get(ordinal, np.nan)
                rows.append({
                    "commodity_std": comm, "key": key, "ordinal": ordinal, "cur": cur, "prev": prev,
                    "z_jump": z_j.get(ordinal, np.nan), "move": cur / prev - 1.0,
                    "z_div": z_d.get(ordinal, np.nan), "gap": gap.get(ordinal, np.nan),
                    "peer_move": float(np.expm1(pm)) if pd.notna(pm) else np.nan,
                })
    return pd.DataFrame(rows)


def _calibrated(checks: pd.DataFrame, col: str, base: float, target_rate: float) -> pd.Series:
    """Seuil de |z| par produit : au moins `base`, et au moins le quantile (1 - target_rate) de son bruit réel."""
    def thr(g):
        v = g[col].abs().dropna()
        return min(max(base, float(v.quantile(1.0 - target_rate))), CALIBRATION_CAP * base) if len(v) >= MIN_CALIBRATION else base
    return checks.groupby("commodity_std").apply(thr, include_groups=False)


def _signals(checks: pd.DataFrame, kind: str, z_threshold: float, min_size: float, target_rate: float) -> list[dict]:
    if checks.empty:
        return []
    zcol, sizecol = ("z_jump", "move") if kind == "jump" else ("z_div", "gap")
    thr = checks["commodity_std"].map(_calibrated(checks, zcol, z_threshold, target_rate))
    hit = (checks[zcol].abs() >= thr) & (checks[sizecol].abs() >= min_size)
    if kind == "jump":
        common = checks["peer_move"].notna() & (np.sign(checks["peer_move"]) == np.sign(checks["move"])) & \
            (checks["peer_move"].abs() >= COMMON_SHARE * checks["move"].abs())
        hit &= ~common            # mouvement général (saison, choc commun) : pas une anomalie propre à ce marché
    out = []
    for r in checks[hit].itertuples(index=False):
        size, z = getattr(r, sizecol), getattr(r, zcol)
        ref = r.prev if kind == "jump" else r.prev * (1.0 + (r.peer_move if pd.notna(r.peer_move) else 0.0))
        out.append(_row(r.key, kind, _severity(z, size), r.ordinal, r.cur, ref, size * 100, z))
    return out


def jump_anomalies(kg_df: pd.DataFrame, z_threshold: float = Z_THRESHOLD, min_move: float = MIN_MOVE,
                   target_rate: float = TARGET_RATE, checks: Optional[pd.DataFrame] = None) -> list[dict]:
    return _signals(_checks(kg_df) if checks is None else checks, "jump", z_threshold, min_move, target_rate)


def divergence_anomalies(kg_df: pd.DataFrame, z_threshold: float = Z_THRESHOLD, min_divergence: float = MIN_DIVERGENCE,
                         target_rate: float = TARGET_RATE, checks: Optional[pd.DataFrame] = None) -> list[dict]:
    """Un choc commun à tous les marchés n'est pas une divergence ; un marché qui bouge seul l'est."""
    return _signals(_checks(kg_df) if checks is None else checks, "divergence", z_threshold, min_divergence, target_rate)


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
    checks = _checks(kg_df)
    rows = jump_anomalies(kg_df, checks=checks) + divergence_anomalies(kg_df, checks=checks) + quality_issues(kg_df)
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
