"""Famille B : détection d'anomalies (données synthétiques à anomalies connues)."""
import numpy as np
import pandas as pd
import pytest

from src.anomalies import (SERIES_KEYS, detect_anomalies, divergence_anomalies, evaluate_detection,
                           inject_shocks, jump_anomalies, quality_issues, recent_anomalies)


def panel(n_months=30, n_markets=6, noise=0.02, seed=3, commodity="Millet"):
    rng = np.random.default_rng(seed)
    months = pd.period_range("2024-01", periods=n_months, freq="M")
    rows = []
    for k in range(n_markets):
        base = 300 + 20 * k
        for m in months:
            rows.append(("WFP", f"Prov{k % 3}", f"Marche{k}", commodity, m, base * (1 + rng.normal(0, noise))))
    return pd.DataFrame(rows, columns=SERIES_KEYS + ["year_month", "value"])


def set_value(df, market, month, factor):
    df = df.copy()
    m = (df["market_name"] == market) & (df["year_month"] == pd.Period(month, "M"))
    assert m.sum() == 1
    df.loc[m, "value"] *= factor
    return df


def test_clean_series_raises_almost_no_alert():
    anom = detect_anomalies(panel())
    assert len(anom[anom["kind"].isin(["jump", "divergence", "jump+divergence"])]) <= 2


def test_spike_is_detected_as_jump_with_right_numbers():
    df = set_value(panel(), "Marche2", "2025-12", 1.45)
    j = pd.DataFrame(jump_anomalies(df))
    hit = j[(j["market_name"] == "Marche2") & (j["month"] == "2025-12")]
    assert len(hit) == 1
    r = hit.iloc[0]
    assert r["change_pct"] > 30 and r["severity"] == "forte" and r["value"] > r["reference"]


def test_drop_is_detected_with_negative_sign():
    df = set_value(panel(), "Marche1", "2025-10", 0.6)
    j = pd.DataFrame(jump_anomalies(df))
    r = j[(j["market_name"] == "Marche1") & (j["month"] == "2025-10")].iloc[0]
    assert r["change_pct"] < -20 and r["score"] < 0


def test_small_move_is_not_flagged_even_on_flat_series():
    df = set_value(panel(noise=0.005), "Marche0", "2025-11", 1.06)  # +6 % < seuil de 10 %
    j = pd.DataFrame(jump_anomalies(df))
    assert j.empty or not ((j["market_name"] == "Marche0") & (j["month"] == "2025-11")).any()


def test_no_leakage_future_does_not_change_past_flags():
    df = set_value(panel(), "Marche2", "2025-06", 1.5)
    full = pd.DataFrame(jump_anomalies(df))
    cut = pd.DataFrame(jump_anomalies(df[df["year_month"] <= pd.Period("2025-06", "M")]))
    key = lambda x: set(map(tuple, x[SERIES_KEYS + ["month"]].itertuples(index=False, name=None)))
    assert key(cut) <= key(full) and ("WFP", "Prov2", "Marche2", "Millet", "2025-06") in key(cut)


def test_divergence_flags_market_moving_alone_but_not_common_shock():
    df = panel(noise=0.01)
    common = df["year_month"] >= pd.Period("2025-09", "M")
    df.loc[common, "value"] *= 1.4                       # choc COMMUN à tous les marchés : pas une divergence
    late = df["year_month"] >= pd.Period("2026-04", "M")
    df.loc[late & (df["market_name"] == "Marche3"), "value"] *= 1.6  # un marché décroche seul
    d = pd.DataFrame(divergence_anomalies(df))
    assert not d.empty and (d["market_name"] == "Marche3").all()
    assert d["month"].tolist() == ["2026-04"] and d.iloc[0]["change_pct"] > 40
    assert d.iloc[0]["reference"] < d.iloc[0]["value"]


def test_divergence_needs_enough_peers():
    df = panel(n_markets=3)
    df.loc[df["market_name"] == "Marche0", "value"] *= 2
    assert divergence_anomalies(df) == []


def test_stale_series_is_reported():
    df = panel()
    last = df["year_month"].max()
    frozen = df[df["market_name"] == "Marche4"].sort_values("year_month").tail(5)["value"].iloc[0]
    df.loc[(df["market_name"] == "Marche4") & (df["year_month"] > last - 5), "value"] = frozen
    q = pd.DataFrame(quality_issues(df))
    r = q[q["market_name"] == "Marche4"].iloc[0]
    assert r["kind"] == "stale" and r["score"] >= 4


def test_stopped_series_is_reported_with_gap():
    df = panel()
    df = df[~((df["market_name"] == "Marche5") & (df["year_month"] > df["year_month"].max() - 4))]
    q = pd.DataFrame(quality_issues(df))
    r = q[q["market_name"] == "Marche5"].iloc[0]
    assert r["kind"] == "stopped" and r["score"] == 4


def test_merged_kinds_and_recent_filter():
    df = set_value(panel(), "Marche2", "2026-05", 1.5)
    anom = detect_anomalies(df)
    row = anom[(anom["market_name"] == "Marche2") & (anom["month"] == "2026-05")]
    assert len(row) == 1 and row.iloc[0]["kind"] in ("jump", "jump+divergence")
    assert recent_anomalies(anom, months=1)["month"].eq(anom["month"].max()).all()


def test_empty_input_is_safe():
    assert detect_anomalies(panel().iloc[0:0]).empty


def test_injected_shocks_are_mostly_detected_and_report_is_consistent():
    df = panel(n_months=36, n_markets=12, noise=0.02, seed=5)
    shocked, truth = inject_shocks(df, 30, 0.40, seed=1)
    assert 0 < len(truth) <= 30 and not shocked.equals(df)
    ev = evaluate_detection(df, magnitudes=(0.10, 0.40), n=30, seed=1)
    assert ev["detection"][0.40]["rate"] >= 0.9
    assert ev["detection"][0.40]["rate"] >= ev["detection"][0.10]["rate"]
    assert ev["alert_rate_pct"] < 5


# --- Branchement dans le chat et l'API -------------------------------------------------------------

import pandas as _pd


def _anomaly_rows():
    base = dict(source="WFP", province="Lac", market_name="Bol", commodity_std="Millet", value=400.0, reference=300.0,
                change_pct=33.3, score=6.1)
    return [
        base | {"kind": "jump", "severity": "forte", "month": "2026-10"},
        base | {"kind": "divergence", "severity": "modérée", "month": "2026-09", "score": 3.9, "change_pct": 18.0,
                "market_name": "Karal", "value": 354.0, "reference": 300.0},
        base | {"kind": "stale", "severity": "modérée", "month": "2026-10", "score": 5, "market_name": "Mao",
                "change_pct": 0.0, "value": 300.0},
        base | {"kind": "jump", "severity": "forte", "month": "2025-01"},  # trop ancien : hors fenêtre
    ]


@pytest.fixture()
def chat_agent(gold_tables):
    from api import server
    fc, cp = gold_tables
    return server.build_state_from_gold(fc, cp, anomaly_rows=_anomaly_rows())["agent"]


def test_chat_lists_recent_anomalies_grounded_in_table(chat_agent):
    r = chat_agent.answer("y a-t-il des anomalies de prix ?")
    assert r["intent"] == "anomalies"
    assert "Saut de prix" in r["reply"] and "+33 %" in r["reply"] and "400 vs 300" in r["reply"]
    assert "Écart avec les autres marchés" in r["reply"] and "identique depuis 5 mois" in r["reply"]
    assert "à vérifier" in r["reply"]
    assert "janvier 2025" not in r["reply"]


def test_chat_filters_by_province_and_is_honest_when_nothing(chat_agent):
    r = chat_agent.answer("prix anormaux à Ouaddai")
    assert r["intent"] == "anomalies" and "aucune anomalie" in r["reply"].lower()


def test_chat_without_anomaly_table_does_not_invent(gold_tables):
    from api import server
    fc, cp = gold_tables
    agent = server.build_state_from_gold(fc, cp)["agent"]
    r = agent.answer("anomalies de prix du mil")
    assert r["intent"] == "anomalies" and "aucune anomalie" in r["reply"].lower()


def test_anomalies_endpoint_filters(gold_tables, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from api import server
    fc, cp = gold_tables
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-secret"))
    server.STATE.clear()
    server.STATE.update(server.build_state_from_gold(fc, cp, anomaly_rows=_anomaly_rows()))
    c = TestClient(server.app)
    hdr = {"X-Premium-Key": "pro-secret"}
    all_ = c.get("/api/v1/anomalies", headers=hdr).json()
    assert all_["count"] == 4
    strong = c.get("/api/v1/anomalies", params={"severity": "forte"}, headers=hdr).json()
    assert strong["count"] == 2 and all(i["severity"] == "forte" for i in strong["items"])
    assert c.get("/api/v1/anomalies", params={"kind": "stale"}, headers=hdr).json()["count"] == 1
    assert c.get("/api/v1/anomalies", params={"kind": "nimporte"}, headers=hdr).status_code == 422
    server.STATE.clear()


# --- Mouvements généraux et étalonnage -------------------------------------------------------------

def test_market_wide_move_is_not_a_jump():
    """Tous les marchés montent de 30 % le même mois (saison, choc commun) : aucune anomalie de saut."""
    df = panel(n_months=30, n_markets=8, noise=0.015)
    m = df["year_month"] == pd.Period("2026-04", "M")
    df.loc[m, "value"] *= 1.30
    jumps = [a for a in jump_anomalies(df) if a["month"] == "2026-04"]
    assert jumps == []


def test_single_market_jump_is_still_flagged_when_others_are_flat():
    df = set_value(panel(n_months=30, n_markets=8, noise=0.015), "Marche3", "2026-04", 1.35)
    found = [a for a in detect_anomalies(df).to_dict("records") if a["month"] == "2026-04"]
    assert any(a["market_name"] == "Marche3" for a in found)


def test_calibration_never_exceeds_cap_so_real_shocks_survive():
    from src import anomalies as an
    df = panel(n_months=36, n_markets=12, noise=0.02, seed=5)
    shocked, truth = inject_shocks(df, 40, 0.40, seed=2)  # >3 % des contrôles : le quantile serait contaminé
    ck = an._checks(shocked)
    thr = an._calibrated(ck, "z_jump", an.Z_THRESHOLD, an.TARGET_RATE)
    assert (thr <= an.CALIBRATION_CAP * an.Z_THRESHOLD + 1e-9).all()


def test_simultaneous_moves_in_one_province_become_one_regional_episode():
    df = panel(n_months=30, n_markets=9, noise=0.015)           # Prov0/1/2 : 3 marchés chacun
    for market in ("Marche0", "Marche3", "Marche6"):             # les 3 marchés de Prov0 montent ensemble
        df = set_value(df, market, "2026-04", 1.6)
    det = detect_anomalies(df)
    reg = det[(det["kind"] == "regional") & (det["month"] == "2026-04")]
    assert len(reg) == 1 and reg.iloc[0]["province"] == "Prov0" and reg.iloc[0]["market_name"] == "Marche0, Marche3, Marche6"
    assert reg.iloc[0]["change_pct"] > 40
    isolated = detect_anomalies(df, group_regional=False)
    assert (isolated["kind"] == "regional").sum() == 0


def test_two_markets_only_are_not_a_regional_episode():
    df = panel(n_months=30, n_markets=9, noise=0.015)
    for market in ("Marche0", "Marche3"):
        df = set_value(df, market, "2026-04", 1.6)
    det = detect_anomalies(df)
    assert (det["kind"] == "regional").sum() == 0


def test_evaluation_compares_operating_points():
    ev = evaluate_detection(panel(n_months=36, n_markets=12, noise=0.02, seed=5), magnitudes=(0.40,), n=20, seed=1)
    pts = ev["points"]
    assert len(pts) == 3
    rates = [p["alert_rate_pct"] for p in pts.values()]
    assert rates == sorted(rates)  # plus le plafond baisse, plus on alerte (ou autant)
    assert ev["alert_rate_pct"] == rates[0]


def test_return_to_normal_after_a_bad_reading_is_not_flagged():
    """Un relevé divisé par 2 un mois, puis retour à la normale : on signale le mois fautif, pas le rebond."""
    df = set_value(panel(n_months=30, n_markets=8, noise=0.012), "Marche2", "2026-05", 0.55)
    det = detect_anomalies(df, group_regional=False)
    mine = det[det["market_name"] == "Marche2"]
    assert "2026-05" in set(mine["month"])          # le relevé fautif est signalé
    assert "2026-06" not in set(mine["month"])      # le rebond ne l'est pas


def test_real_spike_after_flat_period_is_still_flagged():
    df = set_value(panel(n_months=30, n_markets=8, noise=0.012), "Marche2", "2026-05", 1.8)
    det = detect_anomalies(df, group_regional=False)
    assert "2026-05" in set(det[det["market_name"] == "Marche2"]["month"])


def test_dip_and_rebound_flags_only_a_drop_that_recovers():
    import pandas as pd
    from src.anomalies import dip_and_rebound, SERIES_KEYS

    def series(vals, name):
        d = {k: "x" for k in SERIES_KEYS}
        d["commodity_std"] = name
        return [{**d, "year_month": pd.Timestamp(2026, 1 + i, 1), "value": v} for i, v in enumerate(vals)]

    df = pd.DataFrame(series([200, 205, 120, 210, 212], "dip") + series([200, 120, 118, 119, 120], "real_drop"))
    out = dip_and_rebound(df)
    assert list(out["commodity_std"]) == ["dip"]
    assert out.iloc[0]["month"] == "2026-03"
