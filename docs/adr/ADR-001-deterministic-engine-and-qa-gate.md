# ADR-001: Deterministic Financial/ML Engines & Zero-Fabrication QA Gate

- **Status:** Accepted
- **Evidence in Repo:** `src/business_engine.py`, `src/ai_agent.py`, `src/reports/qa_validator.py`, `DATA_GOVERNANCE.md`

## Context
FreeData.AI serves financial pre-feasibility studies, market price forecasts, and institutional PDF reports where hallucinated numbers or forced profitability would mislead users.

## Problem
General-purpose LLMs frequently invent statistics, miscalculate break-even/cashflow metrics, or overwrite user constraints across long conversations.

## Options Considered
1. Pure LLM generation with prompt instructions only.
2. Deterministic calculation engines paired with LLM narrative synthesis and an automated QA gate.

## Decision
Separate deterministic computation (`src/business_engine.py`, `src/forecasting.py`, `src/credit_passport.py`) from LLM synthesis. Enforce numerical grounding (`FreeDataAIAgent._numbers_are_grounded`) and block PDF delivery (`HTTP 422`) when `validate_market_study_report()` detects critical data or financial integrity failures.

## Consequences
- **Positive:** Verifiable financial tables (`80/8/12` / `88/0/12`), honest non-profitable flags, and explicit provenance (`observe`, `simule`, `fourni par le promoteur`, `hypothese standard`).
- **Trade-off:** Higher code complexity in `src/study_context.py` and `src/reports/` to keep deterministic state synchronized across turns.

