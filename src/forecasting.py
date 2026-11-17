from typing import Optional

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

    keys = ["source", "province", "market_name", "commodity_std"]
    series_meta = kg_df[keys].drop_duplicates()
    series_meta["key"] = 1
    grid = pd.merge(series_meta, pd.DataFrame({"year_month": all_months, "key": 1}), on="key").drop("key", axis=1)

    panel = pd.merge(
        grid,
        kg_df[keys + ["year_month", "value"]],
        on=keys + ["year_month"],
        how="left",
    ).sort_values(keys + ["year_month"]).reset_index(drop=True)

    grp = panel.groupby(keys, sort=False)["value"]
    panel["lag_1"], panel["lag_2"], panel["lag_3"] = grp.shift(1), grp.shift(2), grp.shift(3)
    panel["value_ffill2"] = grp.ffill(limit=2)
    grp_ff = panel.groupby(keys, sort=False)["value_ffill2"]
    panel["roll_mean_3"] = grp_ff.transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    panel["roll_std_3"] = grp_ff.transform(lambda s: s.shift(1).rolling(3, min_periods=2).std()).fillna(0.0)

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
    weights = fit_ridge_numpy(X_train, y_train_logret, alpha=50.0) if len(train_full) > 0 else np.zeros(X_train.shape[1])

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
        # Alertes : prix attendu = moyenne des (jusqu'à) 3 relevés PRÉCÉDENTS ; écart du dernier relevé par rapport à cette attente.
        prior = observed.groupby(keys)["value"].apply(lambda v: v.iloc[:-1].tail(3).mean()).rename("predicted_price").reset_index()
        orphans = orphans.drop(columns=["predicted_price"], errors="ignore").merge(prior, on=keys, how="left")
        orphans["predicted_price"] = orphans["predicted_price"].round(2)
        orphans["residual_xaf"] = np.round(orphans["value"] - orphans["predicted_price"], 2)
        orphans["deviation_pct"] = np.round(orphans["residual_xaf"] / orphans["predicted_price"] * 100.0, 2)
        replaced = orphans[keys]
        latest = latest.merge(replaced.assign(_drop=1), on=keys, how="left")
        latest = latest[latest["_drop"].isna()].drop(columns="_drop")
        latest = pd.concat([latest, orphans[[c for c in latest.columns if c in orphans.columns]]], ignore_index=True)

    latest["last_observed_month"] = latest["year_month"].astype(str)
    latest["forecast_month"] = (latest["year_month"] + 1).astype(str)

    # Calibration conforme hors-échantillon (split chronologique 70/30 sur train_full) :
    # on évite d'utiliser le MAE in-sample qui sous-estime l'erreur future sur les séries volatiles.
    oos_residuals = pd.DataFrame(columns=["province", "commodity_std", "abs_err"])
    unique_ym = sorted(train_full["year_month"].unique())
    if len(unique_ym) >= 6:
        split_idx = max(3, int(len(unique_ym) * 0.7))
        if split_idx < len(unique_ym):
            split_ym = unique_ym[split_idx - 1]
            tr_cal = train_full[train_full["year_month"] <= split_ym]
            va_cal = train_full[train_full["year_month"] > split_ym]
            if len(tr_cal) >= 10 and len(va_cal) >= 5:
                X_tr_cal_cat = pd.get_dummies(tr_cal[cat_cols], dtype=float)
                cal_cols = X_tr_cal_cat.columns.tolist()
                X_tr_cal = np.column_stack([np.ones(len(tr_cal)), tr_cal[num_cols].values, X_tr_cal_cat.values])
                y_tr_cal = np.log(tr_cal["value"].values / tr_cal["lag_1"].values)
                w_cal = fit_ridge_numpy(X_tr_cal, y_tr_cal, alpha=50.0)

                X_va_cal_cat = pd.get_dummies(va_cal[cat_cols], dtype=float).reindex(columns=cal_cols, fill_value=0.0)
                X_va_cal = np.column_stack([np.ones(len(va_cal)), va_cal[num_cols].values, X_va_cal_cat.values])
                pred_va_logret = np.clip(X_va_cal @ w_cal, -0.5, 0.5)
                pred_va_mr = va_cal["lag_1"].values * np.exp(pred_va_logret)
                roll3_va = va_cal["roll_mean_3"].fillna(va_cal["lag_1"]).values
                pred_va = np.round(0.65 * roll3_va + 0.35 * pred_va_mr, 2)
                oos_residuals = pd.DataFrame({
                    "province": va_cal["province"].values,
                    "commodity_std": va_cal["commodity_std"].values,
                    "abs_err": np.abs(va_cal["value"].values - pred_va),
                })

    def _conformal_q80(errs: np.ndarray) -> float:
        n = len(errs)
        level = min(1.0, np.ceil((n + 1) * 0.80) / n)
        return float(np.quantile(errs, level))

    min_cal_n = 20
    pc_q80: dict[tuple[str, str], float] = {}
    pc_mae: dict[tuple[str, str], float] = {}
    c_q80: dict[str, float] = {}
    c_mae: dict[str, float] = {}
    global_q80: Optional[float] = None
    global_mae: Optional[float] = None

    if not oos_residuals.empty:
        for (p, c), g in oos_residuals.groupby(["province", "commodity_std"]):
            if len(g) >= min_cal_n:
                arr = g["abs_err"].to_numpy(float)
                pc_q80[(str(p), str(c))] = _conformal_q80(arr)
                pc_mae[(str(p), str(c))] = float(np.mean(arr))
        for c, g in oos_residuals.groupby("commodity_std"):
            if len(g) >= min_cal_n:
                arr = g["abs_err"].to_numpy(float)
                c_q80[str(c)] = _conformal_q80(arr)
                c_mae[str(c)] = float(np.mean(arr))
        if len(oos_residuals) >= min_cal_n:
            arr_all = oos_residuals["abs_err"].to_numpy(float)
            global_q80 = _conformal_q80(arr_all)
            global_mae = float(np.mean(arr_all))

    # Repli sur les résidus historiques si l'échantillon hors-échantillon est insuffisant
    in_mae = (
        train_full.groupby(["province", "commodity_std"])["residual_xaf"]
        .apply(lambda s: float(np.mean(np.abs(s))))
        .to_dict()
        if not train_full.empty
        else {}
    )

    widths: list[float] = []
    hist_maes: list[float] = []
    statuses: list[str] = []
    for _, row in latest.iterrows():
        key_pc = (str(row["province"]), str(row["commodity_std"]))
        comm_k = str(row["commodity_std"])
        qual = str(row.get("forecast_quality", "standard"))
        if key_pc in pc_q80:
            q_val, mae_val, st = pc_q80[key_pc], pc_mae[key_pc], "calibrated_80"
        elif comm_k in c_q80:
            q_val, mae_val, st = c_q80[comm_k], c_mae[comm_k], "calibrated_80"
        elif global_q80 is not None and global_mae is not None:
            q_val, mae_val, st = global_q80, global_mae, "calibrated_80"
        else:
            mae_val = in_mae.get(key_pc, 25.0)
            q_val = 1.60 * mae_val
            st = "insufficient_history"
        if qual == "reduced":
            q_val *= 1.5
            if st == "calibrated_80":
                st = "wide_reduced"
        widths.append(q_val)
        hist_maes.append(round(mae_val, 2))
        statuses.append(st)

    width_arr = np.asarray(widths, dtype=float)
    latest["hist_mae"] = hist_maes
    latest["interval_status"] = statuses
    latest["ci_low_80"] = np.round(np.clip(latest["forecast_t1"] - width_arr, 10.0, None), 2)
    latest["ci_high_80"] = np.round(latest["forecast_t1"] + width_arr, 2)

    return train_full, latest
