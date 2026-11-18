# FreeData.AI — Data Catalog

## 1. Original Source Data

| Dataset | Source | Geographic Coverage | Collection Frequency | Units / Currency | Known Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `public.table_public` (FreeData.td) | FreeData.td / WFP / partner market surveys (as recorded in `source` column) | Chad provinces & tracked markets | Monthly (varies by market) | Local currency (`XAF`), standardized to `XAF/kg` in Silver | Household demand volumes, competitor market shares, and municipal taxes are **not** measured. Exact collection protocol & original license metadata are not stored in the repository. |

## 2. Processed & Derived Datasets

### Silver Layer
- **`public.v_clean_markets`** (`sql/01_silver_v_clean_markets.sql`): Normalizes commodity names (`commodity_std`) and converts units to homogeneous `XAF/kg`.

### Gold Layer (Published by `scripts/update_predictions.py` / `scripts/publish_pipeline.py`)
| Table | Migration | Key Variables | Access Policy |
| :--- | :--- | :--- | :--- |
| `public.table_ml_forecasts` | `sql/02`, `sql/03`, `sql/06` | `source`, `province`, `market_name`, `commodity_std`, `last_observed_month`, `last_observed_price`, `forecast_month`, `forecast_t1`, `ci_low_80`, `ci_high_80`, `hist_mae`, `forecast_quality`, `interval_status` | Public read (`anon`/`authenticated`) via `sql/04` |
| `public.table_ml_credit_passport` | `sql/02` | `province`, `commodity_std`, `credit_score`, `grade`, `ltv_ratio`, `cv_pct`, `max_drawdown_pct` | Public read (`anon`/`authenticated`) via `sql/04` |
| `public.table_ml_seasonality_studies` | `sql/05` | 12-month seasonal indices & track record | Locked to server `service_role` via `sql/09` |
| `public.table_ml_anomalies` | `sql/07` | Price shock & frozen-series anomaly flags | Locked to server `service_role` via `sql/09` |

### Application & Project Persistence (`sql/10_projects_and_study_versions.sql` / SQLite `ProjectStore`)
- `projects`, `project_contexts`, `project_conversations`, `project_messages`, `studies`, `study_versions` (protected by `owner_id` isolation & Supabase RLS).

> **Metadata honesty note:** Record counts and latest observation dates are dynamic at runtime (`GET /api/v1/health` and `GET /api/v1/metadata`).

