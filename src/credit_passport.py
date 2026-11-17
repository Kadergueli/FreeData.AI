import math

import numpy as np
import pandas as pd

INDEX_NAME = "Agricultural Market Risk & Stability Index"

PASSPORT_METHODOLOGY = {
    "index_name": INDEX_NAME,
    "scope": "Mesure la stabilité des prix d'une filière agricole (province × produit), jamais la solvabilité d'un emprunteur.",
    "calibrated_against_loan_defaults": False,
    "min_observations": 6,
    "weights": {
        "price_stability_cv": 0.35,
        "max_drawdown": 0.30,
        "spatial_market_friction": 0.20,
        "data_coverage": 0.15,
    },
    "shrinkage": {
        "formula": "w = obs_months / (obs_months + 12.0)",
        "prior_cv": 0.35,
        "prior_max_drawdown": 0.45,
    },
    "grade_thresholds": {
        "A": ">= 70 (LTV indicatif 0.80)",
        "B": "58 à 69.9 (LTV indicatif 0.65)",
        "C": "45 à 57.9 (LTV indicatif 0.50)",
        "D": "< 45 (LTV indicatif 0.30)",
    },
}


def compute_recommended_max_loan(collateral_value_xaf: float, ltv_ratio: float) -> int:
    """Calcule le plafond indicatif de prêt à partir de la valeur de la garantie (collatéral) et du LTV."""
    val = float(collateral_value_xaf)
    if not math.isfinite(val) or val < 0.0:
        raise ValueError("La valeur du collatéral doit être supérieure ou égale à 0.")
    return int(val * max(0.0, float(ltv_ratio)))


def compute_credit_passport(kg_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule l'indice de stabilité des marchés agricoles (`Agricultural Market Risk & Stability Index`, 0-100)
    par (province, produit) avec régularisation bayésienne empirique.
    """
    if kg_df is None or kg_df.empty:
        return pd.DataFrame()
    clean = kg_df.dropna(subset=["value", "province", "commodity_std", "year_month"]).copy()
    if clean.empty:
        return pd.DataFrame()

    nat_med = clean.groupby(["commodity_std", "year_month"])["value"].median().reset_index().rename(columns={"value": "nat_median"})
    merged = pd.merge(clean, nat_med, on=["commodity_std", "year_month"], how="left")
    merged["spatial_spread_pct"] = np.abs(merged["value"] - merged["nat_median"]) / (merged["nat_median"] + 1e-6)

    rows = []
    for (prov, comm), grp in merged.groupby(["province", "commodity_std"]):
        if len(grp) < 6:
            continue
        monthly_s = grp.groupby("year_month")["value"].median().sort_index()
        obs_months = len(monthly_s)
        w_cred = obs_months / (obs_months + 12.0)

        raw_cv = monthly_s.std() / (monthly_s.mean() + 1e-6)
        raw_cv = 0.0 if pd.isna(raw_cv) else float(raw_cv)
        adj_cv = w_cred * raw_cv + (1.0 - w_cred) * 0.35

        roll_max = monthly_s.rolling(3, min_periods=1).max()
        raw_dd = float(((roll_max - monthly_s) / (roll_max + 1e-6)).max())
        adj_dd = w_cred * raw_dd + (1.0 - w_cred) * 0.45

        spatial_friction = float(grp["spatial_spread_pct"].median())

        s_stability = float(np.clip(100.0 * (1.0 - adj_cv / 0.50), 0, 100))
        s_drawdown = float(np.clip(100.0 * (1.0 - adj_dd / 0.60), 0, 100))
        s_logistics = float(np.clip(100.0 * (1.0 - spatial_friction / 0.50), 0, 100))
        s_coverage = float(np.clip(100.0 * (obs_months / 30.0), 0, 100))

        credit_score = round(0.35 * s_stability + 0.30 * s_drawdown + 0.20 * s_logistics + 0.15 * s_coverage, 1)
        if credit_score >= 70:
            grade, ltv, policy = "A (Stabilité Élevée)", 0.80, "Marché stable — LTV indicatif 80 % sur stock warranté"
        elif credit_score >= 58:
            grade, ltv, policy = "B (Risque Modéré)", 0.65, "Stabilité modérée — LTV indicatif 65 % avec suivi prix"
        elif credit_score >= 45:
            grade, ltv, policy = "C (Risque Élevé)", 0.50, "Volatilité notable — LTV indicatif 50 % et couverture conseillée"
        else:
            grade, ltv, policy = "D (Risque Critique)", 0.30, "Forte instabilité — LTV indicatif plafonné à 30 %"

        rows.append({
            "province": prov,
            "commodity_std": comm,
            "credit_score": credit_score,
            "market_stability_index": credit_score,
            "grade": grade,
            "ltv_ratio": ltv,
            "policy_recommendation": policy,
            "s_stability": round(s_stability, 1),
            "s_drawdown": round(s_drawdown, 1),
            "s_logistics": round(s_logistics, 1),
            "s_coverage": round(s_coverage, 1),
            "median_price": round(float(monthly_s.median()), 1),
            "cv_pct": round(float(adj_cv * 100), 1),
            "max_drawdown_pct": round(float(adj_dd * 100), 1),
            "obs_months": obs_months,
        })

    return pd.DataFrame(rows)
