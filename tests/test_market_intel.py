"""Intelligence marché : fiche produit, comparateur, pouls, panier, contexte mondial, brief, alertes, accès PRO."""
import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src import market_intel as mi
from src.market_alerts import MarketAlertStore, evaluate_rules
from src.monetization import SubscriptionStore

MARKETS = [("Salamat", "Am Timan"), ("N'Djamena", "Dembé"), ("Mandoul", "Koumra"),
           ("Logone", "Moundou"), ("Ouaddaï", "Abéché"), ("Kanem", "Mao")]


def _history(commodities=("Millet", "Sorghum (red)", "Maize (white)", "Rice (local)"), months=60, dup=True):
    rows = []
    periods = pd.period_range("2024-01", periods=months, freq="M")
    for ci, comm in enumerate(commodities):
        for mi_, (prov, mkt) in enumerate(MARKETS):
            for k, p in enumerate(periods):
                seasonal = 1 + 0.15 * np.cos(2 * np.pi * (p.month - 9) / 12)  # cher en septembre
                val = (200 + 20 * ci + 10 * mi_) * seasonal * (1 + 0.004 * k)
                for src in (["WFP", "FEWS NET"] if dup else ["WFP"]):
                    rows.append({"source": src, "province": prov, "market_name": mkt, "commodity_std": comm,
                                 "year_month": p, "value": val, "is_flagged_outlier": 0})
    return pd.DataFrame(rows)


def test_brief_dedupes_sources_and_reports_limits():
    brief = mi.product_brief(_history(), "millet")
    assert brief["status"] == "ok" and brief["n_markets"] == 6
    assert brief["as_of"] == "2028-12"
    # Le doublon WFP/FEWS NET ne doit pas changer la médiane
    single = mi.product_brief(_history(dup=False), "millet")
    assert brief["national_median_xaf_kg"] == single["national_median_xaf_kg"]
    assert brief["seasonality"]["status"] == "ok"
    assert brief["seasonality"]["reliable"] is True  # 5 saisons
    assert any("détail" in lim for lim in brief["limits"])
    assert "conseil d'investissement" in brief["disclaimer"]


def test_brief_short_history_marks_seasonality_indicative():
    brief = mi.product_brief(_history(months=36), "millet")
    assert brief["seasonality"]["reliable"] is False
    assert "indicative" in brief["seasonality"]["label"]
    assert any("moins de 3 années" in lim for lim in brief["limits"])


def test_insufficient_and_unknown_product():
    assert mi.product_brief(_history()[:0], "millet")["status"] == "insufficient_data"
    assert mi.product_brief(_history(), "sesame")["status"] == "insufficient_data"
    with pytest.raises(ValueError):
        mi.product_brief(_history(), "diamant")


def test_missing_month_does_not_create_fake_variation():
    df = _history(months=14, dup=False)
    last = df["year_month"].max()
    df = df[df["year_month"] != last - 1]  # trou à M-1 : la variation mensuelle doit devenir indisponible
    brief = mi.product_brief(df, "millet")
    assert brief["mom_pct"] is None


def test_comparison_and_storage_window():
    comp = mi.market_comparison(_history(), "millet", storage_cost_pct_month=1.0, loss_pct=3.0)
    assert comp["status"] == "ok"
    prices = [m["price_xaf_kg"] for m in comp["markets"]]
    assert prices == sorted(prices) and len(prices) == 6
    st = comp["storage_window"]
    assert st["status"] == "ok" and st["sell_month"] == "septembre"
    assert st["net_gain_pct"] == pytest.approx(st["gross_gain_pct"] - st["months_stored"] - 3.0, abs=0.11)
    assert "financement" in st["note"]
    heavy = mi.market_comparison(_history(), "millet", storage_cost_pct_month=15.0)
    assert heavy["storage_window"]["net_gain_pct"] < 0
    assert "pas justifié" in heavy["storage_window"]["verdict"]


def test_pulse_ranks_by_intensity():
    df = _history()
    last = df["year_month"].max()
    mask = (df["commodity_std"] == "Maize (white)") & (df["year_month"] == last)
    df.loc[mask, "value"] *= 1.5
    pulse = mi.market_pulse(df)
    assert pulse["items"][0]["product_id"] == "maize"
    assert pulse["items"][0]["volatility_label"] != "dans la normale"
    assert pulse["summary"]["tracked"] == 4


def test_basket_weights_and_validation():
    df = _history()
    b = mi.commodity_basket(df, {"millet": 2, "sorghum": 1})
    assert b["status"] == "ok" and b["yoy_pct"] is not None
    assert sum(c["weight"] for c in b["components"]) == pytest.approx(1.0, abs=0.01)
    with pytest.raises(ValueError):
        mi.commodity_basket(df, {"millet": 1})
    with pytest.raises(ValueError):
        mi.commodity_basket(df, {"millet": -1, "sorghum": 1})
    # produit absent des données : exclu, pas d'erreur
    out = mi.commodity_basket(df, {"millet": 1, "sorghum": 1, "sugar": 1})
    assert "sugar" in out["excluded"]


def _world():
    months = pd.period_range("2025-01", periods=22, freq="M")
    rows = []
    for ind, unit, base in [("World price, maize", "US$/mt", 200.0), ("World price, urea (fertiliser)", "US$/mt", 400.0)]:
        for i, m in enumerate(months):
            rows.append({"month": m, "indicator": ind, "value": base + i, "unit": unit})
    return pd.DataFrame(rows)


def test_world_context_unavailable_and_available():
    assert mi.world_context(pd.DataFrame(), _history(), "maize")["status"] == "unavailable"
    ctx = mi.world_context(_world(), _history(), "maize")
    assert ctx["status"] == "ok" and ctx["product"]["world"]["yoy_pct"] is not None
    assert "urea" in ctx["inputs"] and "pas de lien fiable" in ctx["note"]
    assert mi.world_context(_world(), _history(), "millet")["product"]["status"] == "no_benchmark"


def test_entry_brief_contains_decision_sections():
    out = mi.entry_brief(_history(), "millet", province="Salamat", world=_world())
    assert out["status"] == "ok"
    for key in ("snapshot", "volatility", "seasonality", "where", "storage_window", "risks",
                "questions_before_committing", "limits", "world"):
        assert key in out
    assert all(m["province"] == "Salamat" for m in out["where"]["cheapest"])
    assert len(out["questions_before_committing"]) >= 4


def test_alert_rules_evaluation_and_store_isolation(tmp_path):
    store = MarketAlertStore(str(tmp_path / "b.db"))
    df = _history()
    a = store.create_rule("user:a", kind="threshold", product_id="millet", value=100, direction="above")
    store.create_rule("user:a", kind="variation", product_id="millet", value=50, direction="any")
    store.create_rule("user:a", kind="gap", product_id="millet", value=5, direction="above", market_name="Dembé")
    store.create_rule("user:a", kind="new_data", product_id="millet")
    ev = {r["kind"]: r for r in evaluate_rules(store.list_rules("user:a"), df)}
    assert ev["threshold"]["triggered"] is True
    assert ev["variation"]["triggered"] is False
    assert ev["gap"]["current"] is not None
    assert ev["new_data"]["triggered"] is True
    store.ack_rule("user:a", ev["new_data"]["rule_id"], ev["new_data"]["as_of"])
    again = {r["kind"]: r for r in evaluate_rules(store.list_rules("user:a"), df)}
    assert again["new_data"]["triggered"] is False
    assert store.delete_rule("user:b", a["rule_id"]) is False
    assert store.list_rules("user:b") == []
    with pytest.raises(ValueError):
        store.create_rule("user:a", kind="gap", product_id="millet", value=5)  # marché obligatoire
    with pytest.raises(ValueError):
        store.create_rule("user:a", kind="threshold", product_id="millet", value=-1)
    # sans données : jamais d'exception
    assert evaluate_rules(store.list_rules("user:a"), pd.DataFrame())[0]["triggered"] is False


def test_endpoints_gate_pro_and_keep_brief_public(tmp_path):
    sub_store = SubscriptionStore(str(tmp_path / "b.db"))
    alert_store = MarketAlertStore(str(tmp_path / "b.db"))
    pro = "user:u_intel_pro_1234567890abcdef1234"
    free = "user:u_intel_free_1234567890abcdef123"
    sub_store.admin_update_subscription(actor="admin", target_user_id=pro, plan_id="premium", status="active", period_days=30)
    df = _history()
    assert server.market_intel_product_endpoint("millet", history=df)["status"] == "ok"
    with pytest.raises(HTTPException) as e:
        server.market_intel_product_endpoint("diamant", history=df)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        server.market_intel_product_endpoint("millet", history=pd.DataFrame())
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        server.market_intel_pulse_endpoint(history=df, owner_id=free, x_premium_key=None, sub_store=sub_store)
    assert e.value.status_code in (401, 402, 403, 503)
    assert server.market_intel_pulse_endpoint(history=df, owner_id=pro, x_premium_key=None, sub_store=sub_store)["status"] == "ok"
    brief = server.market_intel_entry_brief_endpoint(
        "millet", province=None, history=df, world=pd.DataFrame(), owner_id=pro, x_premium_key=None, sub_store=sub_store)
    assert brief["world"]["status"] == "unavailable"
    with pytest.raises(HTTPException) as e:
        server.market_intel_entry_brief_endpoint(
            "millet", province=None, history=df, world=pd.DataFrame(), owner_id=free, x_premium_key=None, sub_store=sub_store)
    assert e.value.status_code in (401, 402, 403, 503)
    rule = server.market_intel_create_alert_endpoint(
        server.MarketAlertRuleRequest(kind="threshold", product_id="millet", value=100),
        owner_id=pro, x_premium_key=None, alert_store=alert_store, sub_store=sub_store)
    feed = server.market_intel_alerts_endpoint(history=df, owner_id=pro, x_premium_key=None,
                                               alert_store=alert_store, sub_store=sub_store)
    assert feed["triggered"][0]["rule_id"] == rule["rule_id"]


def test_rest_history_loads_per_product_with_keyset_pagination(monkeypatch):
    from src import market_data as md
    from src.config import settings

    rows = [{"id": i, "source": "WFP", "month_date": "2025-01-01", "province": "A", "market_name": "M",
             "commodity_std": "Millet", "price_value": 200.0 + i, "is_flagged_outlier": 0} for i in range(1, 2501)]
    seen = []

    class _Resp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.append(params["commodity_std"])
        if params["commodity_std"] != "ilike.millet":
            return _Resp([])
        last = int(params["id"][3:])
        return _Resp([r for r in rows if r["id"] > last][:1000])

    monkeypatch.setattr(md.requests, "get", fake_get)
    monkeypatch.setattr(type(settings), "data_backend", property(lambda self: "supabase_rest"))
    md.clear_cache()
    try:
        df = md.load_price_history()
    finally:
        md.clear_cache()
    assert len(df) == 2500 and "year_month" in df.columns
    assert seen.count("ilike.millet") == 3  # 1000 + 1000 + 500
