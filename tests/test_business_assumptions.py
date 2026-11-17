"""Tests de validation des hypothèses, de provenance et des calculs financiers (TASK 6)."""
import pandas as pd

from src.ai_agent import FreeDataAIAgent, extract_client_state


def _agent() -> FreeDataAIAgent:
    hist_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "date": "2026-07-01", "price": 200.0},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "date": "2026-07-01", "price": 320.0},
    ])
    fc_df = pd.DataFrame([
        {"province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 200.0, "last_observed_price": 200.0, "change_pct": 0.0},
        {"province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet", "forecast_month": "2026-08", "forecast_t1": 320.0, "last_observed_price": 320.0, "change_pct": 0.0},
    ])
    cp_df = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "score_global": 82.0, "grade": "A", "cv_pct": 8.0, "ltv_pct": 70.0, "max_drawdown_pct": 5.0},
    ])
    return FreeDataAIAgent(hist_df=hist_df, forecast_df=fc_df, passport_df=cp_df)


def test_missing_capital_asks_user_not_default():
    agent = _agent()
    res = agent.answer("Je veux me lancer dans le commerce agricole au Tchad")
    assert res["intent"] == "needs_capital"
    assert "500 000" not in res["reply"]


def test_missing_transport_cost_is_explicitly_marked_default():
    agent = _agent()
    res = agent.answer("Simule un achat de mil à Lac vers N'Djamena avec 800 000 FCFA")
    assert res["intent"] == "business_simulator"
    assert "Hypothèse transport utilisée : 25 XAF/kg" in res["reply"]


def test_capital_explicitly_provided_and_provenance():
    agent = _agent()
    sim = agent.provider.simulate_trade_pnl(
        "Millet", "Lac", "N'Djamena",
        capital_xaf=1_000_000.0, transport_cost_per_kg=30.0,
        capital_provenance="user_provided", transport_provenance="user_provided",
    )
    assert sim["status"] == "ok"
    assert sim["provenance"]["capital_xaf"] == "user_provided"
    assert sim["provenance"]["transport_cost_per_kg"] == "user_provided"
    assert sim["provenance"]["buy_price"] == "retrieved_from_dataset"
    assert sim["provenance"]["loss_rate_pct"] == "estimated"
    assert sim["provenance"]["net_profit_xaf"] == "calculated"
    assert sim["gross_margin_xaf"] > sim["net_profit_xaf"]  # marge brute != profit net


def test_capital_remembered_and_conflicting_values_latest_wins():
    history = [
        {"role": "user", "content": "Je veux acheter du mil à Lac avec 500 000 FCFA."},
        {"role": "assistant", "content": "Très bien."},
        {"role": "user", "content": "Finalement mon capital est de 1 500 000 FCFA."},
    ]
    state = extract_client_state(history, "Et pour vendre à N'Djamena ?")
    assert state["known_params"]["capital_xaf"] == 1_500_000.0


def test_missing_buying_or_selling_province_and_insufficient_data():
    agent = _agent()
    r_orig = agent.provider.simulate_trade_pnl("Millet", "Borkou", "N'Djamena", capital_xaf=500_000.0)
    assert r_orig["status"] == "missing_origin_data"
    assert r_orig["provenance"]["buy_price"] == "unavailable"

    r_dest = agent.provider.simulate_trade_pnl("Millet", "Lac", "Borkou", capital_xaf=500_000.0)
    assert r_dest["status"] == "missing_dest_data"
    assert r_dest["provenance"]["sell_price"] == "unavailable"


def test_zero_capital_and_very_high_transport_costs():
    agent = _agent()
    r_zero = agent.provider.simulate_trade_pnl("Millet", "Lac", "N'Djamena", capital_xaf=0.0)
    assert r_zero["status"] == "insufficient_capital"
    assert r_zero["purchasable_kg"] == 0

    r_high_tr = agent.provider.simulate_trade_pnl(
        "Millet", "Lac", "N'Djamena", capital_xaf=1_000_000.0, transport_cost_per_kg=250.0,
        capital_provenance="user_provided", transport_provenance="user_provided",
    )
    assert r_high_tr["status"] == "ok"
    assert r_high_tr["is_profitable"] is False
    assert r_high_tr["net_profit_xaf"] < 0
    assert r_high_tr["roi_pct"] < 0


def test_transparent_expense_model_and_profitability_outputs():
    agent = _agent()
    sim = agent.provider.simulate_trade_pnl(
        "Millet", "Lac", "N'Djamena",
        capital_xaf=1_000_000.0,
        transport_cost_per_kg=25.0,
        loss_rate_pct=5.0,
        other_operating_costs_xaf=20_000.0,
        capital_provenance="user_provided",
        transport_provenance="default_assumption",
    )
    for field in (
        "total_purchase_cost_xaf",
        "transport_cost_xaf",
        "physical_loss_cost_xaf",
        "other_operating_costs_xaf",
        "gross_revenue_xaf",
        "gross_margin_xaf",
        "estimated_operating_profit_xaf",
        "break_even_quantity_kg",
        "return_on_invested_capital_pct",
    ):
        assert field in sim

    # Marge brute (CA - coût d'achat) > Résultat d'exploitation estimé (CA - achat - transport - autres frais)
    assert sim["gross_margin_xaf"] == sim["gross_revenue_xaf"] - sim["total_purchase_cost_xaf"]
    assert sim["estimated_operating_profit_xaf"] == (
        sim["gross_revenue_xaf"] - sim["actual_invested_xaf"] - sim["other_operating_costs_xaf"]
    )
    assert sim["gross_margin_xaf"] > sim["estimated_operating_profit_xaf"]

    exp = sim["expenses_breakdown"]
    assert "total_purchase_cost_xaf" in exp["known_expenses"]
    assert "other_operating_costs_xaf" in exp["known_expenses"]
    assert "transport_cost_xaf" in exp["estimated_expenses"]
    assert "physical_loss_cost_xaf" in exp["estimated_expenses"]
    assert len(exp["missing_expenses"]) >= 5

