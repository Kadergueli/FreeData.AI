-- Additive, idempotent migration: domaine Agriculture (schéma privé freedata_app, RLS activée, aucun droit anon/authenticated).
-- Les données sont servies au public UNIQUEMENT via l'API (/api/v1/agro/*), jamais en accès direct à la base.
-- NB : l'application crée aussi ces tables au démarrage (CREATE TABLE IF NOT EXISTS) ; ce fichier sert de migration manuelle.

CREATE SCHEMA IF NOT EXISTS freedata_app;

CREATE TABLE IF NOT EXISTS freedata_app.table_agro_indicators (
    id INTEGER NOT NULL,
    sector TEXT NOT NULL DEFAULT 'agriculture',
    indicator TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL,
    reference_date TEXT NOT NULL,
    country_code TEXT NOT NULL DEFAULT 'TCD',
    region TEXT NOT NULL,
    source TEXT NOT NULL,
    license TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL,
    spatial_resolution TEXT NOT NULL,
    confidence_level TEXT NOT NULL,
    PRIMARY KEY (indicator, region, reference_date, source)
);

CREATE INDEX IF NOT EXISTS idx_agro_ind_region
    ON freedata_app.table_agro_indicators (region, indicator, reference_date);

-- Prévu pour l'étape P2 (Agronome PRO) : analyses de terrain PRIVÉES, isolées par propriétaire.
-- Isolation appliquée par l'API (filtre owner_id) + RLS sans politique : aucun accès direct possible.
CREATE TABLE IF NOT EXISTS freedata_app.table_agro_field_assessments (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    project_id TEXT,
    province_hub TEXT NOT NULL,
    gps_lat DOUBLE PRECISION,
    gps_lon DOUBLE PRECISION,
    area_hectares DOUBLE PRECISION,
    lab_soil_inputs TEXT NOT NULL DEFAULT '{}',
    agronomist_field_notes TEXT NOT NULL DEFAULT '',
    target_crops TEXT NOT NULL DEFAULT '[]',
    computed_scores TEXT NOT NULL DEFAULT '{}',
    report_verification_code TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agro_assess_owner
    ON freedata_app.table_agro_field_assessments (owner_id, created_at DESC);

ALTER TABLE freedata_app.table_agro_indicators ENABLE ROW LEVEL SECURITY;
ALTER TABLE freedata_app.table_agro_field_assessments ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE freedata_app.table_agro_indicators FROM PUBLIC;
REVOKE ALL ON TABLE freedata_app.table_agro_field_assessments FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON TABLE freedata_app.table_agro_indicators FROM anon;
        REVOKE ALL ON TABLE freedata_app.table_agro_field_assessments FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE freedata_app.table_agro_indicators FROM authenticated;
        REVOKE ALL ON TABLE freedata_app.table_agro_field_assessments FROM authenticated;
    END IF;
END
$$;

