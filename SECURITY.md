# FreeData.AI — Security Architecture

## Authentication & Authorization
- **PRO Endpoints** (`/api/v1/reports/market-study*`, `/api/v1/reports/jobs*`): Require valid `X-Premium-Key` checked with constant-time comparison (`hmac.compare_digest`).
- **Project Endpoints** (`/api/v1/projects*`): Require `_require_project_owner()` (`X-User-Id` >= 3 chars or SHA-256 hash of a valid `X-Premium-Key`). Missing credentials return `401 Unauthorized`.
- **Admin Endpoints** (`/api/v1/refresh`, `/api/v1/metrics`, `/api/v1/diag/client-ip`): Protected by `X-Admin-Token` (`ADMIN_TOKEN`).

## Data Isolation & Database Security
- Every `ProjectStore` query filters strictly by `WHERE owner_id = ?`. Cross-user reads, updates, deletions, or PDF downloads return `404`.
- Supabase migration [10_projects_and_study_versions.sql](file:///d:/freedata-ai/sql/10_projects_and_study_versions.sql) enables **Row Level Security (RLS)** (`auth.uid()::text = owner_id`) and revokes `anon` access.
- Premium Gold tables are locked via [09_lock_premium_tables_rls.sql](file:///d:/freedata-ai/sql/09_lock_premium_tables_rls.sql).

## Input Validation, Rate Limiting & Secrets
- Request bodies are bounded by `limit_body_size` (`411`/`413`) and Pydantic schemas (`ChatRequest.message` <= 4000 chars, `MarketStudyRequest` bounds).
- `StudyContext._strip_sensitive_keys()` strips any credential-like keys (`api_key`, `token`, `password`, `x_premium_key`) before serialization.
- Rate limiting (`_chat_rate_limit_dependency`, `_data_rate_limit_dependency`, `_admin_rate_limit_dependency`) supports Upstash Redis or in-memory fallback.
- PDF artifacts are stored outside public static paths (`data/artifacts/<owner_hash>/`) and served only after ownership verification.

