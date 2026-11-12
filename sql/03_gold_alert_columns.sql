-- ============================================================================
-- FreeData.AI | Migration : colonnes d'alerte sur table_ml_forecasts
-- À exécuter UNE FOIS sur une base Gold existante (idempotent).
-- Les valeurs sont remplies au prochain run de scripts/update_predictions.py ;
-- d'ici là l'API retombe sur l'ancienne approximation (et le signale dans /health).
-- ============================================================================

ALTER TABLE public.table_ml_forecasts
    ADD COLUMN IF NOT EXISTS predicted_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS deviation_pct DOUBLE PRECISION;
