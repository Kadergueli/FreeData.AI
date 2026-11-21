"""Achat = dernier prix constaté ; vente = prévision t+1 ; predicted_price (valeur ajustée) n'est jamais prioritaire."""
import pandas as pd

from src.ai_agent import MarketDataProvider

FC = pd.DataFrame([
    {"province": "A", "market_name": "m1", "commodity_std": "Millet", "value": 200.0, "forecast_t1": 220.0, "predicted_price": 150.0},
    {"province": "B", "market_name": "m2", "commodity_std": "Millet", "value": 300.0, "forecast_t1": 330.0, "predicted_price": 400.0},
])
CP = pd.DataFrame([{"province": "A", "commodity_std": "Millet", "credit_score": 70.0, "grade": "B", "ltv_ratio": 0.6,
                    "cv_pct": 10.0, "max_drawdown_pct": 10.0}])


def test_series_kinds_ignore_predicted_price_when_real_columns_exist():
    assert MarketDataProvider._resolve_price_series(FC, "forecast").tolist() == [220.0, 330.0]
    assert MarketDataProvider._resolve_price_series(FC, "observed").tolist() == [200.0, 300.0]


def test_legacy_frame_without_forecast_columns_still_works():
    legacy = pd.DataFrame({"predicted_price": [250.0], "last_price": [240.0]})
    assert MarketDataProvider._resolve_price_series(legacy, "forecast").tolist() == [240.0]
    assert MarketDataProvider._resolve_price_series(legacy, "observed").tolist() == [240.0]
    only_pred = pd.DataFrame({"predicted_price": [250.0]})
    assert MarketDataProvider._resolve_price_series(only_pred, "observed").tolist() == [250.0]


def test_trade_pnl_buys_at_observed_sells_at_forecast():
    p = MarketDataProvider(FC, CP)
    r = p.simulate_trade_pnl("Millet", "A", "B", capital_xaf=500000.0, transport_cost_per_kg=0.0, loss_rate_pct=0.0)
    assert r["buy_price"] == 200.0 and r["sell_price"] == 330.0


def test_compare_sell_locations_uses_forecast():
    p = MarketDataProvider(FC, CP)
    rows = {x["province"]: x["price_xaf"] for x in p.compare_sell_locations("Millet", ["A", "B"])["rows"]}
    assert rows == {"A": 220.0, "B": 330.0}


def test_route_revenue_cost_is_observed_price():
    p = MarketDataProvider(FC, CP)
    r = p.calculate_route_revenue("A", "B", ["Millet"], volume_kg=1000.0)["routes"][0]
    assert r["origin_buy_price_xaf"] == 200.0 and r["origin_cost_basis"] == "observed"
    assert r["unit_spread_xaf"] == 130.0  # 330 prévu - 200 constaté
    assert r["volume_cost_xaf"] == 200000.0 and r["volume_margin_xaf"] == 130000.0
