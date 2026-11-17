-- 08 — Retirer les droits d'ÉCRITURE aux rôles publics (anon, authenticated) sur le schéma public.
--
-- Constat (audit du 17/11/2026) : par défaut Supabase accorde INSERT/UPDATE/DELETE/TRUNCATE à anon et authenticated sur
-- toutes les tables ; seule la sécurité par ligne (RLS) les bloque. Une politique mal écrite ouvrirait l'écriture.
--
-- NE PAS APPLIQUER sans avoir vérifié qu'aucune autre application du projet n'écrit avec la clé anon ou un utilisateur connecté
-- (par ex. la plateforme de collecte : tables table_admins, table_admin_audit, table_harvest_runs...). Le rôle service_role et
-- le rôle postgres ne sont pas affectés : l'API de lecture, update_predictions, update_seasonality et update_anomalies
-- (clé service_role) continuent de fonctionner.

-- 1. Retrait des écritures sur tout l'existant
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- 2. Les futures tables ne les recevront pas non plus
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM anon, authenticated;

-- 3. Vérification : doit ne renvoyer AUCUNE ligne
SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
  AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE');

-- Retour arrière (si une application légitime en dépend) :
-- GRANT INSERT, UPDATE, DELETE ON <table> TO authenticated;   -- table par table, avec une politique RLS adaptée
