-- 09 — Restreindre l'accès direct PostgREST aux tables Gold PRO/Premium.
--
-- Tables concernées :
--   - public.table_ml_seasonality_studies (études saisonnières & track_record)
--   - public.table_ml_anomalies           (détection d'anomalies & qualité)
--
-- Tables publiques conservées en lecture (inchangées) :
--   - public.table_ml_forecasts
--   - public.table_ml_credit_passport
--   - Tables de collecte FreeData.td (aucune modification)
--
-- Prérequis : l'API FastAPI doit disposer de SUPABASE_SERVICE_ROLE_KEY pour lire ces tables côté serveur
-- (`_fetch_gold_table(..., privileged=True)`), et vérifier X-Premium-Key avant de servir les clients.

ALTER TABLE public.table_ml_seasonality_studies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.table_ml_anomalies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS seasonality_studies_public_read ON public.table_ml_seasonality_studies;
DROP POLICY IF EXISTS anomalies_public_read ON public.table_ml_anomalies;

REVOKE SELECT ON public.table_ml_seasonality_studies FROM anon, authenticated;
REVOKE SELECT ON public.table_ml_anomalies FROM anon, authenticated;

-- Vérification : aucune politique SELECT pour anon/authenticated sur les 2 tables premium
SELECT schemaname, tablename, policyname, roles, cmd
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('table_ml_seasonality_studies', 'table_ml_anomalies');

-- ============================================================================
-- ROLLBACK SQL (à exécuter uniquement pour restaurer la lecture publique) :
-- ============================================================================
-- GRANT SELECT ON public.table_ml_seasonality_studies TO anon, authenticated;
-- GRANT SELECT ON public.table_ml_anomalies TO anon, authenticated;
-- CREATE POLICY seasonality_studies_public_read
--     ON public.table_ml_seasonality_studies FOR SELECT TO anon, authenticated USING (true);
-- CREATE POLICY anomalies_public_read
--     ON public.table_ml_anomalies FOR SELECT TO anon, authenticated USING (true);

