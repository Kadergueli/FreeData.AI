-- ============================================================================
-- FreeData.AI | RAG : base documentaire vectorielle (pgvector)
--
-- ÉTAT ACTUEL : aucun PDF n'est encore importé. Ce fichier ne crée que l'infrastructure.
-- Tant que rag_chunks est vide, match_chunks() renvoie 0 ligne : l'API doit alors répondre
-- avec les seules données chiffrées (tables Gold), sans citer de source documentaire.
-- Les PDF pourront être ajoutés plus tard (scripts/build_vector_store.py) sans modifier ce schéma.
--
-- MODÈLE DE SÉCURITÉ
--   * Lecture publique (anon, authenticated) limitée aux documents où redistribution_ok = true.
--   * AUCUNE écriture pour anon/authenticated : seul le script hors ligne (service_role) écrit.
--   * match_chunks : SECURITY INVOKER, search_path fixé, 10 résultats maximum.
--
-- DIMENSION DES EMBEDDINGS : 1024 (mistral-embed). À CONFIRMER dans la documentation Mistral
-- avant le premier import : changer de modèle plus tard oblige à recalculer tous les vecteurs.
--
-- Idempotent : peut être relancé sans erreur.
-- ============================================================================

-- 1. Extension (schéma "extensions", convention Supabase)
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- 2. Un enregistrement par document source (PDF)
CREATE TABLE IF NOT EXISTS public.rag_documents (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title             TEXT        NOT NULL,
    publisher         TEXT        NOT NULL,                    -- PAM, FEWS NET, INSEED...
    published_on      DATE,
    source_url        TEXT,
    language          TEXT        NOT NULL DEFAULT 'fr' CHECK (language IN ('fr', 'ar', 'en')),
    license           TEXT,                                    -- conditions de réutilisation, telles que publiées
    -- Un extrait n'est JAMAIS servi au public tant que ce drapeau n'est pas passé à TRUE à la main.
    redistribution_ok BOOLEAN     NOT NULL DEFAULT FALSE,
    file_sha256       TEXT        UNIQUE,                      -- évite d'importer deux fois le même fichier
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Un enregistrement par extrait (chunk) de document
CREATE TABLE IF NOT EXISTS public.rag_chunks (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   BIGINT      NOT NULL REFERENCES public.rag_documents (id) ON DELETE CASCADE,
    chunk_index   INTEGER     NOT NULL CHECK (chunk_index >= 0),
    page          INTEGER     CHECK (page > 0),
    content       TEXT        NOT NULL CHECK (char_length(content) BETWEEN 1 AND 8000),
    content_hash  TEXT        NOT NULL,                        -- ne pas ré-embedder un extrait inchangé (quota API)
    embedding     extensions.vector(1024) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Permet de relancer l'import sans doublons (upsert).
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS rag_chunks_document_id_idx ON public.rag_chunks (document_id);

-- Recherche approximative par similarité cosinus. HNSW : aucun entraînement requis (contrairement à IVFFlat),
-- donc valable dès la table vide. Sur quelques milliers d'extraits, PostgreSQL peut aussi choisir un
-- balayage exact : c'est normal et correct.
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw_idx
    ON public.rag_chunks USING hnsw (embedding extensions.vector_cosine_ops);

COMMENT ON TABLE public.rag_documents IS 'Documents sources du RAG. Lecture publique uniquement si redistribution_ok.';
COMMENT ON TABLE public.rag_chunks    IS 'Extraits de documents et leurs embeddings (1024 dimensions).';

-- 4. Recherche : les N extraits les plus proches d'un vecteur de question
--    SECURITY INVOKER : s'exécute avec les droits (et le RLS) de l'appelant, jamais avec ceux du propriétaire.
--    search_path fixé : empêche le détournement par un objet portant le même nom dans un autre schéma.
--    Distance cosinus = opérateur <=> ; similarité = 1 - distance (1 = identique).
CREATE OR REPLACE FUNCTION public.match_chunks(
    query_embedding extensions.vector(1024),
    match_count     INTEGER DEFAULT 5
)
RETURNS TABLE (
    chunk_id     BIGINT,
    document_id  BIGINT,
    title        TEXT,
    publisher    TEXT,
    published_on DATE,
    source_url   TEXT,
    page         INTEGER,
    content      TEXT,
    similarity   DOUBLE PRECISION
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, extensions, pg_temp
AS $$
    SELECT c.id,
           d.id,
           d.title,
           d.publisher,
           d.published_on,
           d.source_url,
           c.page,
           c.content,
           (1 - (c.embedding <=> query_embedding))::DOUBLE PRECISION
    FROM public.rag_chunks c
    JOIN public.rag_documents d ON d.id = c.document_id
    WHERE d.redistribution_ok
    ORDER BY c.embedding <=> query_embedding
    -- Plafond imposé côté base : un client ne peut jamais demander plus de 10 extraits par appel.
    LIMIT LEAST(GREATEST(COALESCE(match_count, 5), 1), 10);
$$;

-- 5. Sécurité : RLS activé, lecture seule pour les rôles publics
ALTER TABLE public.rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chunks    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rag_documents_public_read ON public.rag_documents;
CREATE POLICY rag_documents_public_read
    ON public.rag_documents
    FOR SELECT TO anon, authenticated
    USING (redistribution_ok);

DROP POLICY IF EXISTS rag_chunks_public_read ON public.rag_chunks;
CREATE POLICY rag_chunks_public_read
    ON public.rag_chunks
    FOR SELECT TO anon, authenticated
    USING (EXISTS (
        SELECT 1 FROM public.rag_documents d
        WHERE d.id = rag_chunks.document_id AND d.redistribution_ok
    ));

-- Aucune politique INSERT/UPDATE/DELETE : écriture refusée. On retire AUSSI les droits eux-mêmes
-- (défense en profondeur : une politique créée par erreur ne suffirait pas à ouvrir l'écriture).
REVOKE ALL ON public.rag_documents, public.rag_chunks FROM anon, authenticated;
GRANT SELECT ON public.rag_documents, public.rag_chunks TO anon, authenticated;

-- Par défaut PostgreSQL autorise l'exécution à PUBLIC : on restreint explicitement.
REVOKE ALL ON FUNCTION public.match_chunks(extensions.vector, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.match_chunks(extensions.vector, INTEGER) TO anon, authenticated, service_role;
