"""Deterministic AI Evaluation & Monitoring Suite for FreeData.AI."""
from __future__ import annotations

from typing import Any

from src.ai_agent import FreeDataAIAgent, extract_client_state
from src.business_engine import build_professional_business_plan


def run_ai_evaluation_suite() -> dict[str, Any]:
    """Runs deterministic evaluations across grounding, instructions, finance, geography, and conflicts."""
    results: list[dict[str, Any]] = []

    # 1. Hallucination / numerical grounding detection
    grounded_ok = FreeDataAIAgent._numbers_are_grounded(
        "Le mil est à 210 XAF/kg (soit 21 000 XAF par sac de 100 kg).",
        "Prix observé : 210 XAF/kg à Bol (Lac).",
    )
    hallucinated_blocked = not FreeDataAIAgent._numbers_are_grounded(
        "La marge garantie est de 987 654 XAF avec 42 % de part de marché.",
        "Prix observé : 210 XAF/kg à Bol (Lac).",
    )
    results.append({
        "dimension": "hallucination_detection",
        "passed": bool(grounded_ok and hallucinated_blocked),
    })

    # 2. Instruction compliance beyond 8 messages
    hist = [{"role": "user", "content": "Inclure SWOT, sans équipement (CAPEX = 0)."}]
    hist += [{"role": "user", "content": f"Tour {i}"} for i in range(9)]
    st = extract_client_state(hist, "Finalement budget 900 000 XAF.")
    ctx = st["study_context"]
    results.append({
        "dimension": "instruction_compliance",
        "passed": (
            "SWOT" in ctx["required_sections"]
            and ctx["budget_and_assumptions"]["zero_capex"] is True
            and ctx["budget_and_assumptions"]["capital_xaf"] == 900000.0
        ),
    })

    # 3. Financial reasoning (honest non-rentable scale + constant BFR)
    bp = build_professional_business_plan(
        commodity="Millet",
        commodity_fr="Mil",
        origin_province="Lac",
        dest_province="N'Djamena",
        buy_price_per_kg=220.0,
        sell_price_per_kg=260.0,
        volatility_cv_pct=10.0,
        credit_score=70.0,
        capital_xaf=150_000.0,
        user_instructions=["BFR constant"],
    )
    results.append({
        "dimension": "financial_reasoning",
        "passed": (
            bp["unit_economics"]["profitability_status"] == "NON RENTABLE À CETTE ÉCHELLE"
            and bp["unit_economics"]["net_profit_cycle1_xaf"] < 0
            and bp["unit_economics"]["reinvest_enabled"] is False
        ),
    })

    # 4. Geographic accuracy & exclusions
    geo_st = extract_client_state([], "Négoce de mil de Batha vers N'Djamena, exclure Lac.")
    results.append({
        "dimension": "geographic_accuracy",
        "passed": (
            geo_st["known_params"]["origin_province"] == "Batha"
            and geo_st["known_params"]["dest_province"] == "N'Djamena"
            and "Lac" in geo_st["study_context"]["geography"]["excluded_provinces"]
        ),
    })

    # 5. Conflicting instructions / contradiction detection
    c1 = extract_client_state([], "Inclure PESTEL.")
    c2 = extract_client_state([], "Exclure PESTEL.", previous_context=c1["study_context"])
    results.append({
        "dimension": "conflict_detection",
        "passed": bool(c2["study_context"]["needs_clarification"] and c2["study_context"]["contradictions"]),
    })

    passed_count = sum(1 for r in results if r["passed"])
    return {
        "total_checks": len(results),
        "passed_checks": passed_count,
        "failed_checks": len(results) - passed_count,
        "pass_rate_pct": round((passed_count / len(results)) * 100.0, 1),
        "results": results,
    }

