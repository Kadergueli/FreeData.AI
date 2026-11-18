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

