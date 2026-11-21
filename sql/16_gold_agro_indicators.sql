-- ============================================================================
-- FreeData.AI | Gold public : indicateurs agro-climatiques (NASA POWER par hub + Banque mondiale national)
-- Zéro donnée inventée : provenance obligatoire sur chaque ligne (source, licence, date, résolution, confiance).
-- Pas de colonne source_url (champ vide interdit). Pas de température ni de précipitations en V1.
-- Idempotent, additif. Lecture publique (RLS), écriture réservée au rôle service_role.
-- Les évaluations de terrain PRO (sols de l'agronome) ne vivent PAS ici : schéma privé freedata_app (sql/17).
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.table_agro_indicators (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sector              TEXT NOT NULL DEFAULT 'agriculture' CHECK (sector = 'agriculture'),
    indicator           TEXT NOT NULL,
    value               DOUBLE PRECISION NOT NULL,
    unit                TEXT NOT NULL,
    reference_date      DATE NOT NULL,
    country_code        TEXT NOT NULL DEFAULT 'TCD' CHECK (country_code = 'TCD'),
    region              TEXT NOT NULL,
    source              TEXT NOT NULL,
    license             TEXT NOT NULL CHECK (license IN ('Public Domain (U.S. Government / NASA)', 'CC BY 4.0')),
    notes               TEXT,
    collected_at        TIMESTAMPTZ NOT NULL,
    spatial_resolution  TEXT NOT NULL CHECK (spatial_resolution IN ('regional_city_hub', 'national')),
    confidence_level    TEXT NOT NULL CHECK (confidence_level IN ('Satellite_Modeled_Regional', 'Official_Macro_National')),
    CONSTRAINT agro_ind_unique UNIQUE (indicator, region, reference_date, source),
    CONSTRAINT agro_ind_indicator_v1 CHECK (indicator IN (
        'root_zone_soil_wetness', 'surface_soil_wetness', 'photosynthetically_active_radiation',
        'cereal_production', 'cereal_yield', 'crop_production_index', 'food_production_index',
        'agricultural_land_area', 'agricultural_land_share', 'arable_land_share', 'forest_area_share',
        'fertilizer_consumption', 'agriculture_value_added_pct_gdp', 'employment_in_agriculture'))
);
CREATE INDEX IF NOT EXISTS idx_agro_ind_region_ind ON public.table_agro_indicators (region, indicator, reference_date DESC);

ALTER TABLE public.table_agro_indicators ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agro_indicators_public_read ON public.table_agro_indicators;
CREATE POLICY agro_indicators_public_read ON public.table_agro_indicators FOR SELECT TO anon, authenticated USING (true);
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.table_agro_indicators FROM anon, authenticated;
