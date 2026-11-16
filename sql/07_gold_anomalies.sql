-- Famille B : anomalies de prix (sauts, divergences entre marchés, séries figées ou arrêtées).
-- Écrites par scripts/update_anomalies.py. À appliquer par le propriétaire du projet : ne touche à aucune table existante.
CREATE TABLE IF NOT EXISTS public.table_ml_anomalies (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    province      TEXT        NOT NULL,
    market_name   TEXT        NOT NULL,
    commodity_std TEXT        NOT NULL,
    kind          TEXT        NOT NULL,   -- jump | divergence | jump+divergence | stale | stopped
    severity      TEXT        NOT NULL,   -- modérée | forte
    month         TEXT        NOT NULL,   -- 'YYYY-MM'
    value         DOUBLE PRECISION,
    reference     DOUBLE PRECISION,       -- prix attendu (mois précédent ou position habituelle parmi les pairs)
    change_pct    DOUBLE PRECISION,
    score         DOUBLE PRECISION,       -- score robuste (jump/divergence) ou nombre de mois (stale/stopped)
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_anomalies_scope
    ON public.table_ml_anomalies (source, province, market_name, commodity_std, month, kind);  -- cible de l'upsert

ALTER TABLE public.table_ml_anomalies ENABLE ROW LEVEL SECURITY;

-- Lecture par l'API (clé anon) : ce sont des signaux d'alerte dérivés de données publiques (WFP / FEWS NET).
DROP POLICY IF EXISTS anomalies_public_read ON public.table_ml_anomalies;
CREATE POLICY anomalies_public_read
    ON public.table_ml_anomalies
    FOR SELECT TO anon, authenticated
    USING (true);
-- Aucune politique INSERT/UPDATE/DELETE : écriture réservée à la clé service_role.
