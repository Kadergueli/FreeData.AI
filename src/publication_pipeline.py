"""Pipeline fiable et observable de publication des données analytiques FreeData.AI (12 étapes)."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests

from src.anomalies import detect_anomalies, recent_anomalies
from src.config import settings
from src.credit_passport import compute_credit_passport
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
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

