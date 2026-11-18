"""Tests pour le moteur déterministe de Business Plan professionnel (`src/business_engine.py`)."""
from dataclasses import replace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.ai_agent import FreeDataAIAgent
from src.business_engine import allocate_capital, build_professional_business_plan, format_business_plan_markdown
from src.config import settings


@pytest.mark.parametrize("capital", [100_000, 500_000, 1_000_000, 500, 1234.56, 999.99])
def test_allocate_capital_exact_80_8_12_and_sum_equality(capital):
    alloc = allocate_capital(capital)
    total = alloc["total_capital_xaf"]
    wc = alloc["working_capital_xaf"]
    capex = alloc["capex_equipment_xaf"]
    res = alloc["safety_cash_reserve_xaf"]
    assert round(wc + capex + res, 2) == round(total, 2)
    assert alloc["inventory_purchasing_budget_xaf"] == wc
    assert alloc["remaining_liquidity_xaf"] == res


@pytest.mark.parametrize("bad_capital", [0, -1, -500_000, float("nan"), float("inf")])
def test_allocate_capital_rejects_non_positive_or_non_finite(bad_capital):
    with pytest.raises(ValueError):
        allocate_capital(bad_capital)


def test_beginner_guide_uses_same_80_8_12_allocation():
    hist_df = pd.DataFrame([{"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "date": "2026-07-01", "price": 200.0}])
    fc_df = pd.DataFrame([{"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 200.0, "last_observed_price": 200.0, "change_pct": 0.0}])
    cp_df = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "score_global": 80.0, "grade": "A", "cv_pct": 8.0, "ltv_pct": 70.0, "max_drawdown_pct": 5.0}])
    agent = FreeDataAIAgent(hist_df=hist_df, forecast_df=fc_df, passport_df=cp_df)
    guide = agent.provider.get_beginner_market_guide(capital_xaf=500_000.0, province="Lac", commodity="Millet")
    fp = guide["focus_plan"]
    assert fp["stock_budget_xaf"] == 400_000.0
    assert fp["capex_budget_xaf"] == 40_000.0
    assert fp["cash_reserve_xaf"] == 60_000.0
    assert "80 %" in guide["checklist"][0]["description"]


def test_build_professional_business_plan_accounting_and_projections():
    bp = build_professional_business_plan(
        commodity="Millet",
        commodity_fr="Mil",
        origin_province="Lac",
        dest_province="N'Djamena",
        buy_price_per_kg=200.0,
        sell_price_per_kg=320.0,
        volatility_cv_pct=8.5,
        credit_score=82.0,
        capital_xaf=1_000_000.0,
        transport_cost_per_kg=25.0,
        loss_rate_pct=5.0,
        monthly_fixed_costs_xaf=35_000.0,
        cycles_per_month=1.0,
        user_instructions=["Sans produits périssables"],
    )

    ca = bp["capital_allocation"]
    assert ca["capex_equipment_xaf"] == 80_000
    assert ca["safety_cash_reserve_xaf"] == 120_000
    assert ca["working_capital_xaf"] == 800_000
    assert ca["capex_equipment_xaf"] + ca["safety_cash_reserve_xaf"] + ca["working_capital_xaf"] == 1_000_000

    ue = bp["unit_economics"]
    assert ue["unit_landed_cost"] == 230.0
    assert ue["volume_bought_kg"] == 3478
    assert ue["volume_bought_bags_100kg"] == 34.78
    assert ue["volume_sellable_kg"] == 3304.1
    assert ue["break_even_price_per_kg"] == 252.7
    assert ue["is_simulated_sell_price"] is False
    assert ue["net_profit_cycle1_xaf"] > 0

    proj = bp["projection_6_months"]
    assert len(proj) == 6
    assert [r["month"] for r in proj] == [1, 2, 3, 4, 5, 6]
    assert proj[-1]["working_capital"] > proj[0]["working_capital"]
    assert proj[-1]["cumulative_cash"] > ca["safety_cash_reserve_xaf"]

    st = bp["stress_tests"]
    assert len(st) == 3
    assert all(r["net_profit_xaf"] < ue["net_profit_cycle1_xaf"] for r in st)

    md = format_business_plan_markdown(bp)
    assert "M6" in md and "800 000" in md


def test_build_professional_business_plan_simulates_missing_sell_price():
    bp = build_professional_business_plan(
        commodity="Millet",
        commodity_fr="Mil",
        origin_province="Lac",
        dest_province=None,
        buy_price_per_kg=210.0,
        sell_price_per_kg=None,
        volatility_cv_pct=None,
        credit_score=None,
        capital_xaf=500_000.0,
    )
    ue = bp["unit_economics"]
    assert ue["is_simulated_sell_price"] is True
    assert ue["target_sell_price_per_kg"] == round(ue["break_even_price_per_kg"] * 1.15, 1)


def test_agent_business_plan_wires_blueprint_to_llm(monkeypatch):
    hist_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "date": "2026-07-01", "price": 210.0},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "date": "2026-07-01", "price": 340.0},
    ])
    fc_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 220.0, "last_observed_price": 210.0, "change_pct": 4.8},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 350.0, "last_observed_price": 340.0, "change_pct": 2.9},
    ])
    cp_df = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "score_global": 82.0, "grade": "A", "cv_pct": 8.5, "ltv_pct": 70.0, "max_drawdown_pct": 6.0},
    ])
    agent = FreeDataAIAgent(hist_df=hist_df, forecast_df=fc_df, passport_df=cp_df)

    # Free mode renders structured blueprint tables
    res_free = agent.answer(
        "Fais-moi un business plan pour acheter du mil à Lac et vendre à N'Djamena avec 1 000 000 FCFA",
        tier="free",
    )
    assert res_free["intent"] == "business_simulator"
    assert "Business Plan Financier" in res_free["reply"]
    assert "800 000" in res_free["reply"]

    # Premium mode injects [MODÈLE FINANCIER CALCULÉ] and FreeData.AI Advisory prompt
    monkeypatch.setattr("src.ai_agent.settings", replace(settings, llm_api_key="test-key"))
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["messages"] = json["messages"]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"choices": [{"message": {"content": "Business plan validé avec un BFR de 800 000 XAF et CAPEX de 80 000 XAF."}}]}
        return resp

    monkeypatch.setattr("src.ai_agent.requests.post", fake_post)
    res_prem = agent.answer(
        "Fais-moi un business plan pour acheter du mil à Lac et vendre à N'Djamena avec 1 000 000 FCFA",
        tier="premium",
    )
    assert "800 000" in res_prem["reply"]
    assert "FreeData.AI Advisory" in captured["messages"][0]["content"]
    assert "[MODÈLE FINANCIER CALCULÉ]" in captured["messages"][-1]["content"]


def test_dynamic_overrides_bfr_constant_and_zero_capex():
    bp = build_professional_business_plan(
        commodity="Millet",
        commodity_fr="Mil",
        origin_province="Lac",
        dest_province="N'Djamena",
        buy_price_per_kg=200.0,
        sell_price_per_kg=320.0,
        volatility_cv_pct=8.5,
        credit_score=82.0,
        capital_xaf=1_000_000.0,
        user_instructions=["Sans équipement (CAPEX = 0)", "BFR constant sans réinvestissement"],
    )
    ca = bp["capital_allocation"]
    assert ca["capex_equipment_xaf"] == 0
    assert ca["working_capital_xaf"] == 880_000
    assert ca["safety_cash_reserve_xaf"] == 120_000
    assert ca["capex_share_pct"] == 0.0
    assert ca["working_capital_share_pct"] == 88.0

    proj = bp["projection_6_months"]
    assert all(r["working_capital"] == 880_000 for r in proj)
    total_net = sum(r["net_profit"] for r in proj)
    assert proj[-1]["cumulative_cash"] == 120_000 + total_net


def test_non_rentable_status_and_commercial_strategy():
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
        transport_cost_per_kg=25.0,
        loss_rate_pct=5.0,
        monthly_fixed_costs_xaf=35_000.0,
        predicted_t1_sell_price_per_kg=245.0,
    )
    ue = bp["unit_economics"]
    assert ue["break_even_price_per_kg"] > 260.0
    assert ue["profitability_status"] == "NON RENTABLE À CETTE ÉCHELLE"
    assert ue["net_profit_cycle1_xaf"] < 0
    assert ue["min_theoretical_capital_xaf"] is None

    cs = bp["commercial_strategy"]
    assert "flux tendu < 15 jours" in cs["flow_strategy"]
    assert "détaillants de quartier" in cs["distribution_channel"]
    assert cs["long_distance_freight_warning"] is True
    assert len(cs["field_validation_checklist"]) == 5

