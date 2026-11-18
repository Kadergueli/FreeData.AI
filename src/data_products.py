"""Reusable Data Products Catalog with license-enforced export."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.analytics import AnalyticsService
from src.governance import LicensingRegistry


class DataProductCatalog:
    """Publishes structured, schema-documented data products governed by LicensingRegistry."""

    PRODUCTS: dict[str, dict[str, Any]] = {
        "commodity_forecasts_v1": {
            "product_id": "commodity_forecasts_v1",
            "title": "Agricultural Commodity Price Forecasts (t+1)",
            "description": "Monthly t+1 price forecasts with 80% confidence intervals and historical MAE.",
            "source_dataset_id": "table_ml_forecasts",
            "version": "1.0.0",
            "update_frequency": "Monthly",
            "geographic_coverage": "Tracked provinces in Chad",
            "schema": {
                "province": "string",
                "market_name": "string",
                "commodity_std": "string",
                "last_observed_month": "YYYY-MM",
                "last_observed_price": "float (XAF/kg)",
                "forecast_month": "YYYY-MM",
                "forecast_t1": "float (XAF/kg)",
                "ci_low_80": "float (XAF/kg)",
                "ci_high_80": "float (XAF/kg)",
            },
        },
        "market_stability_index_v1": {
            "product_id": "market_stability_index_v1",
            "title": "Agricultural Market Risk & Stability Index",
            "description": "Composite stability score (0-100), risk grade, CV %, and indicative LTV.",
            "source_dataset_id": "table_ml_credit_passport",
            "version": "1.0.0",
            "update_frequency": "Monthly",
            "geographic_coverage": "Tracked provinces in Chad",
            "schema": {
                "province": "string",
                "commodity_std": "string",
                "credit_score": "float (0-100)",
                "grade": "string (A-D)",
                "cv_pct": "float (%)",
                "ltv_ratio": "float (0-1)",
            },
        },
        "regional_price_indicators_v1": {
            "product_id": "regional_price_indicators_v1",
            "title": "Provincial Price Disparities & Coverage",
            "description": "Derived provincial median prices and market coverage counts.",
            "source_dataset_id": "table_ml_forecasts",
            "version": "1.0.0",
            "update_frequency": "Monthly",
            "geographic_coverage": "Tracked provinces in Chad",
            "schema": {
                "province": "string",
                "markets_count": "integer",
                "median_observed_xaf_kg": "float",
                "median_forecast_t1_xaf_kg": "float",
            },
        },
        "raw_market_observations_restricted": {
            "product_id": "raw_market_observations_restricted",
            "title": "Raw Market Survey Observations (Restricted)",
            "description": "Unredacted primary survey table with unverified upstream redistribution license.",
            "source_dataset_id": "table_public",
            "version": "1.0.0",
            "update_frequency": "Monthly",
            "geographic_coverage": "Tracked markets in Chad",
            "schema": {"province": "string", "market_name": "string", "price": "float"},
        },
    }

    def list_products(self, registry: LicensingRegistry, forecast_df: pd.DataFrame) -> list[dict[str, Any]]:
        obs_months = forecast_df["last_observed_month"].dropna().astype(str) if (forecast_df is not None and not forecast_df.empty and "last_observed_month" in forecast_df.columns) else pd.Series(dtype=str)
        time_cov = {"latest_month": str(obs_months.max())} if not obs_months.empty else {"latest_month": None}

        out = []
        for pid, spec in self.PRODUCTS.items():
            ds_id = spec["source_dataset_id"]
            lic = registry.get_entry(ds_id).to_dict()
            out.append({
                **spec,
                "time_coverage": time_cov,
                "attribution": registry.get_attribution_notices([ds_id]),
                "license": {
                    "name": lic["license_name"],
                    "category": lic["license_category"],
                    "redistribution_allowed": registry.check_redistribution_allowed(ds_id),
                    "publication_status": lic["publication_status"],
                },
            })
        return out

    def get_product(self, product_id: str, registry: LicensingRegistry, forecast_df: pd.DataFrame) -> dict[str, Any]:
        for item in self.list_products(registry, forecast_df):
            if item["product_id"] == product_id:
                return item
        raise KeyError(f"Produit de données introuvable : {product_id}")

    def export_product(
        self,
        product_id: str,
        *,
        registry: LicensingRegistry,
        forecast_df: pd.DataFrame,
        passport_df: pd.DataFrame,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if product_id not in self.PRODUCTS:
            raise KeyError(f"Produit de données introuvable : {product_id}")
        spec = self.PRODUCTS[product_id]
        ds_id = spec["source_dataset_id"]
        registry.assert_redistribution_allowed(ds_id)

        if product_id == "commodity_forecasts_v1":
            df = forecast_df if forecast_df is not None else pd.DataFrame()
            page = df.iloc[offset : offset + limit].where(df.notna(), None).to_dict(orient="records") if not df.empty else []
            total = int(len(df))
        elif product_id == "market_stability_index_v1":
            df = passport_df if passport_df is not None else pd.DataFrame()
            page = df.iloc[offset : offset + limit].where(df.notna(), None).to_dict(orient="records") if not df.empty else []
            total = int(len(df))
        else:  # regional_price_indicators_v1
            reg = AnalyticsService().get_regional_comparison(forecast_df)
            rows = reg.get("provinces") or []
            total = len(rows)
            page = rows[offset : offset + limit]

        return {
            "product_id": product_id,
            "version": spec["version"],
            "attribution": registry.get_attribution_notices([ds_id]),
            "total": total,
            "records": page,
        }

