"""
Script d'automatisation mensuelle post-collecte (MarketsAgent -> table_public -> Gold).
Calcule les nouvelles prévisions t+1 et met à jour table_ml_forecasts et table_ml_credit_passport.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport


def main():
    print(f"[FreeData.AI] Démarrage du pipeline mensuel (Backend: {settings.data_backend})...")
    kg_df = load_clean_markets()
    print(f"[FreeData.AI] {len(kg_df)} observations homogènes XAF/kg chargées.")

    _, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    print(f"[FreeData.AI] {len(forecast_df)} prévisions t+1 et {len(passport_df)} scores Credit Passport calculés.")

    if settings.data_backend == "supabase":
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.supabase_db_url)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE public.table_ml_forecasts RESTART IDENTITY;"))
            conn.execute(text("TRUNCATE TABLE public.table_ml_credit_passport RESTART IDENTITY;"))

        fc_cols = [
            "source", "province", "market_name", "commodity_std",
            "last_observed_month", "value", "forecast_month",
            "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae",
        ]
        fc_export = forecast_df[fc_cols].rename(columns={"value": "last_observed_price"})
        fc_export.to_sql("table_ml_forecasts", engine, schema="public", if_exists="append", index=False)

        cp_cols = [
            "province", "commodity_std", "credit_score", "grade",
            "ltv_ratio", "policy_recommendation",
            "s_stability", "s_drawdown", "s_logistics", "s_coverage",
            "median_price", "cv_pct", "max_drawdown_pct", "obs_months",
        ]
        passport_df[cp_cols].to_sql("table_ml_credit_passport", engine, schema="public", if_exists="append", index=False)
        print("[FreeData.AI] Tables Gold Supabase (table_ml_forecasts & table_ml_credit_passport) mises à jour.")
    else:
        forecast_df.to_csv("freedata_forecasts_t1.csv", index=False)
        passport_df.to_csv("freedata_credit_passport.csv", index=False)
        print("[FreeData.AI] Exports CSV locaux mis à jour (mode hors-ligne).")


if __name__ == "__main__":
    main()- ============================================================================
-- FreeData.AI | Couche Silver : Vue de standardisation unifiée sur Supabase
-- Branchée directement sur public.table_public (données validées et publiées).
-- ============================================================================

CREATE OR REPLACE VIEW public.v_clean_markets AS
WITH base_markets AS (
    SELECT
        id,
        source_api AS source,
        indicateur AS indicator,
        region,
        DATE_TRUNC('month', date_reference)::date AS month_date,
        LOWER(TRIM(unite)) AS raw_unit,
        valeur AS raw_value,
        CASE WHEN COALESCE(notes_publiques, '') LIKE '%OUTLIER%' THEN 1 ELSE 0 END AS is_flagged_outlier,
        score_qualite,
        date_publication
    FROM public.table_public
    WHERE source_api IN ('WFP', 'FEWS NET')
      AND valeur IS NOT NULL
),
standardized AS (
    SELECT
        id,
        source,
        month_date,
        CASE 
            WHEN raw_unit = 'xaf/500_g' THEN raw_value * 2.0
            WHEN raw_unit = 'xaf/400_g' THEN raw_value * 2.5
            ELSE raw_value
        END AS price_value,
        CASE 
            WHEN raw_unit IN ('xaf/500_g', 'xaf/400_g') THEN 'xaf/kg'
            ELSE raw_unit
        END AS unit_clean,
        CASE 
            WHEN source = 'WFP' THEN SUBSTRING(region FROM '\(([^()]+)\)$')
            ELSE region
        END AS province,
        CASE 
            WHEN source = 'WFP' THEN REGEXP_REPLACE(region, '\s*\([^()]+\)$', '')
            ELSE COALESCE(NULLIF(SPLIT_PART(indicator, ' - ', 2), ''), region || ' (Agrégé)')
        END AS market_name,
        CASE 
            WHEN source = 'WFP' THEN 
                CASE 
                    WHEN REGEXP_REPLACE(indicator, '\s+retail price \(WFP\)$', '') = 'Sorghum' THEN 'Sorghum (red)'
                    ELSE REGEXP_REPLACE(indicator, '\s+retail price \(WFP\)$', '')
                END
            ELSE REGEXP_REPLACE(SPLIT_PART(indicator, ' - ', 1), '\s+price\s+\(retail\)$', '')
        END AS raw_commodity,
        is_flagged_outlier,
        score_qualite,
        date_publication
    FROM base_markets
)
SELECT
    id,
    source,
    month_date,
    price_value,
    unit_clean,
    province,
    market_name,
    CASE raw_commodity
        WHEN 'Millet (Pearl)' THEN 'Millet'
        WHEN 'Sorghum (Red)' THEN 'Sorghum (red)'
        WHEN 'Maize (Corn)' THEN 'Maize (white)'
        WHEN 'Maize Grain (White)' THEN 'Maize (white)'
        WHEN 'Rice (5% Broken)' THEN 'Rice (imported)'
        ELSE raw_commodity
    END AS commodity_std,
    is_flagged_outlier,
    score_qualite,
    date_publication
FROM standardized;