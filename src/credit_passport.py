import numpy as np
import pandas as pd


def compute_credit_passport(kg_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule le score bancaire Agricultural Credit Passport (0-100) par (province, produit)
    avec régularisation bayésienne empirique pour pénaliser les séries à faible observabilité.
    """
    nat_med = kg_df.groupby(["commodity_std", "year_month"])["value"].median().reset_index().rename(columns={"value": "nat_median"})
    merged = pd.merge(kg_df, nat_med, on=["commodity_std", "year_month"], how="left")
    merged["spatial_spread_pct"] = np.abs(merged["value"] - merged["nat_median"]) / merged["nat_median"]

    rows = []
    for (prov, comm), grp in merged.groupby(["province", "commodity_std"]):
        if len(grp) < 6:
            continue
        monthly_s = grp.groupby("year_month")["value"].median().sort_index()
        obs_months = len(monthly_s)
        w_cred = obs_months / (obs_months + 12.0)

        raw_cv = monthly_s.std() / (monthly_s.mean() + 1e-6)
        adj_cv = w_cred * raw_cv + (1.0 - w_cred) * 0.35

        roll_max = monthly_s.rolling(3, min_periods=1).max()
        raw_dd = ((roll_max - monthly_s) / (roll_max + 1e-6)).max()
        adj_dd = w_cred * raw_dd + (1.0 - w_cred) * 0.45

        spatial_friction = grp["spatial_spread_pct"].median()

        s_stability = float(np.clip(100.0 * (1.0 - adj_cv / 0.50), 0, 100))
        s_drawdown = float(np.clip(100.0 * (1.0 - adj_dd / 0.60), 0, 100))
        s_logistics = float(np.clip(100.0 * (1.0 - spatial_friction / 0.50), 0, 100))
        s_coverage = float(np.clip(100.0 * (obs_months / 30.0), 0, 100))

        credit_score = round(0.35 * s_stability + 0.30 * s_drawdown + 0.20 * s_logistics + 0.15 * s_coverage, 1)
        if credit_score >= 70:
            grade, ltv, policy = "A (Faible Risque)", 0.80, "Éligible — Financement Standard (taux préférentiel -1,5 %)"
        elif credit_score >= 58:
            grade, ltv, policy = "B (Risque Modéré)", 0.65, "Éligible — Sous réserve de stockage warranté"
        elif credit_score >= 45:
            grade, ltv, policy = "C (Risque Élevé)", 0.50, "Conditionnel — Assurance récolte ou caution mutuelle requise"
        else:
            grade, ltv, policy = "D (Risque Critique)", 0.30, "Risque Critique — Micro-tranches plafonnées uniquement"

        rows.append({
            "province": prov,
            "commodity_std": comm,
            "credit_score": credit_score,
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
