"""Economic & Market Intelligence Engine: volatility ranking, 12-month trends, and inflation guardrails."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


class EconomicIntelligenceEngine:
    """Computes commodity volatility rankings and historical price evolution from verified market series."""

    def volatility_ranking(self, passport_df: pd.DataFrame, forecast_df: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
        if passport_df is not None and not passport_df.empty and "cv_pct" in passport_df.columns:
            sub = passport_df.dropna(subset=["cv_pct"]).copy()
            sub["cv_pct"] = pd.to_numeric(sub["cv_pct"], errors="coerce")
            agg = (
                sub.groupby("commodity_std", as_index=False)["cv_pct"]
                .mean()
                .sort_values("cv_pct", ascending=False)
                .head(limit)
            )
            return [
                {
                    "commodity": str(r["commodity_std"]),
                    "avg_cv_pct": round(float(r["cv_pct"]), 2),
                    "source": "table_ml_credit_passport (FreeData-derived)",
                }
                for _, r in agg.iterrows()
            ]
        return []

    def price_evolution_12m(
        self,
        hist_df: pd.DataFrame,
        *,
        commodity: Optional[str] = None,
        province: Optional[str] = None,
        limit: int = 24,
        offset: int = 0,
    ) -> dict[str, Any]:
        if hist_df is None or hist_df.empty or "date" not in hist_df.columns:
            return {"records": [], "total": 0, "change_12m_pct": None, "unit": "XAF/kg"}

        pcol = "price" if "price" in hist_df.columns else ("value" if "value" in hist_df.columns else None)
        if not pcol:
            return {"records": [], "total": 0, "change_12m_pct": None, "unit": "XAF/kg"}

        sub = hist_df.copy()
        if commodity and "commodity_std" in sub.columns:
            sub = sub[sub["commodity_std"].astype(str).str.lower() == commodity.strip().lower()]
        if province and "province" in sub.columns:
            sub = sub[sub["province"].astype(str).str.lower() == province.strip().lower()]

        sub["ym"] = pd.to_datetime(sub["date"], errors="coerce").dt.to_period("M").astype(str)
        sub["p_val"] = pd.to_numeric(sub[pcol], errors="coerce")
        monthly = (
            sub.dropna(subset=["ym", "p_val"])
            .groupby("ym", as_index=False)["p_val"]
            .median()
            .sort_values("ym")
        )
        if monthly.empty:
            return {"records": [], "total": 0, "change_12m_pct": None, "unit": "XAF/kg"}

        recent = monthly.tail(12)
        first_p = float(recent.iloc[0]["p_val"])
        last_p = float(recent.iloc[-1]["p_val"])
        chg_pct = round(((last_p / first_p) - 1.0) * 100.0, 2) if first_p > 0 else None

        records = [
            {"month": str(r["ym"]), "median_price_xaf_kg": round(float(r["p_val"]), 1)}
            for _, r in monthly.iloc[offset : offset + limit].iterrows()
        ]
        return {
            "records": records,
            "total": int(len(monthly)),
            "period_start": str(recent.iloc[0]["ym"]),
            "period_end": str(recent.iloc[-1]["ym"]),
            "change_12m_pct": chg_pct,
            "unit": "XAF/kg",
            "note": "Variation observée sur les produits suivis uniquement ; ne constitue pas un indice national d'inflation (IPC).",
        }

