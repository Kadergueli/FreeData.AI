"""Tests d'isolation des groupes, d'exactitude statistique et de non-fuite pour `src/forecasting.py`."""
import numpy as np
import pandas as pd
import pytest

from src.backtest import run_backtest
from src.forecasting import _conformal_q80, run_forecasting_pipeline


def _make_series(
    source: str,
    province: str,
    market: str,
    commodity: str,
    months: list[str],
    values: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source": source,
            "province": province,
            "market_name": market,
            "commodity_std": commodity,
            "year_month": pd.PeriodIndex(months, freq="M"),
            "value": values,
        }
    )


def test_cross_series_rolling_isolation_regression():
    """Deux séries aux niveaux de prix très différents ne doivent jamais contaminer leurs fenêtres glissantes."""
    months = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
    s_high = _make_series("WFP", "Lac", "Bol", "Millet", months, [10_000.0] * 5)
    s_low = _make_series("WFP", "Lac", "Bol", "Sorghum (red)", months, [200.0] * 5)
    df = pd.concat([s_high, s_low], ignore_index=True)

    train_full, latest = run_forecasting_pipeline(df)

    low_train = train_full[train_full["commodity_std"] == "Sorghum (red)"]
    assert not low_train.empty
    assert np.allclose(low_train["roll_mean_3"], 200.0)
    assert np.allclose(low_train["roll_std_3"], 0.0)
    assert (low_train["predicted_price"] < 500.0).all()

    low_latest = latest[latest["commodity_std"] == "Sorghum (red)"].iloc[0]
    assert low_latest["forecast_t1"] < 500.0


@pytest.mark.parametrize("diff_col,diff_val", [
    ("source", "FEWS"),
    ("province", "Salamat"),
    ("market_name", "Moundou"),
    ("commodity_std", "Maize (white)"),
])
def test_isolation_across_all_series_identifiers(diff_col, diff_val):
    """Changer un seul identifiant (source, province, market_name, commodity_std) isole strictement le rolling."""
    months = ["2025-01", "2025-02", "2025-03", "2025-04"]
    s1 = _make_series("WFP", "Lac", "Bol", "Millet", months, [5000.0, 5000.0, 5000.0, 5000.0])
    s2 = _make_series("WFP", "Lac", "Bol", "Millet", months, [100.0, 100.0, 100.0, 100.0])
    s2[diff_col] = diff_val
    df = pd.concat([s1, s2], ignore_index=True)

    train_full, _ = run_forecasting_pipeline(df)
    sub2 = train_full[train_full[diff_col] == diff_val]
    assert np.allclose(sub2["roll_mean_3"], 100.0)
    assert np.allclose(sub2["roll_std_3"], 0.0)


def test_rolling_mean_and_std_exact_values():
    """Vérifie l'exactitude mathématique de `roll_mean_3` et `roll_std_3` (décalés à t-1)."""
    months = ["2025-01", "2025-02", "2025-03", "2025-04"]
    df = _make_series("WFP", "Lac", "Bol", "Millet", months, [100.0, 200.0, 300.0, 400.0])

    train_full, _ = run_forecasting_pipeline(df)
    train_full = train_full.sort_values("year_month").reset_index(drop=True)

    # train_full commence au mois 2 (2025-02) car lag_1 est requis
    assert train_full["year_month"].astype(str).tolist() == ["2025-02", "2025-03", "2025-04"]
    assert train_full.loc[0, "roll_mean_3"] == pytest.approx(100.0)
    assert train_full.loc[0, "roll_std_3"] == pytest.approx(0.0)  # min_periods=2

    assert train_full.loc[1, "roll_mean_3"] == pytest.approx(150.0)
    assert train_full.loc[1, "roll_std_3"] == pytest.approx(np.std([100.0, 200.0], ddof=1))

    assert train_full.loc[2, "roll_mean_3"] == pytest.approx(200.0)
    assert train_full.loc[2, "roll_std_3"] == pytest.approx(np.std([100.0, 200.0, 300.0], ddof=1))


def test_missing_months_do_not_create_fake_lag1_and_handle_reduced_forecast():
    """Un mois manquant empêche lag_1 d'être ffill dans train_full et bascule en qualité reduced si final."""
    df = _make_series(
        "WFP", "Lac", "Bol", "Millet",
        ["2025-01", "2025-02", "2025-04"],
        [200.0, 220.0, 260.0],
    )
    train_full, latest = run_forecasting_pipeline(df)

    # 2025-04 n'a pas de relevé en 2025-03 : il ne doit pas entrer dans train_full avec un faux lag_1
    assert "2025-04" not in train_full["year_month"].astype(str).tolist()
    assert len(latest) == 1
    assert latest.iloc[0]["forecast_quality"] == "reduced"
    assert latest.iloc[0]["forecast_month"] == "2025-05"


def test_short_series_handled_safely_without_crash():
    """Des séries de 1 ou 2 relevés ne doivent jamais faire planter fit_ridge_numpy."""
    df_one = _make_series("WFP", "Lac", "Bol", "Millet", ["2025-01"], [300.0])
    train_one, latest_one = run_forecasting_pipeline(df_one)
    assert train_one.empty
    assert latest_one.empty

    df_two = _make_series("WFP", "Lac", "Bol", "Millet", ["2025-01", "2025-02"], [300.0, 320.0])
    train_two, latest_two = run_forecasting_pipeline(df_two)
    assert len(train_two) == 1
    assert len(latest_two) == 1


def test_backtest_chronological_no_future_leakage():
    """Modifier les prix futurs après l'origine ne doit jamais modifier la prévision du modèle à cette origine."""
    months = pd.period_range("2024-01", periods=18, freq="M")
    vals = [300.0 + (i % 6) * 15.0 for i in range(18)]
    df = pd.DataFrame({
        "source": "WFP",
        "province": "Lac",
        "market_name": "Bol",
        "commodity_std": "Millet",
        "year_month": months,
        "value": vals,
    })
    res_a = run_backtest(df, n_origins=3, min_history=12, model_fn=run_forecasting_pipeline)

    df_future_mutated = df.copy()
    df_future_mutated.loc[df_future_mutated.index[-1], "value"] = 99_999.0
    res_b = run_backtest(df_future_mutated, n_origins=3, min_history=12, model_fn=run_forecasting_pipeline)

    # Les deux origines antérieures au dernier mois doivent être strictement identiques
    first_origins = sorted(res_a["origin"].unique())[:-1]
    a_sub = res_a[(res_a["method"] == "model") & (res_a["origin"].isin(first_origins))].sort_values("origin")
    b_sub = res_b[(res_b["method"] == "model") & (res_b["origin"].isin(first_origins))].sort_values("origin")
    assert np.allclose(a_sub["forecast"].values, b_sub["forecast"].values)


def test_interval_calibration_status_and_valid_widths():
    """Vérifie la calibration conforme sur historique suffisant et le statut sur petit échantillon."""
    # Petit échantillon (< 20 résidus OOS) -> interval_status == 'insufficient_history'
    short_df = _make_series(
        "WFP", "Lac", "Bol", "Millet",
        ["2025-01", "2025-02", "2025-03", "2025-04"],
        [200.0, 210.0, 220.0, 230.0],
    )
    _, latest_short = run_forecasting_pipeline(short_df)
    assert latest_short.iloc[0]["interval_status"] == "insufficient_history"
    assert latest_short.iloc[0]["ci_high_80"] > latest_short.iloc[0]["ci_low_80"]

    # Échantillon suffisant (>= 20 résidus OOS) -> interval_status == 'calibrated_80' et couverture proche de 80 %
    rng = np.random.default_rng(7)
    months = pd.period_range("2022-01", periods=48, freq="M")
    rows = []
    for prov in ("Lac", "Salamat", "Logone"):
        for m in months:
            rows.append(("WFP", prov, f"{prov} m", "Millet", m, 300.0 + float(rng.normal(0, 25.0))))
    long_df = pd.DataFrame(rows, columns=["source", "province", "market_name", "commodity_std", "year_month", "value"])
    _, latest_long = run_forecasting_pipeline(long_df)
    assert (latest_long["interval_status"] == "calibrated_80").all()
    assert (latest_long["ci_high_80"] > latest_long["ci_low_80"]).all()

    res = run_backtest(long_df, n_origins=6, min_history=18, model_fn=run_forecasting_pipeline)
    cov = res[res["method"] == "model"]["in_ci"].mean()
    assert 0.65 <= cov <= 0.95





def test_conformal_q80_uses_finite_sample_order_statistic():
    """Le quantile conformel fini doit prendre le rang ceil((n+1)*0.8), sans interpolation."""
    errors = np.arange(1.0, 21.0)
    assert _conformal_q80(errors) == 17.0
    assert _conformal_q80(np.array([1.0, 2.0, np.nan, np.inf, 3.0])) == 3.0
    with pytest.raises(ValueError):
        _conformal_q80(np.array([np.nan, np.inf]))


def test_reduced_forecast_is_explicit_and_uses_wider_interval():
    """Une série dont le dernier mois manque est réduite et reçoit un intervalle élargi."""
    rng = np.random.default_rng(19)
    months = pd.period_range("2022-01", periods=48, freq="M")
    rows = []
    for market in ("Bol", "Aboudeia", "Am-Timan"):
        for i, month in enumerate(months):
            if market == "Am-Timan" and i == len(months) - 1:
                continue
            value = 500.0 + i * 1.5 + float(rng.normal(0, 18.0))
            rows.append(("WFP", "Salamat", market, "Millet", month, value))
    df = pd.DataFrame(
        rows,
        columns=["source", "province", "market_name", "commodity_std", "year_month", "value"],
    )
    _, latest = run_forecasting_pipeline(df)
    reduced = latest[latest["market_name"] == "Am-Timan"].iloc[0]
    standard = latest[latest["market_name"] == "Bol"].iloc[0]
    assert reduced["forecast_quality"] == "reduced"
    assert reduced["interval_status"] == "wide_reduced"
    assert standard["forecast_quality"] == "standard"
    assert standard["interval_status"] == "calibrated_80"
    assert (reduced["ci_high_80"] - reduced["ci_low_80"]) > (
        standard["ci_high_80"] - standard["ci_low_80"]
    )
