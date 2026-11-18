# FreeData.AI — Monetization & Usage-Management Architecture

## 1. Centralized Entitlements & Atomic Usage Metering (`src/monetization.py`, `sql/11`)
- **Plans (`DEFAULT_PLANS`)**: `free`, `trial`, `premium` with backend-enforced limits (`daily_chat_limit`, `monthly_pdf_limit`, `daily_ml_limit`, `daily_rag_limit`, `max_projects`, `max_file_mb`, `history_limit`). No plan claims "unlimited" usage.
- **Atomic Quota Consumption**: `SubscriptionStore.consume_usage_atomic()` executes inside SQLite `BEGIN IMMEDIATE` transactions to prevent concurrent overuse.
- **Privacy-Conscious Metering**: `usage_events` logs `user_id`, `request_id`, `operation`, `model_name`, `tokens_in`, `tokens_out`, `latency_ms`, and `success` — never private prompts or document contents.

## 2. Subscription Lifecycle & Manual Activation
- Supports `active`, `trialing`, `grace_period`, `past_due`, `cancelled`, and `expired`. Expired trials/premium plans automatically resolve `effective_plan_id = "free"`.
- Administrators can manually activate/upgrade/downgrade subscriptions via `POST /api/v1/billing/admin/activate` (`X-Admin-Token`), recorded in `subscription_audit_logs`.

## 3. Payment Provider Evaluation (Provider-Independent Abstraction)
`PaymentProviderAdapter` (`HmacJsonWebhookAdapter`) decouples billing from any specific gateway until a provider is formally selected:
- **Chad**: Mobile money (Airtel Money / Moov Money Tchad) via local aggregator or manual activation; requires local merchant registration & BCEAC/CEMAC compliance review.
- **India**: Razorpay / UPI / Cashfree; requires Indian entity/GST/RBI e-mandate compliance for recurring billing.
- **International**: Stripe / Flutterwave / Paystack; subject to supported merchant countries and cross-border FX settlement fees.

## 4. Cost & Margin Simulation
`POST /api/v1/billing/cost-simulation` (`simulate_unit_economics()`) estimates `cost_per_conversation_xaf`, `cost_per_report_xaf`, `avg_cost_per_user_xaf`, and `estimated_gross_margin_xaf` from configurable assumptions without hardcoding retail prices.

