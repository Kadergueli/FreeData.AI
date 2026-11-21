-- ============================================================================
-- FreeData.AI | Évaluations de terrain Agronome PRO — schéma PRIVÉ freedata_app (jamais exposé par PostgREST)
-- L'API crée cette table elle-même au démarrage ; ce fichier la documente et permet de l'appliquer à la main.
-- Mesures de sol = données privées du client : aucune lecture par anon/authenticated, aucune table publique,
-- aucun modèle global, aucun scope ml_benchmark (ALLOWED_DATASET_SCOPES = ('platform_public',)).
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS freedata_app;
CREATE TABLE IF NOT EXISTS freedata_app.agro_field_assessments (
    assessment_id TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL,
    hub           TEXT NOT NULL,
    title         TEXT NOT NULL,
    downgraded    INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agro_assess_owner ON freedata_app.agro_field_assessments (owner_id, created_at DESC);
ALTER TABLE freedata_app.agro_field_assessments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON freedata_app.agro_field_assessments FROM PUBLIC, anon, authenticated;
-- Aucune politique pour anon/authenticated : accès exclusivement via l'API (rôle serveur), filtré par owner_id.
