import numpy as np
import pandas as pd


def fit_ridge_numpy(X: np.ndarray, y: np.ndarray, alpha: float = 50.0) -> np.ndarray:
    """Résout (X^T X + alpha * I) w = X^T y en pur NumPy sans pénaliser l'intercept."""
    n_features = X.shape[1]
    reg = np.eye(n_features) * alpha
    reg[0, 0] = 0.0
    return np.linalg.solve(X.T @ X + reg, X.T @ y)


def run_forecasting_pipeline(kg_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Construit la grille calendaire complète, entraîne le modèle hybride Mean-Reversion
    (65% Moyenne Mobile 3m + 35% Régression Log-Return) et génère les prévisions t+1.
    """
    min_ym, max_ym = kg_df["year_month"].min(), kg_df["year_month"].max()
    all_months = pd.period_range(min_ym, max_ym + 1, freq="M")

    series_meta = kg_df[["source", "province", "market_name", "commodity_std"]].drop_duplicates()
    series_meta["key"] = 1
    grid = pd.merge(series_meta, pd.DataFrame({"year_month": all_months, "key": 1}), on="key").drop("key", axis=1)

    panel = pd.merge(
        grid,
        kg_df[["source", "province", "market_name", "commodity_std", "year_month", "value"]],
        on=["source", "province", "market_name", "commodity_std", "year_month"],
        how="left",
    ).sort_values(["source", "province", "market_name", "commodity_std", "year_month"]).reset_index(drop=True)

    grp = panel.groupby(["source", "province", "market_name", "commodity_std"])["value"]
    panel["lag_1"], panel["lag_2"], panel["lag_3"] = grp.shift(1), grp.shift(2), grp.shift(3)
    panel["value_ffill2"] = grp.ffill(limit=2)
    grp_ff = panel.groupby(["source", "province", "market_name", "commodity_std"])["value_ffill2"]
    panel["roll_mean_3"] = grp_ff.shift(1).rolling(3, min_periods=1).mean()
    panel["roll_std_3"] = grp_ff.shift(1).rolling(3, min_periods=2).std().fillna(0)

    panel["ret_1m"] = np.log(panel["lag_1"] / panel["lag_2"]).fillna(0.0)
    panel["ret_2m"] = np.log(panel["lag_2"] / panel["lag_3"]).fillna(0.0)
    panel["log_ratio_roll3"] = np.log(panel["lag_1"] / panel["roll_mean_3"]).fillna(0.0)
    panel["rel_vol_3"] = (panel["roll_std_3"] / (panel["roll_mean_3"] + 1e-6)).fillna(0.0)

    train_full = panel[(panel["year_month"] <= max_ym) & panel["value"].notna() & panel["lag_1"].notna()].copy()
    y_train_logret = np.log(train_full["value"].values / train_full["lag_1"].values)

    num_cols = ["ret_1m", "ret_2m", "log_ratio_roll3", "rel_vol_3"]
    cat_cols = ["source", "province", "commodity_std"]
    X_cat_df = pd.get_dummies(train_full[cat_cols], dtype=float)
    dummy_columns = X_cat_df.columns.tolist()

    X_train = np.column_stack([np.ones(len(train_full)), train_full[num_cols].values, X_cat_df.values])
    weights = fit_ridge_numpy(X_train, y_train_logret, alpha=50.0)

    pred_logret_hist = np.clip(X_train @ weights, -0.5, 0.5)
    pred_mr_hist = train_full["lag_1"].values * np.exp(pred_logret_hist)
    roll3 = train_full["roll_mean_3"].fillna(train_full["lag_1"]).values
    train_full["predicted_price"] = np.round(0.65 * roll3 + 0.35 * pred_mr_hist, 2)
    train_full["residual_xaf"] = np.round(train_full["value"] - train_full["predicted_price"], 2)
    train_full["deviation_pct"] = np.round((train_full["residual_xaf"] / train_full["predicted_price"]) * 100.0, 2)

    latest = train_full.sort_values("year_month").groupby(["source", "province", "market_name", "commodity_std"]).tail(1).copy()
    latest["f_roll_mean_3"] = latest[["value", "lag_1", "lag_2"]].mean(axis=1)
    latest["f_roll_std_3"] = latest[["value", "lag_1", "lag_2"]].std(axis=1).fillna(0)

    next_num = np.column_stack([
        np.log(latest["value"] / latest["lag_1"]).fillna(0.0).values,
        np.log(latest["lag_1"] / latest["lag_2"]).fillna(0.0).values,
        np.log(latest["value"] / latest["f_roll_mean_3"]).fillna(0.0).values,
        (latest["f_roll_std_3"] / (latest["f_roll_mean_3"] + 1e-6)).fillna(0.0).values,
    ])
    next_cat = pd.get_dummies(latest[cat_cols], dtype=float).reindex(columns=dummy_columns, fill_value=0.0).values
    X_next = np.column_stack([np.ones(len(latest)), next_num, next_cat])

    pred_next_mr = latest["value"].values * np.exp(np.clip(X_next @ weights, -0.5, 0.5))
    latest["forecast_t1"] = np.round(0.65 * latest["f_roll_mean_3"].values + 0.35 * pred_next_mr, 2)
    latest["forecast_quality"] = "standard"

    # Séries dont le relevé le plus récent suit un trou (pas de mois précédent) : le modèle ci-dessus ne peut pas
    # l'utiliser. On les prévoit quand même, sans le terme de régression (il exige le mois d'avant) :
    # 65 % moyenne des 3 derniers relevés observés + 35 % dernier relevé. Qualité « reduced », intervalle élargi.
    keys = ["source", "province", "market_name", "commodity_std"]
    observed = panel[panel["value"].notna()]
    n_obs = observed.groupby(keys)["value"].transform("size")
    last_obs = observed[n_obs >= 3].groupby(keys).tail(1)  # moins de 3 relevés : pas de prévision
    newest = latest[keys + ["year_month"]].rename(columns={"year_month": "_std_ym"})
    orphans = last_obs.merge(newest, on=keys, how="left")
    orphans = orphans[orphans["_std_ym"].isna() | (orphans["year_month"] > orphans["_std_ym"])].drop(columns="_std_ym").copy()
    if not orphans.empty:
        mean3 = observed.groupby(keys)["value"].apply(lambda v: v.tail(3).mean()).rename("f_roll_mean_3").reset_index()
        orphans = orphans.drop(columns=["f_roll_mean_3"], errors="ignore").merge(mean3, on=keys, how="left")
        orphans["forecast_t1"] = np.round(0.65 * orphans["f_roll_mean_3"] + 0.35 * orphans["value"], 2)
        orphans["forecast_quality"] = "reduced"
        replaced = orphans[keys]
        latest = latest.merge(replaced.assign(_drop=1), on=keys, how="left")
        latest = latest[latest["_drop"].isna()].drop(columns="_drop")
        latest = pd.concat([latest, orphans[[c for c in latest.columns if c in orphans.columns]]], ignore_index=True)

    latest["last_observed_month"] = latest["year_month"].astype(str)
    latest["forecast_month"] = (latest["year_month"] + 1).astype(str)

    err_stats = train_full.groupby(["province", "commodity_std"])["residual_xaf"].apply(lambda s: np.mean(np.abs(s))).reset_index()
    err_stats.rename(columns={"residual_xaf": "hist_mae"}, inplace=True)
    latest = pd.merge(latest, err_stats, on=["province", "commodity_std"], how="left")
    latest["hist_mae"] = np.round(latest["hist_mae"].fillna(25.0), 2)
    # Intervalle plus large (x1.5) quand la prévision n'a pas pu utiliser le mois précédent.
    width = 1.28 * latest["hist_mae"] * np.where(latest["forecast_quality"] == "reduced", 1.5, 1.0)
    latest["ci_low_80"] = np.round(np.clip(latest["forecast_t1"] - width, 10.0, None), 2)
    latest["ci_high_80"] = np.round(latest["forecast_t1"] + width, 2)

    return train_full, latest
