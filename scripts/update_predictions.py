"""
Script d'automatisation mensuelle post-collecte (MarketsAgent -> table_public -> Gold).
Met à jour table_ml_forecasts et table_ml_credit_passport sur Supabase.

Le modèle (src/forecasting.py, src/credit_passport.py) est utilisé tel quel : ce script
ne fait que l'exécuter et publier ses sorties.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport

FORECAST_SRC_COLS = [
    "source", "province", "market_name", "commodity_std",
    "last_observed_month", "value", "forecast_month",
    "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae",
    # Sorties déjà calculées par le modèle pour le dernier mois observé (alertes de tension).
    "predicted_price", "deviation_pct",
    # 'standard' ou 'reduced' (dernier relevé après un trou) : sql/06 doit être appliqué avant ce script.
    "forecast_quality",
    # Statut de calibration de l'intervalle à 80 % : sql/15 doit être appliqué avant ce script.
    "interval_status",
]

PASSPORT_COLS = [
    "province", "commodity_std", "credit_score", "grade",
    "ltv_ratio", "policy_recommendation",
    "s_stability", "s_drawdown", "s_logistics", "s_coverage",
    "median_price", "cv_pct", "max_drawdown_pct", "obs_months",
]


def build_exports(forecast_df, passport_df):
    """Sélectionne/renomme les colonnes à publier. Fonction pure (testable)."""
    fc_export = forecast_df[FORECAST_SRC_COLS].rename(columns={"value": "last_observed_price"})
    cp_export = passport_df[PASSPORT_COLS].copy()
    return fc_export, cp_export


def _records(df) -> list[dict]:
    """DataFrame -> liste de dicts JSON valides (NaN/inf deviennent null)."""
    return json.loads(df.to_json(orient="records"))


def _headers(extra: dict | None = None) -> dict:
    key = settings.write_key
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if extra:
        headers.update(extra)
    return headers


def _upsert_supabase_rest(table_name: str, records: list[dict], conflict_cols: str):
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}?on_conflict={conflict_cols}"
    headers = _headers({"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"})
    chunk_size = 500
    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
        resp.raise_for_status()


def _purge_stale_rest(table_name: str, run_ts: str):
    """Supprime les lignes non mises à jour par ce run (séries disparues).

    À n'appeler qu'APRÈS le succès de tous les upserts du run.
    """
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}"
    resp = requests.delete(endpoint, headers=_headers(), params={"date_calcul": f"lt.{run_ts}"}, timeout=30)
    resp.raise_for_status()


def main():
    print(f"[FreeData.AI] Démarrage du pipeline mensuel (Backend: {settings.data_backend})...")
    kg_df = load_clean_markets()
    print(f"[FreeData.AI] {len(kg_df)} observations homogènes XAF/kg chargées.")

    _, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    print(f"[FreeData.AI] {len(forecast_df)} prévisions t+1 et {len(passport_df)} scores Credit Passport calculés.")

    fc_export, cp_export = build_exports(forecast_df, passport_df)

    if settings.data_backend == "supabase_rest":
        if not settings.supabase_service_key:
            print("[FreeData.AI] ATTENTION : SUPABASE_SERVICE_ROLE_KEY absente, l'écriture utilise SUPABASE_KEY "
                  "(refusée si le RLS est activé).")
        # Horodatage UTC naïf : les colonnes date_calcul sont des TIMESTAMP WITHOUT TIME ZONE.
        run_ts = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()
        fc_records = [dict(r, date_calcul=run_ts) for r in _records(fc_export)]
        cp_records = [dict(r, date_calcul=run_ts) for r in _records(cp_export)]

        _upsert_supabase_rest("table_ml_forecasts", fc_records, "source,province,market_name,commodity_std")
        _upsert_supabase_rest("table_ml_credit_passport", cp_records, "province,commodity_std")
        if fc_records and cp_records:
            _purge_stale_rest("table_ml_forecasts", run_ts)
            _purge_stale_rest("table_ml_credit_passport", run_ts)
        print("[FreeData.AI] Tables Gold Supabase mises à jour via HTTPS REST (séries disparues purgées).")
    elif settings.data_backend == "supabase":
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.supabase_db_url)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE public.table_ml_forecasts RESTART IDENTITY;"))
            conn.execute(text("TRUNCATE TABLE public.table_ml_credit_passport RESTART IDENTITY;"))
        fc_export.to_sql("table_ml_forecasts", engine, schema="public", if_exists="append", index=False)
        cp_export.to_sql("table_ml_credit_passport", engine, schema="public", if_exists="append", index=False)
        print("[FreeData.AI] Tables Gold Supabase mises à jour via PostgreSQL.")
    else:
        fc_export.to_csv("freedata_forecasts_t1.csv", index=False)
        cp_export.to_csv("freedata_credit_passport.csv", index=False)
        print("[FreeData.AI] Exports CSV locaux mis à jour (mode hors-ligne).")


if __name__ == "__main__":
    main()
