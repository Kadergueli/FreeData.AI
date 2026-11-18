"""Statistical Analysis Engine: descriptive stats, distribution, outliers, and correlation."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


class StatisticalEngine:
    """Computes descriptive statistics, IQR outliers, and correlation (never conflating correlation with causation)."""

    @staticmethod
    def _price_col(df: pd.DataFrame) -> Optional[str]:
        for col in ("last_observed_price", "value", "price", "forecast_t1"):
            if col in df.columns:
                return col
        return None

    def descriptive_summary(
        self,
        df: pd.DataFrame,
        *,
        commodity: Optional[str] = None,
        province: Optional[str] = None,
    ) -> dict[str, Any]:
        if df is None or df.empty:
            return {"count": 0, "unit": "XAF/kg", "stats": None}

        sub = df.copy()
        if commodity and "commodity_std" in sub.columns:
            sub = sub[sub["commodity_std"].astype(str).str.lower() == commodity.strip().lower()]
        if province and "province" in sub.columns:
            sub = sub[sub["province"].astype(str).str.lower() == province.strip().lower()]

        pcol = self._price_col(sub)
        if not pcol or sub.empty:
            return {"count": 0, "unit": "XAF/kg", "stats": None}

        vals = pd.to_numeric(sub[pcol], errors="coerce").dropna()
        if vals.empty:
            return {"count": 0, "unit": "XAF/kg", "stats": None}

        mean_v = float(vals.mean())
        std_v = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
        q25, q50, q75 = [float(x) for x in np.percentile(vals, [25, 50, 75])]
        iqr = q75 - q25
        low_fence = q25 - 1.5 * iqr
        high_fence = q75 + 1.5 * iqr
        outlier_count = int(((vals < low_fence) | (vals > high_fence)).sum())

        return {
            "count": int(len(vals)),
            "unit": "XAF/kg",
            "price_column_used": pcol,
            "stats": {
                "mean": round(mean_v, 2),
                "median": round(q50, 2),
                "std": round(std_v, 2),
                "cv_pct": round((std_v / mean_v) * 100.0, 2) if mean_v > 0 else 0.0,
                "min": round(float(vals.min()), 2),
                "q25": round(q25, 2),
                "q75": round(q75, 2),
                "max": round(float(vals.max()), 2),
                "iqr": round(iqr, 2),
                "iqr_outlier_count": outlier_count,
            },
        }

    def province_correlation(
        self,
        hist_df: pd.DataFrame,
        commodity: str,
        province_a: str,
        province_b: str,
    ) -> dict[str, Any]:
        if hist_df is None or hist_df.empty or "date" not in hist_df.columns:
            return {"available": False, "reason": "Historique insuffisant pour calculer une corrélation."}

        pcol = "price" if "price" in hist_df.columns else ("value" if "value" in hist_df.columns else None)
        if not pcol:
            return {"available": False, "reason": "Colonne de prix absente."}

        sub = hist_df[hist_df["commodity_std"].astype(str).str.lower() == commodity.strip().lower()].copy()
        sub["ym"] = pd.to_datetime(sub["date"], errors="coerce").dt.to_period("M").astype(str)
        sub["p_val"] = pd.to_numeric(sub[pcol], errors="coerce")
        piv = sub.groupby(["ym", "province"])["p_val"].median().unstack()
        if province_a not in piv.columns or province_b not in piv.columns:
            return {"available": False, "reason": "Une des provinces est absente de l'historique."}

        paired = piv[[province_a, province_b]].dropna()
        if len(paired) < 4:
            return {"available": False, "reason": f"Moins de 4 mois communs ({len(paired)})."}

        corr = float(paired[province_a].corr(paired[province_b]))
        return {
            "available": True,
            "commodity": commodity,
            "province_a": province_a,
            "province_b": province_b,
            "common_months": int(len(paired)),
            "pearson_r": round(corr, 3),
            "methodological_note": "Corrélation linéaire observée uniquement ; ne prouve pas une relation de causalité.",
        }

