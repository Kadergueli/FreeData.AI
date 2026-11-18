"""Geospatial Intelligence Engine: provincial comparisons, coverage counts, and geographic gaps."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


class GeospatialEngine:
    """Analyzes provincial price disparities and geographic coverage using existing administrative identifiers."""

    def regional_comparison(
        self,
        forecast_df: pd.DataFrame,
        *,
        commodity: Optional[str] = None,
    ) -> dict[str, Any]:
        if forecast_df is None or forecast_df.empty or "province" not in forecast_df.columns:
            return {"provinces": [], "spatial_spread_xaf_kg": None, "missing_provinces": []}

        all_provinces = sorted(forecast_df["province"].dropna().astype(str).unique().tolist())
        sub = forecast_df.copy()
        if commodity and "commodity_std" in sub.columns:
            sub = sub[sub["commodity_std"].astype(str).str.lower() == commodity.strip().lower()]

        pcol = "last_observed_price" if "last_observed_price" in sub.columns else "forecast_t1"
        sub["obs"] = pd.to_numeric(sub[pcol], errors="coerce") if pcol in sub.columns else float("nan")
        sub["fc"] = pd.to_numeric(sub["forecast_t1"], errors="coerce") if "forecast_t1" in sub.columns else float("nan")

        agg = (
            sub.groupby("province", as_index=False)
            .agg(
                markets_count=("market_name", "nunique") if "market_name" in sub.columns else ("province", "count"),
                median_observed_xaf_kg=("obs", "median"),
                median_forecast_t1_xaf_kg=("fc", "median"),
            )
            .sort_values("median_observed_xaf_kg", ascending=False, na_position="last")
        )
        rows = []
        for _, r in agg.iterrows():
            obs_v = None if pd.isna(r["median_observed_xaf_kg"]) else round(float(r["median_observed_xaf_kg"]), 1)
            fc_v = None if pd.isna(r["median_forecast_t1_xaf_kg"]) else round(float(r["median_forecast_t1_xaf_kg"]), 1)
            rows.append({
                "province": str(r["province"]),
                "markets_count": int(r["markets_count"]),
                "median_observed_xaf_kg": obs_v,
                "median_forecast_t1_xaf_kg": fc_v,
            })

        valid_obs = [r["median_observed_xaf_kg"] for r in rows if r["median_observed_xaf_kg"] is not None]
        spread = round(max(valid_obs) - min(valid_obs), 1) if len(valid_obs) >= 2 else None
        covered = {r["province"] for r in rows}
        missing = [p for p in all_provinces if p not in covered]

        return {
            "commodity": commodity,
            "provinces": rows,
            "highest_province": rows[0] if rows and rows[0]["median_observed_xaf_kg"] is not None else None,
            "lowest_province": rows[-1] if rows and rows[-1]["median_observed_xaf_kg"] is not None else None,
            "spatial_spread_xaf_kg": spread,
            "missing_provinces": missing,
            "unit": "XAF/kg",
            "note": "Comparaison agrégée au niveau provincial ; aucune coordonnée GPS exacte n'est extrapolée.",
        }

