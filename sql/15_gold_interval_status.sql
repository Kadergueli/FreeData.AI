-- ============================================================================
-- FreeData.AI | Migration : statut de calibration de l'intervalle (table_ml_forecasts.interval_status)
-- 'calibrated_80'        = intervalle à 80 % calibré hors-échantillon
-- 'wide_reduced'         = calibré mais très large (peu exploitable pour décider)
-- 'insufficient_history' = historique insuffisant pour calibrer
-- 'uncalibrated'         = valeur par défaut des lignes produites avant cette migration
-- Idempotent. À appliquer AVANT de relancer scripts/update_predictions.py.
-- ============================================================================
ALTER TABLE public.table_ml_forecasts
    ADD COLUMN IF NOT EXISTS interval_status TEXT NOT NULL DEFAULT 'uncalibrated';
ALTER TABLE public.table_ml_forecasts DROP CONSTRAINT IF EXISTS table_ml_forecasts_interval_status_check;
ALTER TABLE public.table_ml_forecasts
    ADD CONSTRAINT table_ml_forecasts_interval_status_check
    CHECK (interval_status IN ('calibrated_80', 'wide_reduced', 'insufficient_history', 'uncalibrated'));
