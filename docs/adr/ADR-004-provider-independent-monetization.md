# ADR-004: Provider-Independent Subscriptions & Backend Entitlements

- **Status:** Accepted
- **Evidence in Repo:** `src/monetization.py`, `src/entitlements.py`, `sql/11_subscriptions_and_usage_metering.sql`

## Context
FreeData.AI operates across Chad and regional markets where payment providers (mobile money, cards, bank transfers) are not yet finalized and frontend clients cannot be trusted for access control.

## Problem
Hardcoding a single payment gateway creates vendor lock-in, and client-side tier checks can be bypassed.

## Options Considered
1. Direct integration with a single payment provider + client-side feature flags.
2. Centralized backend `SubscriptionStore` + `entitlements.py` + `PaymentWebhookAdapter` (`HmacJsonWebhookAdapter`).

## Decision
Enforce all quotas (`daily_chat_limit`, `monthly_pdf_limit`, `daily_ml_limit`, `daily_rag_limit`, `max_projects`, `max_file_mb`) and feature flags (`DEFAULT_PLANS`) on the backend with atomic SQLite/PostgreSQL usage metering, and abstract payment callbacks behind `PaymentWebhookAdapter` with HMAC-SHA256 signature verification.

## Consequences
- **Positive:** Any regional mobile-money or card provider can be plugged in later without rewriting entitlement logic; frontend cannot spoof `premium` access.
- **Trade-off:** Requires configuring `PREMIUM_API_KEYS` / webhook secrets and running `sql/11_subscriptions_and_usage_metering.sql` in production.

