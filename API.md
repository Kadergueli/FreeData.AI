# FreeData.AI — REST API Reference

Base URL (production): `https://freedata-ai.onrender.com`

## Public & Market Data
- `GET /api/v1/health` — Service status, backend mode, dataset freshness, and series counts.
- `GET /api/v1/metadata` — Tracked products, provinces, markets, sources, and periods.
- `GET /api/v1/forecasts?province=&commodity=&limit=100` — Forecast records and 80% intervals.

## Chat Engine
- `POST /api/v1/chat`
  - Body: `{"message": "...", "history": [...], "tier": "free|premium", "study_context": {...}}`
  - Headers: `X-Premium-Key` (required when `tier == "premium"`)
  - Returns: `reply`, `intent`, `entities`, `sources`, `chart`, `summary`, `client_state` (includes `study_context`), `follow_ups`.

## PRO Market Studies & Async Jobs (Requires `X-Premium-Key`)
- `POST /api/v1/reports/market-study` — Returns structured JSON dossier + `validation` QA report.
- `POST /api/v1/reports/market-study/pdf` — Returns binary PDF (`200`, header `X-Report-QA-Status`) or `422` if QA blocks delivery.
- `POST /api/v1/reports/jobs` *(also requires `X-User-Id` or valid `X-Premium-Key`)* — Queues background PDF generation; returns `job_id`.
- `GET /api/v1/reports/jobs/{job_id}` — Poll job `status`, `progress_pct`, `validation`, `study_id`, `version_number`.
- `GET /api/v1/reports/jobs/{job_id}/pdf` — Download completed job PDF.

## Persistent Projects & Versions (Requires `X-User-Id` or valid `X-Premium-Key`)
- `POST /api/v1/projects` — Create project (`name`, `description`, `study_context`, `idempotency_key`).
- `GET /api/v1/projects?include_archived=false&limit=50&offset=0` — Paginated project list.
- `GET /api/v1/projects/{project_id}` — Project details, `study_context`, conversations, studies.
- `PATCH /api/v1/projects/{project_id}` — Rename, update description/context, archive/restore.
- `DELETE /api/v1/projects/{project_id}?confirm=true` — Safe delete.
- `POST /api/v1/projects/{project_id}/conversations` & `/messages` — Persist conversations and context updates.
- `POST /api/v1/projects/{project_id}/studies` — Generate & store a new study version (`v1`, `v2`, ...).
- `GET /api/v1/projects/{project_id}/studies/{study_id}/versions` — List versions.
- `GET /api/v1/projects/{project_id}/studies/{study_id}/compare?v1=1&v2=2` — Compare two versions.
- `GET /api/v1/projects/{project_id}/studies/{study_id}/versions/{version_number}/pdf` — Download version PDF.

## Admin & Observability (`X-Admin-Token`)
- `GET /api/v1/metrics` — Aggregate request counts, 4xx/5xx errors, QA blocks, and average latency.
- `POST /api/v1/refresh` — Reload Gold tables in memory.

