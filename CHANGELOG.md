# Changelog

## [1.2.0] - 2026-11-18
### Added
- Persistent `StudyContext` (`src/study_context.py`) preserving instructions beyond 8 chat turns with contradiction detection.
- Modular Report Engine (`src/reports/orchestrator.py`, `engines.py`, `sections.py`, `qa_validator.py`, `jobs.py`) with vector cash-flow charts, FreeData.AI logo, dynamic traceability, and 6-dimension QA gate.
- Persistent Projects & Study Versions (`src/projects/store.py`, `sql/10_projects_and_study_versions.sql`, `ProjectsScreen`).
- Data Governance, Licensing Registry, Lineage & Privacy (`src/governance.py`, `src/ai_eval.py`).
- Advanced Analytics, ML Engine, Hybrid RAG & Orchestration (`src/analytics/`, `src/ml_engine.py`, `src/rag_engine.py`, `src/orchestrator_ml_rag.py`, `AnalyticsScreen`).
- Data Products Catalog & Python SDK (`src/data_products.py`, `src/api_keys.py`, `sdk/python/freedata_client.py`).
- Multi-Domain Platform & Monetization (`src/domains.py`, `src/entitlements.py`, `src/monetization.py`, `sql/11`, `SubscriptionScreen`, `SettingsScreen`).
- AI Infrastructure Router, TTL Caches & Provider Gateway (`src/ai_infra.py`).
- Security Hardening (`src/security.py`), Admin RBAC Console (`src/admin.py`, `sql/12`, `AdminScreen`), Online SQLite Backup (`src/backup.py`), and `render.yaml`.

