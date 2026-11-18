-- 10 — Persistent Projects, StudyContext, Conversations, Study Versions, QA & Artifacts with RLS.
-- Compatible with Supabase PostgreSQL (auth.uid()::text = owner_id).

CREATE TABLE IF NOT EXISTS public.projects (
    project_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_projects_owner_updated ON public.projects (owner_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_idempotency
    ON public.projects (owner_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.project_contexts (
    project_id TEXT PRIMARY KEY REFERENCES public.projects (project_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    study_context_json JSONB NOT NULL,
    context_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.project_conversations (
    conversation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects (project_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proj_conv_project ON public.project_conversations (project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.project_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES public.project_conversations (conversation_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proj_msg_conv ON public.project_messages (conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS public.studies (
    study_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects (project_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    commodity TEXT NOT NULL,
    origin_province TEXT NOT NULL,
    dest_province TEXT,
    latest_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studies_project ON public.studies (project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.study_versions (
    version_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL REFERENCES public.studies (study_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES public.projects (project_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    context_snapshot_json JSONB NOT NULL,
    data_snapshot_json JSONB NOT NULL,
    generation_params_json JSONB NOT NULL,
    dossier_json JSONB NOT NULL,
    validation_result_json JSONB NOT NULL,
    artifact_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (study_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_study_versions_study ON public.study_versions (study_id, version_number DESC);

-- Row Level Security (strict user-level isolation)
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.studies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_versions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.projects, public.project_contexts, public.project_conversations,
    public.project_messages, public.studies, public.study_versions FROM anon;

DO $$
DECLARE tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'projects', 'project_contexts', 'project_conversations',
        'project_messages', 'studies', 'study_versions'
    ]
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_owner_all ON public.%I', tbl, tbl);
        EXECUTE format(
            'CREATE POLICY %I_owner_all ON public.%I FOR ALL TO authenticated USING (auth.uid()::text = owner_id) WITH CHECK (auth.uid()::text = owner_id)',
            tbl, tbl
        );
    END LOOP;
END $$;

