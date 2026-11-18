# FreeData.AI — Release Management & Quality Assurance

## 1. Semantic Versioning & Environments
- **Versioning**: `MAJOR.MINOR.PATCH` (current API version: `1.2.0`).
- **Environments**:
  - `development`: local `.venv` + SQLite, `REQUIRE_SIGNED_USER_AUTH=0`, `ALLOW_LOCALHOST_CORS=1`.
  - `staging`: Render preview + Firebase Hosting preview channel (`staging`), executing full `pytest` + `flutter test` + migration dry-run.
  - `production`: Render (`render.yaml`) + Firebase Hosting (`build/web`), `REQUIRE_SIGNED_USER_AUTH=1`, `ALLOW_LOCALHOST_CORS=0`, `ENABLE_DOCS=0`.

## 2. Release Acceptance Criteria (Blocking Gates)
A release is **blocked** from production if any of the following fail:
1. Security & RBAC tests (`tests/test_security_hardening.py`, `tests/test_admin_dashboard.py`)
2. Release Gate 10-step E2E journeys & AI evaluation (`tests/test_release_gate.py`)
3. Report QA validator & financial consistency (`tests/test_phase4_qa_validator.py`, `tests/test_business_engine.py`)
4. Monetization & atomic quota tests (`tests/test_monetization.py`)
5. Flutter static analysis, tests, and release web build (`flutter analyze --no-fatal-infos`, `flutter test`, `flutter build web --release`)
6. Database migration verification (`sql/01`–`sql/12`).

## 3. Post-Deployment Verification & Rollback
1. Verify `GET /api/v1/health` returns `status == "ok"` and valid `data_freshness`.
2. Verify `GET /api/v1/billing/plans` and `GET /api/v1/products`.
3. Rollback on failure: `git revert` + `git push origin main` (Render) and `firebase hosting:rollback`.

