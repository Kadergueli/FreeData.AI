"""Chronological Forecasting Benchmark Engine: Naive vs Moving Average vs Exponential Smoothing."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class ForecastingBenchmarkEngine:
    """Evaluates simple baseline models on chronological splits; refuses publishing when history < 6 months."""

    def benchmark_series(
        self,
        hist_df: pd.DataFrame,
        *,
        commodity: str,
        province: str,
        min_history: int = 6,
    ) -> dict[str, Any]:
        if hist_df is None or hist_df.empty or "date" not in hist_df.columns:
            return {"status": "insufficient_history", "reason": "Historique vide.", "models": []}

        pcol = "price" if "price" in hist_df.columns else ("value" if "value" in hist_df.columns else None)
        if not pcol:
            return {"status": "insufficient_history", "reason": "Colonne de prix absente.", "models": []}

        sub = hist_df[
            (hist_df["commodity_std"].astype(str).str.lower() == commodity.strip().lower())
            & (hist_df["province"].astype(str).str.lower() == province.strip().lower())
        ].copy()
        sub["ym"] = pd.to_datetime(sub["date"], errors="coerce").dt.to_period("M").astype(str)
        sub["p_val"] = pd.to_numeric(sub[pcol], errors="coerce")
        series = (
            sub.dropna(subset=["ym", "p_val"])
            .groupby("ym", as_index=False)["p_val"]
            .median()
            .sort_values("ym")["p_val"]
            .to_numpy(dtype=float)
        )

        if len(series) < min_history:
            return {
                "status": "insufficient_history",
                "observations": int(len(series)),
                "min_required": min_history,
                "reason": f"Historique insuffisant ({len(series)} < {min_history} mois) : prévision non publiée.",
                "models": [],
            }

        split = max(3, int(len(series) * 0.7))
        actuals = series[split:]
        naive_preds = series[split - 1 : -1]
        ma3_preds = np.array([series[i - 3 : i].mean() for i in range(split, len(series))])

        # Simple Exponential Smoothing (alpha = 0.4) walk-forward
        alpha = 0.4
        ses_preds = []
        level = float(series[0])
        for i in range(1, len(series)):
            if i >= split:
                ses_preds.append(level)
            level = alpha * float(series[i]) + (1.0 - alpha) * level
        ses_arr = np.array(ses_preds, dtype=float)

        def _metrics(name: str, preds: np.ndarray) -> dict[str, Any]:
            err = actuals - preds
            mae = float(np.mean(np.abs(err)))
            rmse = float(np.sqrt(np.mean(err ** 2)))
            nonzero = actuals > 0
            mape = float(np.mean(np.abs(err[nonzero]) / actuals[nonzero]) * 100.0) if nonzero.any() else 0.0
            return {
                "model": name,
                "mae_xaf_kg": round(mae, 2),
                "rmse_xaf_kg": round(rmse, 2),
                "mape_pct": round(mape, 2),
            }

        models = sorted(
            [
                _metrics("naive_last_value", naive_preds),
                _metrics("moving_average_3m", ma3_preds),
                _metrics("exponential_smoothing_0.4", ses_arr),
            ],
            key=lambda m: m["mae_xaf_kg"],
        )
        return {
            "status": "evaluated",
            "commodity": commodity,
            "province": province,
            "train_months": int(split),
            "test_months": int(len(actuals)),
            "best_model": models[0]["model"],
            "models": models,
        }

