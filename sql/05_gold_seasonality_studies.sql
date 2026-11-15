-- Famille A : études saisonnières (kind='seasonality') et bilans de fiabilité des prévisions par produit
-- (kind='track_record'), précalculés pour l'offre premium. Écrits par scripts/update_seasonality.py.
-- À appliquer par le propriétaire du projet : ne touche à aucune table existante.
CREATE TABLE IF NOT EXISTS public.table_ml_seasonality_studies (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT        NOT NULL DEFAULT 'seasonality',
    commodity_std TEXT        NOT NULL,
    province      TEXT        NOT NULL DEFAULT '',  -- '' = étude nationale du produit
    payload       JSONB       NOT NULL,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_seasonality_studies_scope
    ON public.table_ml_seasonality_studies (kind, commodity_std, province);  -- cible de l'upsert (on_conflict)

ALTER TABLE public.table_ml_seasonality_studies ENABLE ROW LEVEL SECURITY;

-- Lecture par l'API (clé anon). Les études sont dérivées de données publiques (WFP / FEWS NET) ;
-- le contrôle d'accès premium est appliqué par l'API (X-Premium-Key). Pour interdire aussi la lecture directe
-- via PostgREST, supprimer cette politique et faire lire l'API avec une clé serveur.
DROP POLICY IF EXISTS seasonality_studies_public_read ON public.table_ml_seasonality_studies;
CREATE POLICY seasonality_studies_public_read
    ON public.table_ml_seasonality_studies
    FOR SELECT TO anon, authenticated
    USING (true);
-- Aucune politique INSERT/UPDATE/DELETE : écriture réservée à la clé service_role.
