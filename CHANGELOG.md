# Changelog

## [Unreleased] - Agriculture : pré-diagnostic de zone et diagnostic de terrain PRO
### Added
- `src/agro/` : indicateurs NASA POWER par hub (12 hubs) et Banque mondiale (national, liste blanche), chacun avec source, licence, date, résolution spatiale et niveau de confiance ; aucune température ni précipitation en V1 ; Open-Meteo Agro-Climate et FAOSTAT exclus.
- `sql/16_gold_agro_indicators.sql` (Gold public, lecture seule) et `sql/17_agro_field_assessments_private.sql` (privé, RLS, isolé par compte).
- `scripts/load_agro_indicators.py` : validation (sans `--apply`) puis chargement du CSV NASA large et du CSV Banque mondiale long.
- API : `GET /api/v1/agro/hubs`, `/agro/indicators`, `/agro/zone-prediagnosis` (publics) ; `POST /agro/field-assessment[/preview]`, `GET/DELETE /agro/field-assessments[/{id}]` (PRO). Le titre du document est décidé par le QA gate : « Diagnostic de terrain (pré-achat) » seulement avec mesures de sol complètes, sinon « Pré-diagnostic Zonal Uniquement ».
- Flutter : écran `AgroScreen` (espace Grand public, espace Agronome PRO avec aperçu en direct, PDF co-brandé, vue intégration).

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

