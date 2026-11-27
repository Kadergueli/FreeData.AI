# FreeData.AI — Data Governance & Institutional Policy

## 1. Platform Overview
FreeData.AI is a decision-support and pre-feasibility intelligence platform for agricultural markets in Chad. It separates deterministic data/financial computation from LLM narrative synthesis.

## 2. Data Governance & Quality Policy
- **Zero Fabrication Rule**: Market prices, forecasts, and stability indices are served strictly from verified datasets; unmeasured metrics (household demand, competitor shares) are explicitly marked as unavailable.
- **Provenance Separation**: Every report distinguishes `observe` (dataset), `simule` (forecast/scenario), `fourni par le promoteur` (user input), and `hypothese standard` (default operating parameters).
- **Automated QA Gate**: Reports failing deterministic data or financial integrity checks are blocked (`422`) before PDF delivery.

## 3. Privacy, Security & Responsible Use
- User project data is isolated by `owner_id` (`ProjectStore` / Supabase RLS `sql/10_projects_and_study_versions.sql`).
- Sensitive credential keys are stripped from serialized `StudyContext` payloads (`_strip_sensitive_keys`).
- **Legal Compliance Notice**: This document describes technical governance controls only and does **not** constitute legal certification (GDPR, OHADA, or banking compliance requires formal legal review).

## 4. Citation & Attribution Guidelines
When citing FreeData.AI outputs, reference:
- Primary dataset source shown in the report's *Traçabilité dynamique* table (e.g., `WFP` / `FreeData.td`),
- Observation period (`last_observed_month`),
- Study ID (`FD-...`) and version number (`v1`, `v2`, ...).


## 5. Commercial source eligibility — Market & Agriculture

The product scope is intentionally limited to **markets** and **agriculture**. Other sectors may remain in the collection warehouse, but they are not part of the commercial product surface until separately approved.

| Source currently present | Recorded terms / upstream rule | Product treatment |
| :--- | :--- | :--- |
| NASA POWER | NASA POWER states there are no restrictions on use, access or download; cite NASA POWER. | Eligible for commercial analytical features with attribution and source-specific checks. |
| World Bank | CC BY 4.0 datasets permit commercial use with attribution; verify the licence of each dataset. | Eligible when the dataset metadata confirms CC BY 4.0. |
| WFP market observations | The database records CC BY-IGO 3.0, but WFP's general website terms default to personal/non-commercial use unless special terms apply. | **Review required**: retain attribution and verify the exact dataset's special terms/permission before paid features or redistribution. |
| FEWS NET market observations | FEWS NET requires attribution and says underlying third-party datasets may carry additional restrictions or may not be redistributed without consent. | **Review required per indicator/source**; do not assume all FEWS NET records are commercially reusable. |
| Open-Meteo Free API | The data are CC BY 4.0, but the Free API terms restrict the service to non-commercial use; subscription apps and commercial products are explicitly commercial. | **Excluded from commercial features** until a commercial API licence/plan covers FreeData's use. |
| FAOSTAT | FAO database terms include a restriction against using datasets to promote a commercial enterprise, products or services. | **Excluded from commercial product features** unless written permission or an applicable exception is obtained. |
| Copernicus ERA5-Land | Recorded as “Licence to use Copernicus Products”; no exact terms/version stored in the row. | **Review required** before commercial use. |

This is a technical product-control register, not a legal opinion. The licence attached to a dataset and the terms governing the API/service used to obtain it are separate checks. A CC BY 4.0 data licence does not automatically waive a provider's API-tier restrictions.

### Agriculture enhancement implemented in this branch

The existing Agriculture zone screen is extended with NASA POWER monthly precipitation and temperature indicators already present in `public.table_public`. The ingestion script `scripts/ingest_nasa_power_climate.py` imports only the 12 supported regional hubs into the existing `table_agro_indicators` store. It does not ingest Open-Meteo or FAOSTAT, and does not create a second Agriculture screen.

- Default mode is read-only `--dry-run`.
- `--apply` requires `SUPABASE_DB_URL` and writes to the configured agro-indicator store.
- Monthly rainfall remains represented as a mean daily rate (mm/day), matching the source unit; it is not mislabeled as monthly accumulated rainfall.
- Temperature and precipitation anomalies are compared with the same calendar month in the 2020–2023 baseline. They are regional signals, not field measurements or yield forecasts.
