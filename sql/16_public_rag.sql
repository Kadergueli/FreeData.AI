-- FreeData.AI — public document RAG index (Jina Embeddings v3, 1024 dimensions).
-- Apply once in Supabase SQL Editor. This schema stores only explicitly approved public/reference documents.
-- Private user uploads remain in the isolated freedata_app document store and are NOT exposed here.

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
SET search_path = public, extensions;

CREATE TABLE IF NOT EXISTS public.rag_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    titre text NOT NULL,
    editeur text NOT NULL,
    date_publication date,
    url_source text,
    langue text NOT NULL DEFAULT 'fr',
    licence text NOT NULL DEFAULT 'Usage interne uniquement',
    redistribution_ok boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Matches the upsert conflict target used by scripts/build_vector_store.py.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_documents_identity
    ON public.rag_documents (titre, editeur, date_publication);

CREATE TABLE IF NOT EXISTS public.rag_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES public.rag_documents(id) ON DELETE CASCADE,
    page integer NOT NULL CHECK (page > 0),
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    content text NOT NULL CHECK (length(trim(content)) > 0),
    content_hash char(64) NOT NULL,
    embedding vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
    ON public.rag_chunks (document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_cosine
    ON public.rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE public.rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rag_public_approved_documents_read ON public.rag_documents;
CREATE POLICY rag_public_approved_documents_read
    ON public.rag_documents
    FOR SELECT TO anon, authenticated
    USING (redistribution_ok = true);

DROP POLICY IF EXISTS rag_public_approved_chunks_read ON public.rag_chunks;
CREATE POLICY rag_public_approved_chunks_read
    ON public.rag_chunks
    FOR SELECT TO anon, authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.rag_documents d
            WHERE d.id = rag_chunks.document_id
              AND d.redistribution_ok = true
        )
    );

REVOKE ALL ON public.rag_documents, public.rag_chunks FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.rag_documents, public.rag_chunks
    FROM anon, authenticated;
GRANT SELECT ON public.rag_documents, public.rag_chunks TO anon, authenticated;
GRANT ALL PRIVILEGES ON public.rag_documents, public.rag_chunks TO service_role;

CREATE OR REPLACE FUNCTION public.match_chunks(
    query_embedding vector(1024),
    match_count integer DEFAULT 3
)
RETURNS TABLE (
    titre text,
    editeur text,
    page integer,
    url_source text,
    content text,
    similarity double precision
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, extensions
AS $$
    SELECT
        d.titre,
        d.editeur,
        c.page,
        d.url_source,
        c.content,
        (1 - (c.embedding <=> query_embedding))::double precision AS similarity
    FROM public.rag_chunks c
    JOIN public.rag_documents d ON d.id = c.document_id
    WHERE d.redistribution_ok = true
      AND c.embedding IS NOT NULL
    ORDER BY c.embedding <=> query_embedding
    LIMIT LEAST(GREATEST(COALESCE(match_count, 3), 1), 20);
$$;

REVOKE ALL ON FUNCTION public.match_chunks(vector, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.match_chunks(vector, integer) TO anon, authenticated, service_role;

COMMENT ON TABLE public.rag_documents IS
    'Public/reference RAG documents. redistribution_ok must be true before any chunk is retrievable.';
COMMENT ON TABLE public.rag_chunks IS
    'Text chunks and Jina v3 1024-dimensional embeddings for approved public/reference documents.';
