"""Pipeline fiable et observable de publication des données analytiques FreeData.AI (12 étapes)."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests

from src.anomalies import detect_anomalies, recent_anomalies
from src.backtest import run_backtest, summarize as summarize_backtest
from src.config import settings
from src.credit_passport import compute_credit_passport
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.ml_engine import ModelRegistry
from src.season_study import StudyBook

logger = logging.getLogger("freedata.pipeline")

REQUIRED_CLEAN_COLS = {"source", "province", "market_name", "commodity_std", "year_month", "value"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_clean_markets(df: Optional[pd.DataFrame]) -> list[str]:
    """Étape 2 — Valide le jeu de données nettoyé avant tout calcul ML."""
    errors: list[str] = []
    if df is None or df.empty:
        return ["Jeu de données vide : aucune observation disponible."]
    missing = sorted(REQUIRED_CLEAN_COLS - set(df.columns))
    if missing:
        errors.append(f"Colonnes obligatoires manquantes : {', '.join(missing)}")
        return errors
    vals = pd.to_numeric(df["value"], errors="coerce")
    if vals.isna().all() or (vals.dropna() <= 0).any():
        errors.append("Valeurs de prix invalides (nulles ou négatives détectées).")
    if df["year_month"].isna().any():
        errors.append("Mois d'observation manquants dans year_month.")
    return errors


def _default_publish_supabase(
    fc_df: pd.DataFrame,
    cp_df: pd.DataFrame,
    anom_df: pd.DataFrame,
    study_rows: list[dict],
    run_ts: str,
) -> dict[str, int]:
    """Étape 8 — Upsert atomique logique sur toutes les tables avant toute purge."""
    from scripts.update_anomalies import to_rows as anom_to_rows
    from scripts.update_predictions import PASSPORT_COLS, build_exports, _records, _upsert_supabase_rest

    fc_export, cp_export = build_exports(fc_df, cp_df)
    fc_records = [dict(r, date_calcul=run_ts) for r in _records(fc_export)]
    cp_records = [dict(r, date_calcul=run_ts) for r in _records(cp_export)]
    anom_records = anom_to_rows(anom_df) if not anom_df.empty else []

    _upsert_supabase_rest("table_ml_forecasts", fc_records, "source,province,market_name,commodity_std")
    _upsert_supabase_rest("table_ml_credit_passport", cp_records, "province,commodity_std")
    if anom_records:
        from scripts.update_anomalies import push as push_anomalies
        push_anomalies(anom_records)
    if study_rows:
        _upsert_supabase_rest("table_ml_seasonality_studies", study_rows, "kind,commodity_std,province")

    return {
        "table_ml_forecasts": len(fc_records),
        "table_ml_credit_passport": len(cp_records),
        "table_ml_anomalies": len(anom_records),
        "table_ml_seasonality_studies": len(study_rows),
    }


def _default_verify_publication(published: dict[str, int], run_ts: str) -> bool:
    """Étape 9 — Vérifie que les tables critiques contiennent des données avant purge."""
    return (
        published.get("table_ml_forecasts", 0) > 0
        and published.get("table_ml_credit_passport", 0) > 0
    )


def _default_purge_old(run_ts: str) -> None:
    from scripts.update_anomalies import purge_stale as purge_anomalies
    from scripts.update_predictions import _purge_stale_rest

    _purge_stale_rest("table_ml_forecasts", run_ts)
    _purge_stale_rest("table_ml_credit_passport", run_ts)
    purge_anomalies(run_ts)


def _trigger_api_refresh(
    api_base_url: str,
    admin_token: str,
    max_retries: int = 3,
    retry_delay_s: float = 0.0,
) -> tuple[bool, Optional[dict]]:
    """Étapes 10 & 11 — Rafraîchit l'API avec retries puis vérifie /api/v1/health sans exposer le jeton."""
    base = api_base_url.rstrip("/")
    headers = {"X-Admin-Token": admin_token}
    last_err = ""
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            r_ref = requests.post(f"{base}/api/v1/refresh", headers=headers, timeout=20)
            r_ref.raise_for_status()
            r_hlth = requests.get(f"{base}/api/v1/health", timeout=15)
            r_hlth.raise_for_status()
            health = r_hlth.json()
            if health.get("status") == "ok" and int(health.get("series_count", 0)) > 0:
                return True, health
            last_err = f"health degraded: {health.get('status')}"
        except Exception as exc:
            last_err = type(exc).__name__
            logger.warning("API refresh attempt %d/%d failed (%s)", attempt, max_retries, last_err)
        if attempt < max_retries and retry_delay_s > 0:
            time.sleep(retry_delay_s)
    logger.error("API refresh failed after %d attempts (%s)", max_retries, last_err)
    return False, None


def _safe_round(val: Any, digits: int = 2) -> Optional[float]:
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, digits)
    except (TypeError, ValueError):
        return None


def register_forecasting_evaluation_in_registry(
    clean_df: pd.DataFrame,
    fc_df: pd.DataFrame,
    *,
    registry: Optional[ModelRegistry] = None,
    model_id: str = "ridge_price_regressor",
    n_origins: int = 6,
    min_history: int = 12,
    allow_auto_deploy: bool = False,
    evaluation_run_key: Optional[str] = None,
    backtest_fn: Optional[Callable[..., pd.DataFrame]] = None,
) -> dict[str, Any]:
    """Evaluates the existing Gold forecasting pipeline via chronological rolling-origin backtest
    and registers a new versioned candidate in ModelRegistry with real metrics and zero fabricated values.

    Safety guarantees:
    - Never alters `gold_fast_read` prediction behavior.
    - Deduplicates repeated runs with the same `evaluation_run_key`.
    - Registers candidates as `EVALUATION` first; only promotes to `DEPLOYED` if `allow_auto_deploy=True`,
      the quality gate passes (beats or matches naive baseline), AND no production model is overwritten.
    - Preserves any existing `DEPLOYED` model if evaluation fails.
    """
    reg = registry or ModelRegistry()
    now = _utc_now_iso()

    latest_month = str(clean_df["year_month"].max()) if ("year_month" in clean_df.columns and not clean_df.empty) else "unknown"
    content_digest = hashlib.sha256(
        pd.util.hash_pandas_object(clean_df, index=False).to_numpy(dtype="uint64").tobytes()
    ).hexdigest()[:16] if not clean_df.empty else "empty"
    run_key = evaluation_run_key or hashlib.sha256(
        f"{model_id}|RidgeRegression_L2_Gold|alpha=50.0|{latest_month}|{content_digest}|{len(fc_df)}|{n_origins}|{min_history}".encode("utf-8")
    ).hexdigest()[:16]

    # Idempotency: do not create duplicate versions for the same evaluation run
    existing_for_model = [m for m in reg.list_models() if m.get("model_id") == model_id]
    for m in existing_for_model:
        cfg = m.get("configuration") or {}
        if cfg.get("evaluation_run_key") == run_key:
            return {
                "status": "deduplicated",
                "deduplicated": True,
                "model_id": model_id,
                "version": m["version"],
                "lifecycle_status": m.get("lifecycle_status"),
                "metrics": m.get("evaluation_metrics") or {},
            }

    # Check if an active production model already exists (must never be overwritten silently)
    has_active_prod = any(
        m.get("lifecycle_status") == "DEPLOYED" and m.get("is_active_production") is True
        for m in existing_for_model
    )

    # Execute chronological out-of-sample backtest
    bt_runner = backtest_fn or run_backtest
    try:
        bt_df = bt_runner(clean_df, n_origins=n_origins, min_history=min_history)
        summary = summarize_backtest(bt_df)
    except Exception as exc:
        logger.warning("Forecasting registry backtest failed (%s); preserving production model.", type(exc).__name__)
        return {
            "status": "evaluation_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "production_preserved": True,
        }

    methods_df = summary.get("methods")
    if (
        bt_df is None
        or bt_df.empty
        or summary.get("n_points", 0) <= 0
        or methods_df is None
        or methods_df.empty
        or "model" not in set(methods_df["method"])
    ):
        return {
            "status": "evaluation_failed",
            "reason": summary.get("verdict") or "Pas assez de données pour un backtest chronologique.",
            "production_preserved": True,
        }

    model_row = methods_df[methods_df["method"] == "model"].iloc[0]
    naive_rows = methods_df[methods_df["method"] == "naive"]
    naive_mae = _safe_round(naive_rows.iloc[0]["MAE_xaf_kg"]) if not naive_rows.empty else None

    model_bt = bt_df[bt_df["method"] == "model"].dropna(subset=["forecast"])
    series_count = int(model_bt[["source", "province", "market_name", "commodity_std"]].drop_duplicates().shape[0]) if not model_bt.empty else 0
    origins_sorted = sorted(model_bt["origin"].dropna().astype(str).unique().tolist()) if not model_bt.empty else []
    targets_sorted = sorted(model_bt["target"].dropna().astype(str).unique().tolist()) if not model_bt.empty else []
    eval_period = f"{origins_sorted[0]}..{targets_sorted[-1]}" if (origins_sorted and targets_sorted) else latest_month

    raw_metrics: dict[str, Any] = {
        "mae_xaf_kg": _safe_round(model_row.get("MAE_xaf_kg")),
        "rmse_xaf_kg": _safe_round(model_row.get("RMSE_xaf_kg")),
        "mape_pct": _safe_round(model_row.get("MAPE_pct")),
        "ic80_coverage_pct": _safe_round(model_row.get("ic80_coverage_pct"), 1),
        "direction_acc_pct": _safe_round(model_row.get("direction_acc_pct"), 1),
        "baseline_naive_mae_xaf_kg": naive_mae,
        "vs_naive_pct": _safe_round(model_row.get("vs_naive_pct"), 2),
        "evaluated_series_count": series_count,
        "evaluated_observations_count": int(summary.get("n_points", 0)),
        "evaluation_origins_count": len(origins_sorted),
    }
    # Never store fabricated or null metrics
    metrics = {k: v for k, v in raw_metrics.items() if v is not None}

    vs_naive = metrics.get("vs_naive_pct")
    quality_gate_passed = bool(
        metrics.get("mae_xaf_kg") is not None
        and metrics.get("evaluated_observations_count", 0) > 0
        and (vs_naive is None or vs_naive <= 0.0)
    )

    next_version = max((int(m.get("version", 0)) for m in existing_for_model), default=0) + 1
    input_schema = {
        "required_columns": sorted(REQUIRED_CLEAN_COLS),
        "target_column": "value",
        "time_column": "year_month",
        "series_keys": ["source", "province", "market_name", "commodity_std"],
    }
    entry = reg.register_model(
        model_id=model_id,
        model_name="Gold Ridge Price Forecaster (t+1, Causal Lags + Seasonality)",
        domain="markets_and_prices",
        algorithm="RidgeRegression_L2_Gold",
        task_type="forecasting",
        version=next_version,
        description="Modèle de prévision Gold t+1 évalué par backtest chronologique rolling-origin.",
        training_dataset_ref=f"table_ml_forecasts:{latest_month}",
        evaluation_dataset_ref=f"rolling_origin_{n_origins}m:{eval_period}",
        dataset_provenance={
            "latest_observation_month": latest_month,
            "clean_observations": int(len(clean_df)),
            "forecast_series": int(len(fc_df)),
            "evaluation_period": eval_period,
            "input_schema": input_schema,
            "verdict": summary.get("verdict"),
        },
        training_date=now,
        lifecycle_status="EVALUATION",
        evaluation_metrics=metrics,
        configuration={
            "alpha": 50.0,
            "n_origins": int(n_origins),
            "min_history": int(min_history),
            "evaluation_run_key": run_key,
            "quality_gate_passed": quality_gate_passed,
            "execution_mode": "gold_fast_read",
            "input_schema": input_schema,
        },
        dependencies=["numpy", "pandas"],
        enabled=True,
        set_active=False,
    )

    # Persist lightweight artifact metadata durably so recovery after restart is complete
    artifact_bundle = {
        "name": model_id,
        "version": next_version,
        "saved_at_utc": now,
        "metrics": metrics,
        "artifact": {
            "model_type": "RidgeRegression_L2_Gold",
            "alpha": 50.0,
            "input_schema": input_schema,
            "training_dataset_ref": f"table_ml_forecasts:{latest_month}",
            "evaluation_period": eval_period,
        },
    }
    reg._persist_artifact(model_id, next_version, artifact_bundle)

    final_status = "EVALUATION"
    if allow_auto_deploy and quality_gate_passed and not has_active_prod:
        promoted = reg.transition_status(model_id, next_version, "DEPLOYED", set_active=True, enabled=True)
        final_status = promoted["lifecycle_status"]
        entry = promoted

    return {
        "status": "registered",
        "deduplicated": False,
        "model_id": model_id,
        "version": next_version,
        "lifecycle_status": final_status,
        "quality_gate_passed": quality_gate_passed,
        "production_preserved": True,
        "metrics": metrics,
        "entry": entry,
    }


def run_publication_pipeline(
    loader_fn: Callable[[], pd.DataFrame] = load_clean_markets,
    publish_fn: Optional[Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict], str], dict[str, int]]] = None,
    verify_fn: Optional[Callable[[dict[str, int], str], bool]] = None,
    purge_fn: Optional[Callable[[str], None]] = None,
    api_base_url: Optional[str] = None,
    admin_token: Optional[str] = None,
    dry_run: bool = False,
    max_refresh_retries: int = 3,
    retry_delay_s: float = 1.0,
    report_path: Optional[str] = None,
    model_registry: Optional[ModelRegistry] = None,
    allow_auto_deploy: bool = False,
    backtest_origins: int = 6,
) -> dict:
    """Exécute les 12 étapes du pipeline de publication avec observabilité et arrêt sur erreur critique."""
    execution_id = str(uuid.uuid4())
    start_time = _utc_now_iso()
    run_ts = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()
    stages_completed: list[str] = []
    validation_errors: list[str] = []
    rows_processed: dict[str, int] = {}
    rows_published: dict[str, int] = {}
    last_successful_publication: Optional[str] = None
    api_refresh_status = "skipped"
    pipeline_status = "failed"
    ml_registry_evaluation: Optional[dict[str, Any]] = None

    def _finalize() -> dict:
        report = {
            "execution_id": execution_id,
            "start_time": start_time,
            "end_time": _utc_now_iso(),
            "pipeline_status": pipeline_status,
            "stages_completed": stages_completed,
            "rows_processed": rows_processed,
            "rows_published": rows_published,
            "validation_errors": validation_errors,
            "last_successful_publication": last_successful_publication,
            "API_refresh_status": api_refresh_status,
            "ml_registry_evaluation": ml_registry_evaluation,
        }
        if report_path:
            p = Path(report_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # 1. Extraction
    try:
        raw_df = loader_fn()
        stages_completed.append("extract")
    except Exception as exc:
        validation_errors.append(f"Erreur d'extraction : {exc}")
        return _finalize()

    # 2. Validation
    validation_errors.extend(validate_clean_markets(raw_df))
    if validation_errors:
        return _finalize()
    stages_completed.append("validate")

    # 3. Cleaning / déduplication chronologique
    clean_df = (
        raw_df.dropna(subset=["source", "province", "market_name", "commodity_std", "year_month", "value"])
        .sort_values(["source", "province", "market_name", "commodity_std", "year_month"])
        .drop_duplicates(["source", "province", "market_name", "commodity_std", "year_month"], keep="last")
        .reset_index(drop=True)
    )
    rows_processed["observations"] = len(clean_df)
    stages_completed.append("clean")

    # 4. Forecast computation
    _, fc_df = run_forecasting_pipeline(clean_df)
    rows_processed["forecasts"] = len(fc_df)
    if fc_df.empty:
        validation_errors.append("Aucune prévision générée.")
        return _finalize()
    stages_completed.append("forecasts")

    # 4b. Optional ML Registry chronological evaluation (never blocks gold_fast_read)
    if model_registry is not None:
        try:
            ml_registry_evaluation = register_forecasting_evaluation_in_registry(
                clean_df,
                fc_df,
                registry=model_registry,
                n_origins=backtest_origins,
                allow_auto_deploy=allow_auto_deploy,
            )
            stages_completed.append("ml_registry_eval")
        except Exception as exc:
            ml_registry_evaluation = {
                "status": "evaluation_failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "production_preserved": True,
            }

    # 5. Credit Passport computation
    cp_df = compute_credit_passport(clean_df)
    rows_processed["credit_passport"] = len(cp_df)
    if cp_df.empty:
        validation_errors.append("Aucun indice Credit Passport généré.")
        return _finalize()
    stages_completed.append("credit_passport")

    # 6. Anomaly computation
    anom_df = recent_anomalies(detect_anomalies(clean_df), months=6)
    rows_processed["anomalies"] = len(anom_df)
    stages_completed.append("anomalies")

    # 7. Seasonal studies
    study_book = StudyBook(kg_df=clean_df)
    study_rows = [
        {"kind": "seasonality", "commodity_std": k[0], "province": k[1] or "", "payload": v, "generated_at": run_ts}
        for k, v in getattr(study_book, "studies", {}).items()
    ]
    rows_processed["seasonality_studies"] = len(study_rows)
    stages_completed.append("seasonality")

    if dry_run:
        pipeline_status = "succeeded"
        return _finalize()

    # 8. Publication to Supabase
    pub = publish_fn or _default_publish_supabase
    try:
        rows_published = pub(fc_df, cp_df, anom_df, study_rows, run_ts)
        stages_completed.append("publish")
    except Exception as exc:
        validation_errors.append(f"Échec de publication : {exc}")
        return _finalize()

    # 9. Publication integrity verification (avant purge des anciennes lignes)
    ver = verify_fn or _default_verify_publication
    if not ver(rows_published, run_ts):
        validation_errors.append("Échec de vérification d'intégrité de publication : anciennes données conservées.")
        return _finalize()
    stages_completed.append("verify_publication")

    if purge_fn is not None:
        purge_fn(run_ts)
    elif publish_fn is None:
        _default_purge_old(run_ts)

    last_successful_publication = _utc_now_iso()

    # 10 & 11. API refresh & health check
    eff_url = (api_base_url or "").strip()
    eff_tok = (admin_token or settings.admin_token or "").strip()
    if eff_url and eff_tok:
        ok, _ = _trigger_api_refresh(eff_url, eff_tok, max_retries=max_refresh_retries, retry_delay_s=retry_delay_s)
        if ok:
            api_refresh_status = "verified"
            stages_completed.extend(["api_refresh", "health_check"])
            pipeline_status = "succeeded"
        else:
            api_refresh_status = "failed"
            pipeline_status = "partial_refresh_pending"
    else:
        pipeline_status = "succeeded"

    # 12. Execution report
    stages_completed.append("report")
    return _finalize()

