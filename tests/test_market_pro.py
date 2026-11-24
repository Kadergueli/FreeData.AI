"""Tests Étape 4 (P3) — Marché PRO : prévisions 4 cultures + MAPE, Watchlists, Arbitrage et Export CSV."""
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.market_pro import MarketWatchlistStore, compute_campaign_investment_plan
from src.monetization import SubscriptionStore


def _sample_state():
    fc_df = pd.DataFrame([
        {
            "commodity_std": "Millet", "province": "Salamat", "market_name": "Am Timan",
            "forecast_month": "2026-11", "last_observed_price": 210.0, "forecast_t1": 225.0,
            "source": "FreeData.td / PAM-WFP",
        },
        {
            "commodity_std": "Millet", "province": "N'Djamena", "market_name": "Dembé",
            "forecast_month": "2026-11", "last_observed_price": 320.0, "forecast_t1": 340.0,
            "source": "FreeData.td / PAM-WFP",
        },
        {
            "commodity_std": "Sorghum (red)", "province": "Mandoul", "market_name": "Koumra",
            "forecast_month": "2026-11", "last_observed_price": 190.0, "forecast_t1": 200.0,
            "source": "FreeData.td / PAM-WFP",
        },
    ])
    tr = {"Millet": {"mape_pct": 8.4, "vs_naive_pct": 12.1, "verdict": "better"}}
    return {"forecast_df": fc_df, "track_record": tr}


def test_market_pro_overview_watchlists_arbitrage_and_csv(tmp_path):
    watch_store = MarketWatchlistStore(str(tmp_path / "billing.db"))
    sub_store = SubscriptionStore(str(tmp_path / "billing.db"))
    pro_owner = "user:u_mkt_pro_1234567890abcdef123456"
    other_owner = "user:u_mkt_other_1234567890abcdef1234"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=pro_owner, plan_id="premium", status="active", period_days=30,
    )
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=other_owner, plan_id="premium", status="active", period_days=30,
    )
    state = _sample_state()

    # 1. Watchlist créée et évaluée (déclenchée si seuil dépassé)
    created = server.create_market_watchlist_endpoint(
        server.MarketWatchlistCreateRequest(
            crop_id="millet", threshold_xaf_kg=300.0, direction="above", province="N'Djamena",
        ),
        owner_id=pro_owner, x_premium_key=None, watch_store=watch_store, sub_store=sub_store,
    )
    overview = server.market_pro_overview_endpoint(
        crop_id=None, state=state, owner_id=pro_owner, x_premium_key=None,
        watch_store=watch_store, sub_store=sub_store,
    )
    assert overview["validated_forecasts"][0]["historical_mape_pct"] == 8.4
    assert overview["arbitrage"][0]["origin_province"] == "Salamat"
    assert overview["arbitrage"][0]["dest_province"] == "N'Djamena"
    assert overview["arbitrage"][0]["spread_xaf_kg"] == 115.0
    assert overview["watchlists"][0]["triggered"] is True

    # 2. Isolation entre utilisateurs
    with pytest.raises(HTTPException) as exc_del:
        server.delete_market_watchlist_endpoint(
            created["watch_id"], owner_id=other_owner, x_premium_key=None,
            watch_store=watch_store, sub_store=sub_store,
        )
    assert exc_del.value.status_code == 404

    # 3. Export CSV institutionnel avec provenance & MAPE
    csv_resp = server.market_pro_export_csv_endpoint(
        crop_id="millet", state=state, owner_id=pro_owner, x_premium_key=None, sub_store=sub_store,
    )
    body = csv_resp.body.decode("utf-8")
    assert "historical_mape_pct" in body
    assert "Attribution Required" in body
    assert "Millet" in body


def test_spatial_arbitrage_and_agro_credit_passport(tmp_path):
    from pathlib import Path
    from src.agro_indicators import AgroIndicatorStore

    sub_store = SubscriptionStore(str(tmp_path / "billing.db"))
    pro_owner = "user:u_mkt_agro_1234567890abcdef12345"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=pro_owner, plan_id="premium", status="active", period_days=30,
    )
    state = _sample_state()
    state["hist_df"] = pd.DataFrame([
        {"commodity_std": "Millet", "province": "Logone Occidental", "year_month": "2024-05", "value": 180.0},
        {"commodity_std": "Millet", "province": "Logone Occidental", "year_month": "2025-05", "value": 240.0},
        {"commodity_std": "Millet", "province": "Logone Occidental", "year_month": "2026-05", "value": 260.0},
    ])
    state["passport_df"] = pd.DataFrame([
        {"commodity_std": "Millet", "province": "Logone Occidental", "credit_score": 74.0, "risk_grade": "B", "ltv_ratio": 0.65},
    ])

    arb = server.markets_spatial_arbitrage_endpoint(
        crop_id="millet", transport_cost_xaf_kg=35.0, tonnage=10.0,
        state=state, owner_id=pro_owner, x_premium_key=None, sub_store=sub_store,
    )
    assert arb["historical_mape_pct"] == 8.4
    assert arb["routes"][0]["origin_province"] == "Salamat"
    assert arb["routes"][0]["net_margin_xaf_kg"] == 80.0
    assert arb["routes"][0]["estimated_net_margin_xaf"] == 800000.0
    assert "NASA POWER Agro" in arb["sources"]

    agro_store = AgroIndicatorStore(str(tmp_path / "agro.db"))
    real_csv = Path(__file__).resolve().parent.parent / "freedatatd-agriculture-commercial-clean.csv"
    if real_csv.exists():
        agro_store.ingest_csv(str(real_csv))
    cp = server.credit_passport_agro_endpoint(
        server.AgroCreditPassportRequest(
            province="Logone Occidental", crop_id="millet", area_hectares=5.0, loan_amount_xaf=500000.0,
        ),
        state=state, owner_id=pro_owner, x_premium_key=None, agro_store=agro_store, sub_store=sub_store,
    )
    assert cp["profile"] == "agro"
    assert len(cp["scenarios"]) == 3
    assert cp["scenarios"][0]["scenario"] == "stress_floor"
    assert cp["scenarios"][0]["price_xaf_kg"] == 180.0
    assert cp["market_credit_passport"]["risk_grade"] == "B"
    if real_csv.exists():
        assert cp["cereal_yield_mean_2020_2024_kg_ha"] is not None
        assert cp["dry_years_risk"]["observed_july_aug_years"] >= 1
        assert cp["scenarios"][0]["dscr"] > 0



def test_forecast_uses_t1_never_the_fitted_value():
    """`predicted_price` est la valeur ajustée du dernier mois observé : elle ne doit jamais passer pour une prévision."""
    from src.agro_engine import _extract_crop_market_signals
    df = pd.DataFrame([{
        "commodity_std": "Millet", "province": "Lac", "market_name": "Bol", "forecast_month": "2026-12",
        "last_observed_price": 300.0, "predicted_price": 999.0, "forecast_t1": 330.0,
    }])
    sig = _extract_crop_market_signals(df, "Lac")["millet"]
    assert sig["predicted_xaf_kg"] == 330.0 and sig["change_pct"] == 10.0
    no_t1 = df.drop(columns=["forecast_t1"])
    assert _extract_crop_market_signals(no_t1, "Lac")["millet"]["predicted_xaf_kg"] is None


def test_campaign_plan_never_recommends_negative_margin_or_zero_bags():
    hist = pd.DataFrame([
        {"commodity_std": "Millet", "province": "Salamat", "year_month": f"202{y}-{m:02d}", "value": 200.0}
        for y in (4, 5, 6) for m in range(1, 13)
    ])
    forecast = pd.DataFrame([{
        "commodity_std": "Millet", "province": "Salamat", "last_observed_month": "2026-10",
        "last_observed_price": 200.0, "forecast_t1": 150.0,
    }])
    loss_making = compute_campaign_investment_plan(
        hist_df=hist, forecast_df=forecast, capital_xaf=100000.0,
        origin_province="Salamat", crop_id="millet", holding_months=1,
        bag_weight_kg=100.0, transport_per_bag_xaf=0.0,
        storage_per_bag_month_xaf=0.0, loss_pct=0.0,
    )
    assert loss_making["recommended_plan"] is None
    assert loss_making["recommendation_status"] == "no_viable_opportunity"
    assert loss_making["all_opportunities"][0]["recommendation_eligible"] is False
    assert loss_making["all_opportunities"][0]["recommendation_status"] == "negative_central_margin"

    no_bag = compute_campaign_investment_plan(
        hist_df=hist, forecast_df=forecast, capital_xaf=1.0,
        origin_province="Salamat", crop_id="millet", holding_months=1,
    )
    assert no_bag["recommended_plan"] is None
    assert no_bag["all_opportunities"][0]["recommendation_status"] == "capital_insufficient"


def test_campaign_plan_uses_observation_month_and_exposes_data_scope():
    hist = pd.DataFrame([
        {"commodity_std": "Millet", "province": "Salamat", "year_month": f"202{y}-{m:02d}", "value": 200.0 + m}
        for y in (4, 5, 6) for m in range(1, 13)
    ])
    forecast = pd.DataFrame([{
        "commodity_std": "Millet", "province": "Salamat", "last_observed_month": "2026-08",
        "last_observed_price": 210.0, "forecast_t1": 240.0,
    }])
    result = compute_campaign_investment_plan(
        hist_df=hist, forecast_df=forecast, capital_xaf=1000000.0,
        origin_province="Salamat", crop_id="millet", holding_months=2,
    )
    item = result["all_opportunities"][0]
    assert item["last_observed_month"] == "2026-08"
    assert item["data_scope"] == "province"
    assert item["used_national_fallback"] is False
    assert item["history_year_count"] == 3
