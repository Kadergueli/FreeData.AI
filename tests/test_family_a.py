"""Famille A : saisonnalité + backtest (données synthétiques à saisonnalité connue)."""
import numpy as np
import pandas as pd
import pytest

from src.backtest import run_backtest, summarize, report_markdown
from src.seasonality import (seasonal_calendar, seasonal_drift_forecast, seasonal_drift_table,
                             seasonal_profile)


def seasonal_panel(n_months=60, amp=0.20, noise=0.02, seed=1, provinces=("Lac", "Salamat", "Logone")):
    """Prix = niveau × (1 + amp·cos) : creux en octobre (récolte), pic en juillet (soudure)."""
    rng = np.random.default_rng(seed)
    months = pd.period_range("2020-01", periods=n_months, freq="M")
    rows = []
    for prov in provinces:
        base = 300 + rng.integers(0, 80)
        for m in months:
            season = amp * np.cos(2 * np.pi * (m.month - 7) / 12)  # max en juillet, min en janvier
            rows.append(("WFP", prov, f"{prov} marche", "Millet", m,
                         base * (1 + season) * (1 + rng.normal(0, noise))))
    return pd.DataFrame(rows, columns=["source", "province", "market_name", "commodity_std", "year_month", "value"])


def test_profile_recovers_known_peak_and_trough():
    prof = seasonal_profile(seasonal_panel(), "Millet")
    assert prof.loc[prof["index"].idxmax(), "month"] == 7
    assert prof.loc[prof["index"].idxmin(), "month"] == 1
    assert prof["index"].mean() == pytest.approx(1.0, abs=0.02)


def test_calendar_reliable_on_clear_seasonality():
    cal = seasonal_calendar(seasonal_panel(), "Millet")
    assert cal["status"] == "ok" and cal["reliable"]
    assert 1 in cal["buy_months"] and 7 in cal["sell_months"]
    assert cal["buy_discount_pct"] < 0 < cal["sell_premium_pct"]


def test_calendar_not_reliable_on_pure_noise():
    flat = seasonal_panel(amp=0.0, noise=0.05)
    cal = seasonal_calendar(flat, "Millet")
    assert cal["status"] != "ok" or not cal["reliable"]


def test_calendar_insufficient_data():
    short = seasonal_panel(n_months=10)
    assert seasonal_calendar(short, "Millet")["status"] == "insufficient_data"
    assert seasonal_calendar(seasonal_panel(), "Inconnu")["status"] == "insufficient_data"


def test_seasonal_drift_goes_up_before_peak():
    df = seasonal_panel()
    table = seasonal_drift_table(df)
    up = seasonal_drift_forecast(100.0, 4, table, "Millet", "Lac")   # avril : on monte vers juillet
    down = seasonal_drift_forecast(100.0, 9, table, "Millet", "Lac")  # septembre : on descend
    assert up > 100.0 > down


def test_drift_ignores_gaps():
    df = seasonal_panel()
    df = df[df["year_month"].dt.month != 5]  # plus aucun mois consécutif avril->mai / mai->juin
    table = seasonal_drift_table(df)
    assert np.isfinite(table["global"]).all()


def test_backtest_no_leakage_and_beats_naive_on_seasonal_data():
    df = seasonal_panel()
    res = run_backtest(df, n_origins=12, model_fn=None)
    assert not res.empty
    # chaque prévision doit viser le mois qui suit l'origine
    assert (pd.PeriodIndex(res["target"], freq="M") == pd.PeriodIndex(res["origin"], freq="M") + 1).all()
    s = summarize(res)
    m = s["methods"].set_index("method")
    assert m.loc["seasonal_drift", "MAE_xaf_kg"] < m.loc["naive", "MAE_xaf_kg"]


def test_backtest_changing_future_does_not_change_forecast():
    df = seasonal_panel()
    a = run_backtest(df, n_origins=6, model_fn=None)
    df2 = df.copy()
    last = df2["year_month"].max()
    df2.loc[df2["year_month"] == last, "value"] *= 10  # on corrompt le tout dernier mois
    b = run_backtest(df2, n_origins=6, model_fn=None)
    first_origin = a["origin"].min()  # son mois cible n'est pas le dernier mois
    fa = a[(a["origin"] == first_origin) & (a["method"] == "seasonal_drift")].sort_values("province")["forecast"].to_numpy()
    fb = b[(b["origin"] == first_origin) & (b["method"] == "seasonal_drift")].sort_values("province")["forecast"].to_numpy()
    assert np.allclose(fa, fb)


def test_backtest_with_existing_model_and_report():
    df = seasonal_panel(n_months=48)
    res = run_backtest(df, n_origins=6)
    assert (res["method"] == "model").any()
    s = summarize(res)
    assert 0.0 <= s["coverage_model"] <= 1.0
    md = report_markdown(s, 6)
    assert "Verdict" in md and "Modèle FreeData" in md


def test_backtest_empty_is_safe():
    tiny = seasonal_panel(n_months=5)
    res = run_backtest(tiny, n_origins=3, model_fn=None)
    s = summarize(res)
    assert s["n_points"] == 0
    assert "Pas assez" in report_markdown(s, 3)


# ---------------------------------------------------------------- agent : intention « timing »
def _agent_with_season():
    from src.ai_agent import FreeDataAIAgent
    from src.forecasting import run_forecasting_pipeline
    from src.credit_passport import compute_credit_passport
    kg = seasonal_panel(n_months=60)
    hist, forecast = run_forecasting_pipeline(kg)
    return FreeDataAIAgent(hist, forecast, compute_credit_passport(kg))


@pytest.mark.parametrize("q", [
    "Quand acheter du mil ?", "Quel est le meilleur moment pour vendre mon mil ?",
    "Quand stocker le mil à Lac ?", "Quelle est la période de soudure pour le mil ?",
    "quel mois le mil est le moins cher pour acheter",
])
def test_timing_intent_and_grounded_calendar(q):
    r = _agent_with_season().answer(q)
    assert r["intent"] == "timing"
    assert "janvier" in r["reply"] and "juillet" in r["reply"]
    assert "garantit" in r["reply"] or "tendances passées" in r["reply"]


def test_timing_without_history_is_honest():
    a = _agent_with_season()
    r = a.answer("Quand acheter du sorgho ?")
    assert r["intent"] == "timing"
    assert "pas assez" in r["reply"].lower()


def test_prices_questions_not_hijacked_by_timing():
    a = _agent_with_season()
    assert a.answer("Quel est le prix du mil à Lac ?")["intent"] == "forecast"
    assert a.answer("Où acheter du mil moins cher ?")["intent"] == "opportunity"


# ---------------------------------------------------------------- API premium : études avancées + contrôle d'accès
import dataclasses

from api import server
from fastapi.testclient import TestClient
from src.season_study import build_all_studies, build_seasonal_study, with_storage_cost, study_markdown

KEY = "premium-key-0123456789"


@pytest.fixture()
def premium_client(gold_tables, monkeypatch):
    fc_gold, cp_gold = gold_tables
    rows = [{"commodity_std": s["commodity"], "province": s.get("scope_province") or "", "payload": s}
            for s in build_all_studies(seasonal_panel(n_months=84))]
    assert rows, "l'étude nationale du Millet doit exister"
    server.STATE.clear(); server._RATE_LIMIT_BUCKET.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold, rows))
    monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, premium_api_keys=KEY))
    yield TestClient(server.app)
    server.STATE.clear(); server._RATE_LIMIT_BUCKET.clear()


def test_study_requires_valid_premium_key(premium_client):
    url = "/api/v1/studies/seasonality"
    assert premium_client.get(url, params={"commodity": "Millet"}).status_code == 403
    assert premium_client.get(url, params={"commodity": "Millet"}, headers={"X-Premium-Key": "wrong"}).status_code == 403


def test_study_disabled_without_configured_keys(gold_tables, monkeypatch):
    fc_gold, cp_gold = gold_tables
    server.STATE.clear(); server._RATE_LIMIT_BUCKET.clear()
    server.STATE.update(server.build_state_from_gold(fc_gold, cp_gold))
    monkeypatch.setattr(server, "settings", dataclasses.replace(server.settings, premium_api_keys=""))
    c = TestClient(server.app)
    assert c.get("/api/v1/studies/seasonality", params={"commodity": "Millet"}, headers={"X-Premium-Key": KEY}).status_code == 503
    server.STATE.clear()


def test_study_returns_calendar_strategy_and_net_return(premium_client):
    r = premium_client.get("/api/v1/studies/seasonality", params={"commodity": "millet", "storage_cost_pct_month": 1.0},
                           headers={"X-Premium-Key": KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["calendar"]["reliable"]
    assert body["storage_strategy"]["net_hit_rate_pct"] <= body["storage_strategy"]["hit_rate_pct"]
    assert len(body["profile"]) == 12


def test_study_markdown_and_validation(premium_client):
    h = {"X-Premium-Key": KEY}
    md = premium_client.get("/api/v1/studies/seasonality", params={"commodity": "Millet", "format": "markdown"}, headers=h)
    assert md.status_code == 200 and "Étude saisonnière" in md.text
    assert premium_client.get("/api/v1/studies/seasonality", params={"commodity": "Inconnu"}, headers=h).status_code == 404
    assert premium_client.get("/api/v1/studies/seasonality", params={"commodity": "Millet", "province": "Mars"}, headers=h).status_code == 404
    assert premium_client.get("/api/v1/studies/seasonality", params={"commodity": "Millet", "storage_cost_pct_month": 99}, headers=h).status_code == 422
    # un produit connu mais sans étude → réponse honnête, pas d'erreur
    ok = premium_client.get("/api/v1/studies/seasonality", params={"commodity": "Maize (white)"}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "insufficient_data"


def test_chat_premium_tier_needs_key_once_keys_are_configured(premium_client, monkeypatch):
    seen = []
    agent = server.STATE["agent"]
    orig = agent.answer
    monkeypatch.setattr(agent, "answer", lambda q, history=None, tier="free": (seen.append(tier), orig(q, history=history, tier=tier))[1])
    premium_client.post("/api/v1/chat", json={"message": "prix du mil", "tier": "premium"})
    premium_client.post("/api/v1/chat", json={"message": "prix du mil", "tier": "premium"}, headers={"X-Premium-Key": KEY})
    assert seen == ["free", "premium"]


def test_chat_timing_uses_stored_studies_in_production_mode(premium_client):
    r = premium_client.post("/api/v1/chat", json={"message": "Quand acheter du mil ?"}).json()
    assert r["intent"] == "timing" and "janvier" in r["reply"]


def test_malformed_study_rows_are_ignored():
    rows = [{"payload": "pas du json"}, {"payload": {"status": "ok"}}, {"payload": 12}, "x", {"payload": None}]
    assert server._study_payloads(rows) == []


def test_study_cycles_recompute_with_cost_and_no_future_leak():
    df = seasonal_panel(n_months=84)
    st = build_seasonal_study(df, "Millet")
    gross = st["storage_strategy"]["median_return_pct"]
    costly = with_storage_cost(st, 5.0)["storage_strategy"]
    assert costly["net_median_return_pct"] < gross and costly["net_hit_rate_pct"] <= st["storage_strategy"]["hit_rate_pct"]
    assert "Non calculée" not in study_markdown(st)


def test_check_family_a_run_writes_reports_without_network(tmp_path):
    from scripts.check_family_a import run
    out = run(seasonal_panel(n_months=84), tmp_path, n_origins=4)
    assert (tmp_path / "backtest_family_a.md").read_text(encoding="utf-8").startswith("# Backtest")
    import json
    rows = json.loads((tmp_path / "seasonality_studies.json").read_text(encoding="utf-8"))
    assert out["n_studies"] == len(rows) >= 1 and rows[0]["payload"]["status"] == "ok"


def test_short_history_is_never_reliable_and_says_so():
    short = seasonal_panel(n_months=34, amp=0.25, noise=0.01, provinces=tuple(f"P{i}" for i in range(12)))
    cal = seasonal_calendar(short, "Millet")
    assert cal["status"] != "ok" or (not cal["reliable"] and cal["min_years_observed"] < 3)
    if cal["status"] == "ok":
        st = build_seasonal_study(short, "Millet")
        assert any("Historique court" in c for c in st["caveats"])


def test_deviation_table_matches_profile_and_is_reusable():
    from src.seasonality import deviation_table
    df = seasonal_panel(n_months=72)
    dev = deviation_table(df)
    a = seasonal_profile(df, "Millet")
    b = seasonal_profile(None, "Millet", dev=dev)
    assert np.allclose(a["index"], b["index"])
