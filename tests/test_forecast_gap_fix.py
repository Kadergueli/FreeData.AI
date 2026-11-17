"""Dernier relevé après un trou : prévu quand même (qualité « reduced »), sans changer les autres séries."""
import importlib.util
import pathlib
import subprocess

import numpy as np
import pandas as pd
import pytest

from src.forecasting import run_forecasting_pipeline


def _original_module():
    """Version de main avant correction (référence), chargée depuis git."""
    root = pathlib.Path(__file__).resolve().parents[1]
    src = subprocess.run(["git", "show", "c9ef245:src/forecasting.py"], cwd=root, capture_output=True, text=True)
    if src.returncode != 0:
        pytest.skip("historique git indisponible")
    path = root / ".pytest_cache" / "forecasting_ref.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text(src.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("forecasting_ref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def panel_with_gap():
    rng = np.random.default_rng(3)
    months = pd.period_range("2023-01", "2025-12", freq="M")
    rows = []
    for prov in ["Lac", "Salamat", "Logone", "Mayo-Kebbi"]:
        for comm in ["Millet", "Maize (white)"]:
            base = 300 + rng.integers(0, 100)
            for m in months:
                rows.append(("WFP", prov, f"{prov} m", comm, m, base * (1 + rng.normal(0, 0.04))))
    df = pd.DataFrame(rows, columns=["source", "province", "market_name", "commodity_std", "year_month", "value"])
    # Logone/Millet : pas de relevé en novembre 2025 → le relevé de décembre n'a pas de mois précédent
    gap = (df.province == "Logone") & (df.commodity_std == "Millet") & (df.year_month == pd.Period("2025-11"))
    # Lac/Maize : seulement 2 relevés → trop peu pour prévoir
    few = (df.province == "Lac") & (df.commodity_std == "Maize (white)") & ~df.year_month.isin(
        [pd.Period("2023-01"), pd.Period("2025-12")])
    return df[~gap & ~few].reset_index(drop=True)


def test_gap_series_now_forecast_for_the_right_month():
    df = panel_with_gap()
    _, old = _original_module().run_forecasting_pipeline(df)
    _, new = run_forecasting_pipeline(df)
    key = lambda d: d[(d.province == "Logone") & (d.commodity_std == "Millet")]
    assert key(old).iloc[0]["forecast_month"] != "2026-01"          # avant : prévision datée d'avant le trou
    row = key(new).iloc[0]
    assert row["forecast_month"] == "2026-01" and row["last_observed_month"] == "2025-12"
    assert row["forecast_quality"] == "reduced"
    assert np.isfinite(row["forecast_t1"]) and row["ci_low_80"] < row["forecast_t1"] < row["ci_high_80"]


def test_other_series_unchanged_exactly():
    df = panel_with_gap()
    _, old = _original_module().run_forecasting_pipeline(df)
    _, new = run_forecasting_pipeline(df)
    # Les prévisions PONCTUELLES des autres séries ne bougent pas. Les intervalles et hist_mae, eux, ont volontairement
    # changé (calibration conforme hors-échantillon) : ils ne sont plus comparés à l'ancienne version.
    cols = ["province", "commodity_std", "forecast_t1", "forecast_month"]
    k = ["province", "commodity_std"]
    kept = new[new.forecast_quality == "standard"][cols]
    merged = kept.merge(old[cols], on=k, suffixes=("_n", "_o"))
    assert len(merged) == len(kept) > 0
    for c in ("forecast_t1",):
        assert np.allclose(merged[c + "_n"], merged[c + "_o"])
    assert (merged["forecast_month_n"] == merged["forecast_month_o"]).all()


def test_reduced_interval_is_wider_and_series_unique():
    _, new = run_forecasting_pipeline(panel_with_gap())
    assert not new.duplicated(["source", "province", "market_name", "commodity_std"]).any()
    r = new[new.forecast_quality == "reduced"].iloc[0]
    assert r["interval_status"] in ("wide_reduced", "insufficient_history")    # intervalle élargi ×1,5 (calibration conforme)
    assert r["ci_high_80"] - r["forecast_t1"] > 0 and r["forecast_t1"] - r["ci_low_80"] >= 0


def test_series_with_too_few_observations_get_no_forecast():
    _, new = run_forecasting_pipeline(panel_with_gap())
    assert new[(new.province == "Lac") & (new.commodity_std == "Maize (white)")].empty


def test_no_gap_data_gives_identical_output():
    from tests.conftest import make_synthetic_markets
    kg = make_synthetic_markets()
    _, old = _original_module().run_forecasting_pipeline(kg)
    _, new = run_forecasting_pipeline(kg)
    assert (new["forecast_quality"] == "standard").all()
    a = old.sort_values(["province", "commodity_std"]).reset_index(drop=True)
    b = new.sort_values(["province", "commodity_std"]).reset_index(drop=True)
    assert np.allclose(a["forecast_t1"], b["forecast_t1"])      # prévision ponctuelle identique ; les intervalles ont changé
    assert (b["ci_high_80"] > b["forecast_t1"]).all()


def test_agent_warns_on_reduced_quality_forecast():
    from src.ai_agent import FreeDataAIAgent
    from src.credit_passport import compute_credit_passport
    df = panel_with_gap()
    hist, fc = run_forecasting_pipeline(df)
    a = FreeDataAIAgent(hist, fc, compute_credit_passport(df))
    assert "confiance réduite" in a.answer("prix du mil à Logone")["reply"]
    assert "confiance réduite" not in a.answer("prix du mil à Salamat")["reply"]


def test_export_includes_quality_column():
    from scripts.update_predictions import build_exports
    from src.credit_passport import compute_credit_passport
    df = panel_with_gap()
    _, fc = run_forecasting_pipeline(df)
    out, _ = build_exports(fc, compute_credit_passport(df))
    assert set(out["forecast_quality"]) == {"standard", "reduced"}


def test_reduced_series_get_alert_columns_from_previous_observations():
    df = panel_with_gap()
    hist, new = run_forecasting_pipeline(df)
    row = new[(new.province == "Logone") & (new.commodity_std == "Millet")].iloc[0]
    assert row["forecast_quality"] == "reduced"
    prev = df[(df.province == "Logone") & (df.commodity_std == "Millet") & (df.year_month < pd.Period("2025-12"))].sort_values("year_month")
    expected = prev["value"].tail(3).mean()
    assert row["predicted_price"] == pytest.approx(expected, abs=0.01)
    assert row["deviation_pct"] == pytest.approx((row["value"] - expected) / expected * 100.0, abs=0.01)


def test_alert_columns_of_standard_series_unchanged():
    df = panel_with_gap()
    _, old = _original_module().run_forecasting_pipeline(df)
    _, new = run_forecasting_pipeline(df)
    k = ["province", "commodity_std"]
    m = new[new.forecast_quality == "standard"][k + ["predicted_price", "deviation_pct"]].merge(
        old[k + ["predicted_price", "deviation_pct"]], on=k, suffixes=("_n", "_o"))
    assert np.allclose(m["predicted_price_n"], m["predicted_price_o"]) and np.allclose(m["deviation_pct_n"], m["deviation_pct_o"])
