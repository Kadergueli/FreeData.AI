-- Additive, idempotent migration: durable ML Model Registry in private schema `freedata_app`.
-- Survives Render container restarts, redeployments, and ephemeral disk wipes.

CREATE SCHEMA IF NOT EXISTS freedata_app;

CREATE TABLE IF NOT EXISTS freedata_app.ml_model_registry (
    entry_key TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    artifact_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ml_model_registry_model_version
    ON freedata_app.ml_model_registry (model_id, version);

ALTER TABLE freedata_app.ml_model_registry ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE freedata_app.ml_model_registry FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON TABLE freedata_app.ml_model_registry FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE freedata_app.ml_model_registry FROM authenticated;
    END IF;
END
$$;

