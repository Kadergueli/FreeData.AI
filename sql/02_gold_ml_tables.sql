-- ============================================================================
-- FreeData.AI | Couche Gold : Tables de sortie ML & Credit Passport
-- Convention de nommage alignée sur public.table_*
-- Installation neuve : exécuter ce fichier puis 04_rls_policies.sql.
-- Base existante     : exécuter 03_gold_alert_columns.sql puis 04_rls_policies.sql.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.table_ml_forecasts (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    province VARCHAR(120) NOT NULL,
    market_name VARCHAR(180) NOT NULL,
    commodity_std VARCHAR(120) NOT NULL,
    last_observed_month VARCHAR(10) NOT NULL,
    last_observed_price DOUBLE PRECISION NOT NULL,
    forecast_month VARCHAR(10) NOT NULL,
    forecast_t1 DOUBLE PRECISION NOT NULL,
    ci_low_80 DOUBLE PRECISION NOT NULL,
    ci_high_80 DOUBLE PRECISION NOT NULL,
    hist_mae DOUBLE PRECISION NOT NULL,
    -- Prix attendu par le modèle pour le DERNIER mois observé, et écart observé/attendu (%).
    -- Source des alertes de tension ; NULL tant que le pipeline mensuel n'a pas été relancé.
    predicted_price DOUBLE PRECISION,
    deviation_pct DOUBLE PRECISION,
    date_calcul TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE (source, province, market_name, commodity_std)
);

CREATE TABLE IF NOT EXISTS public.table_ml_credit_passport (
    id BIGSERIAL PRIMARY KEY,
    province VARCHAR(120) NOT NULL,
    commodity_std VARCHAR(120) NOT NULL,
    credit_score DOUBLE PRECISION NOT NULL,
    grade VARCHAR(60) NOT NULL,
    ltv_ratio DOUBLE PRECISION NOT NULL,
    policy_recommendation TEXT NOT NULL,
    s_stability DOUBLE PRECISION NOT NULL,
    s_drawdown DOUBLE PRECISION NOT NULL,
    s_logistics DOUBLE PRECISION NOT NULL,
    s_coverage DOUBLE PRECISION NOT NULL,
    median_price DOUBLE PRECISION NOT NULL,
    cv_pct DOUBLE PRECISION NOT NULL,
    max_drawdown_pct DOUBLE PRECISION NOT NULL,
    obs_months INTEGER NOT NULL,
    date_calcul TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE (province, commodity_std)
);
