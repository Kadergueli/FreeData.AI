"""Unified AnalyticsService facade with pagination and lightweight in-memory caching."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from src.analytics.economic import EconomicIntelligenceEngine
from src.analytics.forecasting_eval import ForecastingBenchmarkEngine
from src.analytics.geospatial import GeospatialEngine
from src.analytics.profiler import DataProfiler
from src.analytics.statistics import StatisticalEngine


class AnalyticsService:
    """Reusable analytics service backing API endpoints and Chat Engine queries."""

    def __init__(self) -> None:
        self.profiler = DataProfiler()
        self.stats = StatisticalEngine()
        self.economic = EconomicIntelligenceEngine()
        self.geo = GeospatialEngine()
        self.benchmark = ForecastingBenchmarkEngine()
        self._cache: dict[tuple, Any] = {}

    @staticmethod
    def _sig(df: pd.DataFrame) -> tuple[int, str]:
        if df is None or df.empty:
            return (0, "")
        last_m = str(df["last_observed_month"].max()) if "last_observed_month" in df.columns else ""
        return (len(df), last_m)

    def get_profile(self, forecast_df: pd.DataFrame, hist_df: pd.DataFrame) -> dict[str, Any]:
        key = ("profile", self._sig(forecast_df), self._sig(hist_df))
        if key not in self._cache:
            self._cache[key] = self.profiler.profile(forecast_df, hist_df)
        return self._cache[key]

    def get_summary(
        self,
        forecast_df: pd.DataFrame,
        passport_df: pd.DataFrame,
        *,
        commodity: Optional[str] = None,
        province: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "descriptive": self.stats.descriptive_summary(forecast_df, commodity=commodity, province=province),
            "most_volatile_commodities": self.economic.volatility_ranking(passport_df, forecast_df, limit=10),
        }

    def get_trends(
        self,
        hist_df: pd.DataFrame,
        *,
        commodity: Optional[str] = None,
        province: Optional[str] = None,
        limit: int = 24,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.economic.price_evolution_12m(hist_df, commodity=commodity, province=province, limit=limit, offset=offset)

    def get_regional_comparison(self, forecast_df: pd.DataFrame, *, commodity: Optional[str] = None) -> dict[str, Any]:
        return self.geo.regional_comparison(forecast_df, commodity=commodity)

    def get_anomalies(
        self,
        anomalies_df: pd.DataFrame,
        *,
        province: Optional[str] = None,
        commodity: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if anomalies_df is None or anomalies_df.empty:
            return {"records": [], "total": 0, "note": "Aucune anomalie détectée ou table non chargée."}
        sub = anomalies_df.copy()
        if province and "province" in sub.columns:
            sub = sub[sub["province"].astype(str).str.lower() == province.strip().lower()]
        if commodity and "commodity_std" in sub.columns:
            sub = sub[sub["commodity_std"].astype(str).str.lower() == commodity.strip().lower()]
        total = int(len(sub))
        page = sub.iloc[offset : offset + limit].where(sub.notna(), None).to_dict(orient="records")
        return {
            "records": page,
            "total": total,
            "note": "Les observations inhabituelles sont signalées sans jamais être supprimées automatiquement.",
        }

    def get_forecast_benchmark(self, hist_df: pd.DataFrame, *, commodity: str, province: str) -> dict[str, Any]:
        return self.benchmark.benchmark_series(hist_df, commodity=commodity, province=province)

