-- 11 — Subscriptions, Atomic Usage Metering, Webhook Idempotency & Admin Audit Logs.
-- Compatible with Supabase PostgreSQL.

CREATE TABLE IF NOT EXISTS public.subscriptions (
    user_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL DEFAULT 'free' CHECK (plan_id IN ('free', 'trial', 'premium')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'trialing', 'grace_period', 'past_due', 'cancelled', 'expired')),
    provider TEXT NOT NULL DEFAULT 'manual',
    external_subscription_id TEXT,
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end TIMESTAMPTZ,
    grace_until TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.usage_counters (
    user_id TEXT NOT NULL,
    period_key TEXT NOT NULL, -- YYYY-MM-DD (daily) or YYYY-MM (monthly)
    metric_name TEXT NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, period_key, metric_name)
);

CREATE TABLE IF NOT EXISTS public.usage_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_id TEXT,
    operation TEXT NOT NULL,
    provider_name TEXT,
    model_name TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_events_user_time ON public.usage_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.payment_webhook_events (
    webhook_event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.subscription_audit_logs (
    audit_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_plan TEXT,
    new_plan TEXT,
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_audit_logs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.subscriptions, public.usage_counters, public.usage_events,
    public.payment_webhook_events, public.subscription_audit_logs FROM anon;

DROP POLICY IF EXISTS subscriptions_owner_read ON public.subscriptions;
CREATE POLICY subscriptions_owner_read ON public.subscriptions
    FOR SELECT TO authenticated USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS usage_counters_owner_read ON public.usage_counters;
CREATE POLICY usage_counters_owner_read ON public.usage_counters
    FOR SELECT TO authenticated USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS usage_events_owner_read ON public.usage_events;
CREATE POLICY usage_events_owner_read ON public.usage_events
    FOR SELECT TO authenticated USING (auth.uid()::text = user_id);

