# FreeData.AI — Documentation Index & Maintenance Procedure

This index maps every verified document in the repository so new engineers, operators, and contributors can locate authoritative references without duplication.

## 1. Documentation Map

| Area | Document | Scope |
| :--- | :--- | :--- |
| **Overview & Quickstart** | [README.md](../README.md) | Stack overview, Supabase SQL setup (`01`–`10`), local backend/Flutter startup, Family A/B pipelines |
| **System Architecture** | [ARCHITECTURE.md](../ARCHITECTURE.md) | High-level Mermaid diagram, Chat/`StudyContext`, PDF/QA pipeline, `ProjectStore` |
| **Architecture Decisions** | [docs/adr/README.md](adr/README.md) | ADRs covering deterministic engines (`ADR-001`), modular monolith (`ADR-002`), hybrid RAG (`ADR-003`), monetization (`ADR-004`), and isolated research (`ADR-005`) |
| **Developer & SDK Guide** | [DEVELOPER_GUIDE.md](../DEVELOPER_GUIDE.md) | API authentication, rate limits, Python SDK (`sdk/python/freedata_client.py`), JS `fetch` examples |
| **REST API Reference** | [API.md](../API.md) | Core REST endpoints (supplemented by live OpenAPI at `/docs` when `ENABLE_DOCS=true`) |
| **Deployment & Operations** | [DEPLOYMENT.md](../DEPLOYMENT.md) | Environment variables, SQL migrations (`01`–`12`), Dev/Staging/Prod workflows, RPO/RTO backups, Render & Firebase deploy |
| **Release & QA Process** | [RELEASE_MANAGEMENT.md](../RELEASE_MANAGEMENT.md) | CI/CD gates, release checklist, rollback steps |
| **Data & Methodology** | [DATA_CATALOG.md](../DATA_CATALOG.md), [METHODOLOGY.md](../METHODOLOGY.md) | Silver/Gold schemas, statistical formulas, conformal intervals, 80/8/12 financial model |
| **Governance, Security & Privacy** | [SECURITY.md](../SECURITY.md), [DATA_GOVERNANCE.md](../DATA_GOVERNANCE.md), [DATA_GOVERNANCE_POLICY.md](../DATA_GOVERNANCE_POLICY.md), [DATA_LICENSING_POLICY.md](../DATA_LICENSING_POLICY.md), [PRIVACY_POLICY.md](../PRIVACY_POLICY.md), [RESPONSIBLE_AI_POLICY.md](../RESPONSIBLE_AI_POLICY.md) | Auth/RLS isolation, zero-fabrication rule, dataset licensing (`LicensingRegistry`), user data deletion, responsible AI boundaries |
| **Monetization** | [MONETIZATION_ARCHITECTURE.md](../MONETIZATION_ARCHITECTURE.md) | `free`/`trial`/`premium` plans, atomic usage metering, webhook adapter |
| **Users & Admins** | [USER_GUIDE.md](../USER_GUIDE.md), [ADMIN_GUIDE.md](../ADMIN_GUIDE.md) | End-user workflows; admin RBAC (`ROLE_PERMISSIONS`), `X-Admin-Token`, `admin_audit_logs` |

## 2. Maintenance Procedure

1. **Code-to-Doc Sync:** Any PR modifying `api/server.py` routes, `sql/` migrations, `src/domains.py`, or `src/monetization.py` limits must update the corresponding doc (`API.md`, `DEPLOYMENT.md`, `MONETIZATION_ARCHITECTURE.md`) in the same PR.
2. **New Architectural Choices:** Record significant structural or cross-module decisions as a new `docs/adr/ADR-NNN-*.md` and link it in `docs/adr/README.md`.
3. **Never Expose Secrets:** Only document variable names (`.env.example`), never real tokens, keys, or database credentials.
4. **Separate Live vs. Planned:** Mark unimplemented features explicitly as *Planned* so public docs stay aligned with `tests/test_phase8_docs.py` and `tests/test_api_contracts.py`.

