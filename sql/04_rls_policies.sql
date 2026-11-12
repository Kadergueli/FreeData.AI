-- ============================================================================
-- FreeData.AI | Sécurité : Row Level Security sur les tables Gold
--
-- Effet : la clé publique (anon) peut LIRE les tables Gold mais pas les modifier.
-- La clé service_role (script mensuel) contourne le RLS et garde l'écriture.
--
-- Ordre conseillé en production :
--   1. Exécuter ce fichier (l'API continue de fonctionner, avec n'importe quelle clé).
--   2. Sur Render, définir SUPABASE_KEY = clé publique (anon / publishable)
--      et retirer toute clé service_role de l'environnement de l'API.
--   3. Garder SUPABASE_SERVICE_ROLE_KEY uniquement là où tourne update_predictions.py.
-- ============================================================================

ALTER TABLE public.table_ml_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.table_ml_credit_passport ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS gold_forecasts_public_read ON public.table_ml_forecasts;
CREATE POLICY gold_forecasts_public_read
    ON public.table_ml_forecasts
    FOR SELECT TO anon, authenticated
    USING (true);

DROP POLICY IF EXISTS gold_passport_public_read ON public.table_ml_credit_passport;
CREATE POLICY gold_passport_public_read
    ON public.table_ml_credit_passport
    FOR SELECT TO anon, authenticated
    USING (true);

-- Aucune politique INSERT/UPDATE/DELETE pour anon/authenticated : écriture refusée.
