# FreeData.AI — Responsible AI Policy

## 1. Core Principles
- **Fact vs Assumption Separation**: Observed prices, `t+1` statistical forecasts, user-provided inputs, and standard operating assumptions (`25 XAF/kg` freight, `5%` losses, `35 000 XAF/month` fixed costs) are explicitly labeled.
- **Zero Fabrication**: The LLM cannot invent prices, demand volumes, competitor market shares, or citations; ungrounded numbers are rejected by `FreeDataAIAgent._numbers_are_grounded()`.
- **Uncertainty & Honest Viability**: Forecasts include 80% confidence intervals (`ci_low_80` – `ci_high_80`) and are never presented as guarantees. Unprofitable scales are explicitly flagged as `NON RENTABLE À CETTE ÉCHELLE`.
- **Conflict Resolution**: Contradictory user instructions are flagged (`needs_clarification=True`) rather than silently discarded.

## 2. Deterministic AI Evaluation (`src/ai_eval.py`)
`run_ai_evaluation_suite()` verifies hallucination detection, instruction retention, financial reasoning, geographic accuracy, and conflict detection deterministically without relying on LLM self-evaluation.

