"""Intelligence marché : fiche produit, comparateur, pouls, panier, contexte mondial, brief, alertes, accès PRO."""
import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src import market_intel as mi
from src.market_alerts import MarketAlertStore, evaluate_rules
from src.monetization import SubscriptionStore

MARKETS = [("N'Djamena", "Dembé", 1.25), ("Salamat", "Am Timan", 0.85), ("Mandoul", "Koumra", 0.95),
           ("Logone Occidental", "Moundou", 1.0), ("Ouaddaï", "Abéché", 1.1)]


def _history(months=34, last_boost=1.0):
    rows = []
    periods = pd.period_range("2024-01", periods=months, freq="M")
    for commodity, base in (("Millet", 200.0), ("Sorghum (red)", 180.0), ("Maize (white)", 150.0), ("Rice (local)", 400.0)):
        for i, p in enumerate(periods):
            season = 1 + 0.15 * np.sin((p.month - 3) / 12 * 2 * np.pi)
            boost = last_boost if i == len(periods) - 1 and commodity == "Millet" else 1.0
            for prov, mkt, k in MARKETS:
                for source in ("WFP", "FEWS NET"):  # doublon volontaire : doit être dédoublonné
                    rows.append({"source": source, "province": prov, "market_name": mkt, "commodity_std": commodity,
                                 "year_month": p, "value": base * k * season * boost, "is_flagged_outlier": 0})
    return pd.DataFrame(rows)


def test_product_brief_dedupes_and_reports_limits():
    b = mi.product_brief(_history(), "millet")
    assert b["status"] == "ok" and b["n_markets"] == 5 and b["as_of"] == "2026-10"
    assert b["unit"] == "XAF/kg" and b["national_median_xaf_kg"] > 0
    assert b["seasonality"]["status"] == "ok"
    assert any("prix de gros" in x for x in b["limits"])
    assert "conseil d'investissement" in b["disclaimer"]
    assert b["history_months"] == 34


def test_unknown_product_and_empty_data():
    with pytest.raises(ValueError):
        mi.product_brief(_history(), "bitcoin")
    assert mi.product_brief(pd.DataFrame(), "millet")["status"] == "insufficient_data"
    assert mi.product_brief(None, "sesame")["status"] == "insufficient_data"


def test_exceptional_move_is_flagged_against_product_volatility():
    b = mi.product_brief(_history(last_boost=1.6), "millet")
    assert b["mom_pct"] > 40
    assert b["volatility"]["label"] == "mouvement exceptionnel"
    assert b["direction"] == "hausse"


def test_comparison_and_storage_net_of_costs():
    c = mi.market_comparison(_history(), "millet")
    assert c["markets"][0]["market"] == "Am Timan" and c["markets"][-1]["market"] == "Dembé"
    assert c["spread"]["gross_gap_pct"] > 0
    free = c["storage_window"]
    costly = mi.market_comparison(_history(), "millet", storage_cost_pct_month=5.0, loss_pct=5.0)["storage_window"]
    assert free["status"] == "ok" and costly["net_gain_pct"] < free["net_gain_pct"]
    assert "indicative" in free["reliability"] or "fiable" in free["reliability"]


def test_pulse_ranks_by_intensity():
    p = mi.market_pulse(_history(last_boost=1.6))
    assert p["items"][0]["product_id"] == "millet"
    assert p["summary"]["tracked"] == 4


def test_basket_validation_and_index():
    b = mi.commodity_basket(_history(), {"millet": 1, "sorghum": 1})
    assert b["status"] == "ok" and b["components"] and b["series"][0]["value"] > 0
    with pytest.raises(ValueError):
        mi.commodity_basket(_history(), {"millet": 1})
    with pytest.raises(ValueError):
        mi.commodity_basket(_history(), {"millet": -1, "sorghum": 1})


def test_world_context_degrades_and_states_no_predictive_claim():
    assert mi.world_context(pd.DataFrame(), _history())["status"] == "unavailable"
    months = pd.period_range("2025-01", periods=22, freq="M")
    world = pd.DataFrame({"month": months, "indicator": "World price, maize", "value": np.linspace(200, 260, 22), "unit": "US$/mt"})
    ctx = mi.world_context(world, _history(), "maize")
    assert ctx["product"]["status"] == "ok" and "pas de lien fiable" in ctx["note"]
    assert mi.world_context(world, _history(), "millet")["product"]["status"] == "no_benchmark"


def test_entry_brief_sections():
    e = mi.entry_brief(_history(), "millet", province="Salamat")
    assert e["status"] == "ok" and len(e["questions_before_committing"]) >= 4
    assert all(m["province"] == "Salamat" for m in e["where"]["cheapest"])
    assert e["storage_window"]["status"] == "ok" and e["limits"]


def test_alert_store_validation_isolation_and_evaluation(tmp_path):
    store = MarketAlertStore(str(tmp_path / "a.db"))
    with pytest.raises(ValueError):
        store.create_rule("u1", kind="gap", product_id="millet", value=10, direction="above")  # marché requis
    with pytest.raises(ValueError):
        store.create_rule("u1", kind="variation", product_id="millet", value=900, direction="up")
    t = store.create_rule("u1", kind="threshold", product_id="millet", value=1.0, direction="above")
    v = store.create_rule("u1", kind="variation", product_id="millet", value=20, direction="up")
    g = store.create_rule("u1", kind="gap", product_id="millet", value=10, direction="above", market_name="Dembé")
    n = store.create_rule("u1", kind="new_data", product_id="millet")
    assert store.list_rules("u2") == [] and store.delete_rule("u2", t["rule_id"]) is False
    ev = {r["rule_id"]: r for r in evaluate_rules(store.list_rules("u1"), _history(last_boost=1.6))}
    assert ev[t["rule_id"]]["triggered"] and ev[v["rule_id"]]["triggered"]
    assert ev[g["rule_id"]]["triggered"] and ev[n["rule_id"]]["triggered"]
    store.ack_rule("u1", n["rule_id"], "2026-10")
    again = evaluate_rules(store.list_rules("u1"), _history())
    assert not next(r for r in again if r["rule_id"] == n["rule_id"])["triggered"]
    assert store.purge_owner("u1") == 4
    assert evaluate_rules([{"rule_id": "x", "kind": "threshold", "product_id": "millet", "province": "",
                            "market_name": "", "direction": "above", "value": 1}], pd.DataFrame())[0]["triggered"] is False


def test_endpoints_standard_open_pro_gated(tmp_path):
    sub_store = SubscriptionStore(str(tmp_path / "b.db"))
    free, pro = "user:u_free_1234567890abcdef123456", "user:u_pro_1234567890abcdef1234567"
    sub_store.admin_update_subscription(actor="admin", target_user_id=pro, plan_id="premium", status="active", period_days=30)
    hist = _history()
    assert server.market_intel_product_endpoint("millet", history=hist)["status"] == "ok"
    with pytest.raises(HTTPException) as e:
        server.market_intel_product_endpoint("bitcoin", history=hist)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        server.market_intel_product_endpoint("millet", history=pd.DataFrame())
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        server.market_intel_pulse_endpoint(history=hist, owner_id=free, x_premium_key=None, sub_store=sub_store)
    assert e.value.status_code in (401, 402, 403, 503)
    assert server.market_intel_pulse_endpoint(history=hist, owner_id=pro, x_premium_key=None, sub_store=sub_store)["status"] == "ok"
    brief = server.market_intel_entry_brief_endpoint("sorghum", province=None, history=hist, world=pd.DataFrame(),
                                                     owner_id=pro, x_premium_key=None, sub_store=sub_store)
    assert brief["world"]["status"] == "unavailable"
    store = MarketAlertStore(str(tmp_path / "c.db"))
    created = server.market_intel_create_alert_endpoint(
        server.MarketAlertRuleRequest(kind="new_data", product_id="millet"),
        owner_id=pro, x_premium_key=None, alert_store=store, sub_store=sub_store)
    feed = server.market_intel_alerts_endpoint(history=hist, owner_id=pro, x_premium_key=None,
                                               alert_store=store, sub_store=sub_store)
    assert feed["triggered"][0]["rule_id"] == created["rule_id"]
    assert server.market_intel_ack_alert_endpoint(created["rule_id"], history=hist, owner_id=pro, x_premium_key=None,
                                                  alert_store=store, sub_store=sub_store)["month"] == "2026-10"
