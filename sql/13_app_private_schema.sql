-- FreeData.AI — schéma privé des données applicatives (projets, abonnements, support, admin).
-- L'API crée elle-même ses tables au démarrage quand SUPABASE_DB_URL est défini ; ce fichier documente
-- (et permet d'appliquer à la main) la mise en place du schéma et son verrouillage. Idempotent, additif.
--
-- Le schéma n'est PAS exposé par l'API REST (PostgREST n'expose que « public » par défaut) :
-- ne l'ajoutez jamais à « Exposed schemas » dans Supabase > Settings > API.

CREATE SCHEMA IF NOT EXISTS freedata_app;

REVOKE ALL ON SCHEMA freedata_app FROM PUBLIC;
REVOKE ALL ON SCHEMA freedata_app FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA freedata_app REVOKE ALL ON TABLES FROM anon, authenticated;

-- Après le premier démarrage de l'API (tables créées), vérifier :
--   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'freedata_app';   -- rowsecurity = true partout
--   SELECT has_schema_privilege('anon', 'freedata_app', 'USAGE');                    -- false
