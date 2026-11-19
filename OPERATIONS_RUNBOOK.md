# FreeData.AI — Production Operations Runbook

## 1. Infrastructure Architecture

| Layer | Current Production Component | Purpose | Single Point of Failure / Mitigation |
| :--- | :--- | :--- | :--- |
| **Backend API & AI Engine** | Render Web Service (`render.yaml`, `starter` plan, Python 3.12, Uvicorn) | FastAPI API, Multi-Domain Router, NumPy/Pandas ML Engine, Hybrid RAG, PDF ReportLab | Single instance + ephemeral local disk → use Supabase PostgreSQL (`SUPABASE_DB_URL`) for all persistent user/project/admin/document state |
| **Frontend Web** | Firebase Hosting (`freedata-ai.web.app`) | Flutter Web SPA (User Workspace + `/#/admin` AI Control Center) | Global CDN; zero secrets in bundle (verified by CI `test_api_contracts.py`) |
| **Primary Database & Vectors** | Supabase PostgreSQL (Session Pooler IPv4, private schema `freedata_app`) | Users, auth sessions, projects, conversations, documents, embeddings, subscriptions, admin audit logs | Managed Postgres with automated daily snapshots; fallback to local SQLite in dev/test only |
| **External LLM Provider** | Groq (`llama-3.3-70b-versatile`) | Conversational synthesis & structured routing | Outage degrades gracefully to deterministic ML/RAG output without crashing API |
| **External Embeddings** | Jina AI (`jina-embeddings-v3`, 1024 dim) | Semantic vector embeddings for RAG & private documents | Outage degrades gracefully to BM25/hashed local lexical search |
| **ML Model Storage** | Versioned JSON artifacts (`data/models/*_v*.json`) + `registry_index.json` | Pure NumPy/Pandas models with lazy LRU memory cache (`max_loaded_models=4`) | CPU-only (no GPU needed); back up via `backup_model_artifacts()` |
| **Background Processing** | In-process `ReportJobManager` (`ThreadPoolExecutor`, `max_workers=2`) | Long-running PDF report generation | Bounded pool, idempotency deduplication, timeout enforcement, retry policy |
| **CI/CD & Scheduled Tasks** | GitHub Actions (`ci.yml`, `freshness_monitor.yml`, `publish_pipeline.yml`) | Automated tests, security/contract gates, `pip-audit`, Flutter build, data freshness | Failed tests block release; no automatic deployment of experimental ML models |

---

## 2. Deployment Environments

| Environment | `FREEDATA_ENV` | Database | Auth Policy | CORS / Docs |
| :--- | :--- | :--- | :--- | :--- |
| **Development** | `development` | Local SQLite + CSV | `REQUIRE_SIGNED_USER_AUTH=0` | `ALLOW_LOCALHOST_CORS=1`, `ENABLE_DOCS=1` |
| **Testing (CI)** | `test` | Ephemeral `tmp_path` SQLite | Mocked/signed JWTs | Isolated per test |
| **Staging** | `staging` | Dedicated staging Supabase project | `REQUIRE_SIGNED_USER_AUTH=1` | Staging origin only, `ENABLE_DOCS=0` |
| **Production** | `production` | Production Supabase PostgreSQL (Session Pooler) | `REQUIRE_SIGNED_USER_AUTH=1`, `AUTH_SECRET` >= 32 chars | `ALLOW_LOCALHOST_CORS=0`, `ENABLE_DOCS=0`, `ALLOWED_ORIGINS` strictly production |

**Secrets Rule:** Never commit `.env`. Never put `ADMIN_TOKEN`, `SUPABASE_SERVICE_ROLE_KEY`, `AUTH_SECRET`, `LLM_API_KEY`, or `EMBED_API_KEY` in Flutter builds (`frontend_flutter/`).

---

## 3. Deployment Procedure

1. **Local Pre-Flight Gate:**
   ```powershell
   D:\freedata-ai\.venv\Scripts\python.exe -m pytest -q
   cd frontend_flutter
   dart format --output=none --set-exit-if-changed lib test
   flutter analyze --no-fatal-infos
   flutter test
   flutter build web --release
   ```
2. **Push & CI Verification:** Push to `main` (or open PR). All 3 GitHub Actions jobs (`Python (Tests & Audit)`, `Flutter Web`, `Contrats API, Sécurité Frontend & Configs`) must be green.
3. **Backend Deployment (Render):** Deploy only after CI passes. Verify `GET https://freedata-ai.onrender.com/api/v1/health` returns `200 OK`.
4. **Frontend Deployment (Firebase Hosting):**
   ```powershell
   cd frontend_flutter
   firebase deploy --only hosting
   ```
5. **Post-Deploy Verification:** Open `/#/admin`, authenticate with `X-Admin-Token`, click **"Tester connectivité"**, and confirm zero `HIGH` operational warnings.

---

## 4. Database Migrations

- All SQL migrations live in `sql/` and must be **backward-compatible** (additive columns/indexes, `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).
- Always apply additive SQL migrations to Supabase **before** deploying backend code that depends on them.
- Never run destructive `DROP TABLE` / `TRUNCATE` statements without an explicit verified snapshot and user approval.

---

## 5. Backup & Recovery Strategy

### Recovery Objectives
- **RPO (Recovery Point Objective):** ≤ 24 hours (Supabase automated daily backups + on-demand SQLite/artifact snapshots via `POST /api/v1/admin/backup` before releases).
- **RTO (Recovery Time Objective):** ≤ 30 minutes (Render rollback + Supabase Point-in-Time / snapshot restore).

### Procedures
- **Database Backup (SQLite dev/fallback):** `src/backup.py` → `backup_all_databases()` uses SQLite online hot-backup (`sqlite3.Connection.backup`) + `PRAGMA integrity_check` + `prune_old_backups(keep_last=14)`.
- **Database Restore (SQLite):** `restore_sqlite_file(backup_path, target_path)` validates `PRAGMA integrity_check` before overwriting target.
- **Supabase PostgreSQL Restore:** Use Supabase Dashboard → Database → Backups → Restore to new project or Point-in-Time Recovery (PITR). Verify row counts before switching `SUPABASE_DB_URL`.
- **ML Model Artifacts Backup/Restore:** `backup_model_artifacts(Path("data/models"), backup_root)` copies `registry_index.json` + `*_v*.json` with a `manifest.sha256.json` checksum file.

---

## 6. ML Model Deployment & Rollback

1. **Lifecycle Gate:** Models progress through `REGISTERED → TRAINING → TRAINED → EVALUATION → APPROVED → DEPLOYED`. Experimental or `TRAINED` models are **never** served in production (`ModelRegistry.select_model()` strictly requires `DEPLOYED` + `enabled=True` + `is_active_production=True`).
2. **Memory Management:** Artifacts stay on disk and are lazy-loaded via a bounded LRU cache (`max_loaded_models=4`). No GPU is required for current NumPy/Pandas workloads.
3. **Promotion:** `POST /api/v1/admin/ai/models/{model_id}/status` with `lifecycle_status="DEPLOYED"`, `set_active=true` (requires `manage_models` permission; logged in admin audit trail).
4. **Instant Rollback:** `POST /api/v1/admin/ai/models/{model_id}/rollback` with `{"target_version": <prev_v>, "reason": "..."}` — atomically demotes the faulty version to `DEPRECATED`, evicts it from RAM, and restores the target version.

---

## 7. Background Job Management

- Long PDF generation runs asynchronously in `ReportJobManager` (`max_workers=2`, `default_timeout_seconds=120.0`).
- **Duplicate Prevention:** Passing `idempotency_key` reuses an already `queued`/`running` job for the same owner.
- **Retries:** Failed jobs can be retried via `POST /api/v1/reports/jobs/{job_id}/retry` up to `max_retries`.
- **Monitoring:** Admin overview exposes `background_jobs_summary` (`queued`, `running`, `completed`, `failed`, `max_workers`).

---

## 8. Incident Response

| Incident | Automated Platform Behavior | Operator Action |
| :--- | :--- | :--- |
| **Groq LLM Outage / 429** | Health probe marks `DEGRADED`/`UNAVAILABLE`; deterministic ML & RAG tools continue answering | Check Admin Console → Live Probe; verify Groq status page & key quota |
| **Jina Embeddings Outage** | Health probe marks `DEGRADED`/`UNAVAILABLE`; RAG falls back to local lexical/BM25 retrieval | Verify `EMBED_API_KEY` & Jina quota; re-index affected docs once restored |
| **Supabase PG Outage** | Health probe marks `UNAVAILABLE`; `operational_warnings` raises `SUPABASE_UNAVAILABLE` | Check Supabase dashboard & Session Pooler connection limits (`DB_POOL_MAX`) |
| **ML Model Load Failure** | Raises `FileNotFoundError` / `LookupError`; LLM never fabricates ML results | Roll back via `POST /api/v1/admin/ai/models/{model_id}/rollback` |
| **High 5xx Rate (>5%)** | `HIGH_5XX_RATE` warning raised; `recent_errors` captures `request_id` correlation IDs | Correlate `request_id` in Render logs; roll back deployment if regression |

---

## 9. Application Rollback Procedure

1. **Backend (Render):** Render Dashboard → `freedata-ai-api` → Deploys → click **Rollback** on the last known-good commit.
2. **Frontend (Firebase Hosting):** Firebase Console → Hosting → Release History → **Rollback** to previous release.
3. **ML Models:** Call `POST /api/v1/admin/ai/models/{model_id}/rollback` for any recently promoted model version.
4. **Verify:** Check `/api/v1/health` and Admin Console live probe.

