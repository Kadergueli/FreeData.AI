
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
