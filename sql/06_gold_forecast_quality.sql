-- ============================================================================
-- FreeData.AI | Migration : qualité de la prévision (table_ml_forecasts.forecast_quality)
-- 'standard' = modèle complet ; 'reduced' = dernier relevé après un trou, prévision simplifiée à intervalle élargi.
-- Idempotent. Les lignes existantes sont 'standard' (produites avant cette correction).
-- ============================================================================
ALTER TABLE public.table_ml_forecasts
    ADD COLUMN IF NOT EXISTS forecast_quality TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE public.table_ml_forecasts DROP CONSTRAINT IF EXISTS table_ml_forecasts_quality_check;
ALTER TABLE public.table_ml_forecasts
    ADD CONSTRAINT table_ml_forecasts_quality_check CHECK (forecast_quality IN ('standard', 'reduced'));
