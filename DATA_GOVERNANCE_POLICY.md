# FreeData.AI — Data Governance Policy

## 1. Lifecycle Stages & Responsibilities
| Stage | Control / Implementation | Owner |
| :--- | :--- | :--- |
| Collection | Market price surveys (`public.table_public`) | Data Partners / FreeData.td |
| Ingestion & Cleaning | `sql/01_silver_v_clean_markets.sql` (`XAF/kg` normalization) | Data Engineering |
| Transformation | `src/forecasting.py`, `src/credit_passport.py`, `scripts/publish_pipeline.py` | ML / Analytics Pipeline |
| Validation | `src/reports/qa_validator.py` (6-dimension deterministic QA) | Report QA Layer |
| Storage | Supabase PostgreSQL (RLS `sql/04`, `09`, `10`) + SQLite `ProjectStore` | Platform Engineering |
| Publication & Sharing | `LicensingRegistry` (`src/governance.py`) + `GET /api/v1/governance/registry` | Governance Admin (`ADMIN_TOKEN`) |
| Retention & Deletion | `PrivacyController.delete_user_data` (`DELETE /api/v1/privacy/my-data?confirm=true`) | User / Platform Engineering |
| Versioning | `studies` + `study_versions` (`v1`, `v2`, ...) | `ProjectStore` |

## 2. Notice
This policy documents technical controls implemented in the repository and does **not** constitute legal certification or regulatory compliance (formal legal review is required).

