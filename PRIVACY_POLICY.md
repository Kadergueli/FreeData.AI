# FreeData.AI — Privacy & Data Governance Notice

## 1. Data Collected & Purpose
- **Project & Study Data**: Project names, `StudyContext` (objectives, commodity/corridor, assumptions, requested sections), conversations, and generated PDF versions — collected solely to persist and resume user market studies.
- **Usage Metering**: Anonymized operation counters (`daily_chat`, `monthly_pdf`, `daily_ml`, `daily_rag`), latency, and token counts (`usage_events`) — never private prompt or document bodies.

## 2. Storage, Access & Retention
- **Storage**: `ProjectStore` (`data/freedata_projects.db`) & `SubscriptionStore` (`data/freedata_billing.db`) or Supabase PostgreSQL with Row Level Security (`sql/10`, `sql/11`).
- **Access**: Strictly isolated by `owner_id` / `user_id`; administrators only have access to audit logs and licensing/subscription management (`X-Admin-Token`).
- **Deletion & Export**: Users can delete projects (`DELETE /api/v1/projects/{project_id}?confirm=true`) or wipe all personal project/artifact data (`DELETE /api/v1/privacy/my-data?confirm=true`).

## 3. Compliance Notice
This document describes technical privacy controls implemented in code and does **not** constitute formal legal certification (GDPR/CEMAC/local compliance requires legal counsel review).

