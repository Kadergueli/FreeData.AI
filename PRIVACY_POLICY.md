# FreeData.AI — Privacy & Data Governance Notice

*Last updated: 2026-11-19*

This document describes the technical data processing, storage, and external AI provider integrations actually implemented in the FreeData.AI codebase.

## 1. Data Collected & Processing Purpose

- **Account & Authentication Data (`AuthStore`)**: Email address, optional display name, salted PBKDF2-SHA256 password hash, and account status (`active` / `suspended`) — used strictly for authentication (`Authorization: Bearer` signed tokens) and session revocation.
- **Projects, Conversations & Studies (`ProjectStore`, `ConversationStore`)**: Project names, descriptions, structured `StudyContext` (commodity, provinces, budget/transport assumptions, user instructions), chat threads (optional `projectId` / `projectName`), and versioned study JSON snapshots (`dossier_json`) — used to persist and resume user analyses across devices.
- **Private Uploaded Documents (`UserDocumentStore`)**:
  - Supported formats: `.pdf`, `.csv`, `.txt`, `.md`, `.json`.
  - **Raw binary files are NOT stored in the database**: uploaded PDFs are parsed in volatile memory (RAM) to extract text and immediately discarded (`raw_binary_stored: false`).
  - Only extracted text chunks (overlapping segments, capped per batch with explicit partial-indexing notice for long documents), compacted embedding vectors (4-decimal float precision), SHA-256 content hashes (for duplicate prevention), and metadata (`filename`, `size_bytes`, `chunks_count`, `project_id`) are persisted under the user's `owner_id`.
- **Generated PRO Market Study PDFs**:
  - On cloud PostgreSQL (Supabase), raw PDF binaries are **not** stored as `BLOB`/`BYTEA` in `study_artifacts`. PDFs are streamed directly to the user's device and regenerated on demand from the lightweight `dossier_json` snapshot when re-downloaded.
- **Usage Metering & Support (`SubscriptionStore`, `SupportFeedbackStore`)**: Operation counters (`daily_chat`, `daily_rag`, `monthly_pdf`, `daily_ml`), subscription/payment request references, support tickets, and feature ratings.

## 2. External Service Providers & Data Shared

When configured in the deployment environment, FreeData.AI interacts with the following external providers:

| Provider | Purpose | Exact Data Sent | What Is NOT Sent |
| :--- | :--- | :--- | :--- |
| **Jina AI (`EMBED_API_KEY` / `jina-embeddings-v3`)** | Semantic indexing of uploaded user documents and semantic matching of user chat queries against private document chunks. | Extracted text chunks from uploaded user documents (at upload time) and the user's chat query text (at retrieval time, only when the user has Jina-indexed documents and the query is not a simple greeting). | Account passwords, JWT tokens, email addresses, raw PDF binaries, or other users' documents. |
| **Groq (`LLM_API_KEY` / `LLM_CHAT_MODEL`)** | Natural-language synthesis and interpretation of grounded market data and top-K retrieved private document excerpts. | The user's chat message, up to 8 recent conversation messages (truncated to 500 chars each), deterministic market facts/calculations computed by FreeData.AI, `StudyContext`, and up to 3 compressed excerpts (`<= 440` chars each) from the user's own matching documents. | Account passwords, JWT tokens, raw full PDF files, or any other user's private data. |
| **Supabase PostgreSQL (`SUPABASE_DB_URL` / `SUPABASE_URL`)** | Primary cloud database for accounts, projects, synced conversations, document text chunks/embeddings, subscriptions, and read-only Gold market tables (`freedata_app` schema hardened with Row Level Security). | Structured application records isolated by `owner_id`. | Raw uploaded PDF binaries and raw generated PRO PDF binaries. |

- **Sovereign Fallback Behavior**: If Jina or Groq is unconfigured, unreachable, or rate-limited, FreeData.AI falls back to local hybrid BM25/hash retrieval (`local_hybrid_bm25`) and deterministic Python market responses without exposing API keys, stack traces, or private document contents in error responses.
- **Personal Information Minimization**: Users should avoid uploading unnecessary sensitive personal data (national ID numbers, medical records, unrelated private files). Documents are validated against FreeData.AI's professional domain scope and anti-injection filters before external embedding calls.

## 3. Data Isolation, Retention & User Controls

- **Strict Per-User & Per-Project Isolation**: Every query on projects, conversations, documents, and chunks filters by `owner_id` (and `project_id` when scoped to a project). Cross-user access and unauthorized `project_id` associations are rejected.
- **Project Deletion Lifecycle**: Deleting a project (`DELETE /api/v1/projects/{project_id}?confirm=true`) removes the project, its studies, and all private documents/chunks attached to that `project_id`.
- **User Privacy Controls**:
  - **View / Export personal data**: `GET /api/v1/privacy/export` (projects, conversations, document metadata, subscription/quotas).
  - **Delete a single uploaded document & its vectors**: `DELETE /api/v1/documents/{doc_id}` (immediately deletes both `user_documents` and all `user_document_chunks` / Jina vectors so deleted documents never appear in RAG retrieval).
  - **Delete a single generated study report**: `DELETE /api/v1/projects/{project_id}/studies/{study_id}?confirm=true`.
  - **Delete a single conversation**: `DELETE /api/v1/conversations/{conversation_id}`.
  - **Delete a project**: `DELETE /api/v1/projects/{project_id}?confirm=true` (deletes project, studies, and attached project documents/vectors; safely detaches associated conversations into general history so chat history is not silently lost).
  - **Purge workspace data**: `DELETE /api/v1/privacy/my-data?confirm=true` (deletes all projects, synced conversations, and private documents/vectors).
  - **Delete account permanently**: `POST /api/v1/auth/delete-account` (verifies password, deletes account, purges projects/conversations/documents, and revokes the active session token).

## 4. Logging, Retention, Backups & Known Limitations

- **Log Redaction & Minimization**: Error logs redact database passwords, Bearer tokens, and provider API keys (`redact_secrets`) and do not log raw passwords or private document bodies.
- **Retention**: User data is retained until deleted by the user (or suspended/purged by an authorized administrator). No automated background deletion destroys user data without explicit action.
- **Backups**: In local SQLite mode, `POST /api/v1/admin/backup` performs hot backups of core SQLite databases. In production cloud PostgreSQL mode, database backups and point-in-time recovery follow the Supabase project backup policy; deleted records may remain in provider-managed database snapshots until those snapshots expire.
- **Items Requiring Project Owner / Legal Confirmation**:
  1. Confirm Groq AI and Jina AI zero-data-retention / non-training API terms for the configured API accounts.
  2. Confirm Supabase region, backup retention window, and Data Processing Agreement (DPA).
  3. Confirm legal counsel review for Chad, CEMAC, and GDPR compliance before publishing as a formal legal policy.

## 5. Compliance Notice

This notice reflects technical privacy controls implemented in code and does **not** constitute formal legal certification. Production operators remain responsible for reviewing external provider data-processing agreements (Jina AI, Groq, Supabase, Render, Firebase) and applicable regional regulations (CEMAC, Chad, GDPR).
