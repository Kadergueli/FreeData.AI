# FreeData.AI — Deployment, Operations & Recovery

## Environment Variables
| Variable | Purpose | Required |
| :--- | :--- | :--- |
| `SUPABASE_URL` | Supabase project URL | Yes (prod) |
| `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | Read / privileged server key | Yes (prod) |
| `PREMIUM_API_KEYS` | Comma-separated PRO keys | Yes (PRO) |
| `ADMIN_TOKEN` | Token for `/api/v1/refresh` & `/api/v1/metrics` | Recommended |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_CHAT_MODEL` | LLM synthesis (OpenAI-compatible) | Optional |
| `FREEDATA_PROJECT_DB_PATH` | SQLite path (default `data/freedata_projects.db`) | Optional |
| `FREEDATA_ARTIFACTS_DIR` | PDF artifacts path (default `data/artifacts`) | Optional |
| `CORS_ORIGINS` | Allowed frontend origins | Yes (prod) |

## Database Migrations
Apply SQL scripts in order in Supabase SQL Editor:
`sql/01_silver_v_clean_markets.sql` → ... → `sql/09_lock_premium_tables_rls.sql` → `sql/10_projects_and_study_versions.sql` → `sql/11_subscriptions_and_usage_metering.sql` → `sql/12_admin_rbac_and_audit.sql`.

## Environments & CI/CD Workflow
- **Development**: Local `.venv` + `uvicorn api.server:app --reload`, `ALLOW_LOCALHOST_CORS=1`, `REQUIRE_SIGNED_USER_AUTH=0`.
- **Staging**: Render preview/staging branch + Firebase Hosting preview channel (`firebase hosting:channel:deploy staging`), running full `pytest` + `flutter test` before promotion.
- **Production**: Render Web Service ([render.yaml](render.yaml)) + Firebase Hosting (`build/web`), `ALLOW_LOCALHOST_CORS=0`, `ENABLE_DOCS=0`, `REQUIRE_SIGNED_USER_AUTH=1`.

## Backup & Disaster Recovery (RPO / RTO)
- **RPO**: <= 24 hours (daily automated SQLite hot backup via `POST /api/v1/admin/backup` / `src/backup.py` + Supabase daily PITR/snapshots).
- **RTO**: <= 30 minutes (restore latest verified `.db` backup + `PRAGMA integrity_check`, redeploy Render commit, verify `GET /api/v1/health`).
- **Retention**: 30 daily backups, 12 monthly snapshots. Restoration must be verified with `verify_sqlite_integrity()`.

## Cost & Infrastructure Scenarios (Planning Estimates)
1. **Low-cost initial deployment** (Free/Starter): Render Starter + Supabase Free + Firebase Hosting Spark + Groq/open LLM API (~$0–$25/month).
2. **Growing user base** (1,000+ MAU): Render Standard + persistent disk for SQLite/artifacts + Supabase Pro + Upstash Redis for shared rate limits (~$45–$100/month + LLM token usage).
3. **Larger production environment** (10,000+ MAU): Multi-worker Render/container autoscaling + Supabase PostgreSQL for `sql/10`–`12` + dedicated background worker for PDF/ML jobs (~$150+/month + LLM token usage).

## Deployment Commands
```powershell
# Backend (Render auto-deploys on push to main)
git push origin main

# Frontend (Firebase Hosting)
cd frontend_flutter
flutter analyze --no-fatal-infos
flutter test
flutter build web --release --dart-define=API_BASE_URL=https://freedata-ai.onrender.com
firebase deploy --only hosting
```

## Health Checks, Backup & Rollback
- **Health**: `GET /api/v1/health` (checks `status == "ok"`, `series_count`, `data_freshness`).
- **Metrics**: `GET /api/v1/metrics` (with `X-Admin-Token`: `total_requests`, `error_4xx`, `error_5xx`, `qa_blocked`, `avg_latency_ms`).
- **Backup**: Back up `FREEDATA_PROJECT_DB_PATH` (SQLite `.backup` or persistent disk snapshot) and `FREEDATA_ARTIFACTS_DIR` daily.
- **Rollback**: Redeploy previous Render commit (`git revert` + `git push origin main`) and `firebase hosting:rollback` if needed.

