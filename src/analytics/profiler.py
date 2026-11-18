"""Data Profiling Engine: inspects dataset completeness, duplicates, date span, and coverage."""
from __future__ import annotations

from typing import Any

import pandas as pd


class DataProfiler:
    """Profiles forecast and historical market DataFrames without mutating source data."""

    def profile(self, forecast_df: pd.DataFrame, hist_df: pd.DataFrame) -> dict[str, Any]:
        fc = forecast_df if forecast_df is not None else pd.DataFrame()
        hist = hist_df if hist_df is not None else pd.DataFrame()

        fc_provs = sorted(fc["province"].dropna().astype(str).unique().tolist()) if "province" in fc.columns else []
        fc_comms = sorted(fc["commodity_std"].dropna().astype(str).unique().tolist()) if "commodity_std" in fc.columns else []
        sources = sorted(fc["source"].dropna().astype(str).unique().tolist()) if "source" in fc.columns else []

        obs_months = fc["last_observed_month"].dropna().astype(str) if "last_observed_month" in fc.columns else pd.Series(dtype=str)
        dup_cols = [c for c in ("province", "market_name", "commodity_std", "forecast_month") if c in fc.columns]
        fc_dups = int(fc.duplicated(subset=dup_cols).sum()) if dup_cols and not fc.empty else 0

        missing_rates: dict[str, float] = {}
        if not fc.empty:
            for col in ("last_observed_price", "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae"):
                if col in fc.columns:
                    missing_rates[col] = round(float(fc[col].isna().mean() * 100.0), 2)

        hist_span = {"start": None, "end": None}
        if not hist.empty and "date" in hist.columns:
            dates = pd.to_datetime(hist["date"], errors="coerce").dropna()
            if not dates.empty:
                hist_span = {"start": dates.min().strftime("%Y-%m-%d"), "end": dates.max().strftime("%Y-%m-%d")}

        return {
            "forecast_rows": int(len(fc)),
            "historical_rows": int(len(hist)),
            "provinces_count": len(fc_provs),
            "commodities_count": len(fc_comms),
            "sources": sources,
            "latest_observed_month": str(obs_months.max()) if not obs_months.empty else None,
            "historical_date_span": hist_span,
            "forecast_duplicate_rows": fc_dups,
            "missing_rates_pct": missing_rates,
            "unsupported_domains": [
                "national_cpi_inflation (incomplete basket)",
                "agricultural_production_tonnage (not in dataset)",
                "household_demand_volumes (not in dataset)",
                "population_demographics (not in dataset)",
            ],
        }

