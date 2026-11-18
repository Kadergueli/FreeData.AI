# FreeData.AI — Research & Financial Methodology

## 1. Market Price Analysis & Forecasting (`src/forecasting.py`)
- Prices are aggregated at `(province, market_name, commodity_std)` in `XAF/kg`.
- One-step-ahead (`t+1`) forecasts include an 80% confidence interval (`ci_low_80` – `ci_high_80`), historical MAE (`hist_mae`), and quality flags (`forecast_quality`, `interval_status`).
- Series older than `MAX_STALENESS_MONTHS` (default `3`) are flagged/filtered via `src/freshness.py`.

## 2. Market Stability Index (`src/credit_passport.py`)
- Composite `0–100` score (`credit_score`), risk grade, volatility coefficient of variation (`cv_pct`), maximum drawdown (`max_drawdown_pct`), and indicative `ltv_ratio`.
- **Disclaimer (`CREDIT_PASSPORT_DISCLAIMER`)**: Indicative market risk index only — never a bank credit approval.

## 3. Deterministic Financial Engine (`src/business_engine.py`)
All financial calculations are deterministic Python (never computed by an LLM):
- **Capital Allocation**: Default `80%` Working Capital (BFR) / `8%` Equipment CAPEX / `12%` Safety Reserve. With `"sans équipement"` or `"CAPEX = 0"`, shifts to `88% / 0% / 12%`.
- **Unit Landed Cost**: `buy_price_per_kg + transport_cost_per_kg + 5.0 XAF/kg (packaging)`.
- **Volume & Losses**: `volume_bought_kg = floor(working_capital / unit_landed_cost)`; `volume_sellable_kg = round(volume_bought_kg * (1 - loss_rate_pct / 100), 1)` (default `loss_rate_pct = 5%`, `transport = 25 XAF/kg`).
- **Break-Even Price (`Point Mort`)**: `((volume_bought_kg * unit_landed_cost) + monthly_fixed_costs_xaf) / max(volume_sellable_kg, 1.0)`.
- **Viability Rule**: If `break_even_price_per_kg >= sell_price` or `net_profit_cycle1_xaf <= 0`, status is **`NON RENTABLE À CETTE ÉCHELLE`** and `min_theoretical_capital_xaf` is computed when unit margin `> 0`.
- **6-Month Projection**: Default `reinvest = True` reinvests `75%` of positive net profit into BFR (capped at `3x` initial capital). With `"sans réinvestissement"` or `"BFR constant"`, `reinvest = False` keeps BFR constant M1–M6 and `cumulative_cash = safety_cash_reserve_xaf + sum(net_profit)`.
- **Stress Tests**: `-10%` sell price, `+25%` freight cost, and `2x` technical losses.

## 4. Automated QA Scoring (`src/reports/qa_validator.py`)
Six independent deterministic dimensions (`0–100`): `requirement_compliance`, `data_quality`, `financial_consistency`, `evidence_traceability`, `report_completeness`, `methodological_transparency`. Critical failures block PDF delivery (`HTTP 422`).

## 5. Methodological Limitations
- FreeData.AI does **not** measure household demand volumes, competitor market shares, or local municipal taxes/storage fees.
- Non-agricultural sectors (e.g., digital services) are outside dataset coverage and are rejected rather than fabricated.

