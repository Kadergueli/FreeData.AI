"""Tests Étape 4 (P3) — Marché PRO : prévisions 4 cultures + MAPE, Watchlists, Arbitrage et Export CSV."""
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.market_pro import MarketWatchlistStore
from src.monetization import SubscriptionStore


def _sample_state():
    fc_df = pd.DataFrame([
        {
            "commodity_std": "Millet", "province": "Salamat", "market_name": "Am Timan",
            "forecast_month": "2026-11", "last_observed_price": 210.0, "predicted_price": 225.0,
            "source": "FreeData.td / PAM-WFP",
        },
        {
            "commodity_std": "Millet", "province": "N'Djamena", "market_name": "Dembé",
            "forecast_month": "2026-11", "last_observed_price": 320.0, "predicted_price": 340.0,
            "source": "FreeData.td / PAM-WFP",
        },
        {
            "commodity_std": "Sorghum (red)", "province": "Mandoul", "market_name": "Koumra",
            "forecast_month": "2026-11", "last_observed_price": 190.0, "predicted_price": 200.0,
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

