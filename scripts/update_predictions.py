"""
Script d'automatisation mensuelle post-collecte (MarketsAgent -> table_public -> Gold).
Met à jour table_ml_forecasts et table_ml_credit_passport sur Supabase.
"""
import os
import sys
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport


def _upsert_supabase_rest(table_name: str, records: list[dict], conflict_cols: str):
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}?on_conflict={conflict_cols}"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    chunk_size = 500
    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
        resp.raise_for_status()


def main():
    print(f"[FreeData.AI] Démarrage du pipeline mensuel (Backend: {settings.data_backend})...")
    kg_df = load_clean_markets()
    print(f"[FreeData.AI] {len(kg_df)} observations homogènes XAF/kg chargées.")

    _, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    print(f"[FreeData.AI] {len(forecast_df)} prévisions t+1 et {len(passport_df)} scores Credit Passport calculés.")

    fc_cols = [
        "source", "province", "market_name", "commodity_std",
        "last_observed_month", "value", "forecast_month",
        "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae",
    ]
    fc_export = forecast_df[fc_cols].rename(columns={"value": "last_observed_price"})

    cp_cols = [
        "province", "commodity_std", "credit_score", "grade",
        "ltv_ratio", "policy_recommendation",
        "s_stability", "s_drawdown", "s_logistics", "s_coverage",
        "median_price", "cv_pct", "max_drawdown_pct", "obs_months",
    ]

    if settings.data_backend == "supabase_rest":
        _upsert_supabase_rest(
            "table_ml_forecasts",
            fc_export.to_dict(orient="records"),
            "source,province,market_name,commodity_std",
        )
        _upsert_supabase_rest(
            "table_ml_credit_passport",
            passport_df[cp_cols].to_dict(orient="records"),
            "province,commodity_std",
        )
        print("[FreeData.AI] Tables Gold Supabase mises à jour via HTTPS REST.")
    elif settings.data_backend == "supabase":
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.supabase_db_url)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE public.table_ml_forecasts RESTART IDENTITY;"))
            conn.execute(text("TRUNCATE TABLE public.table_ml_credit_passport RESTART IDENTITY;"))
        fc_export.to_sql("table_ml_forecasts", engine, schema="public", if_exists="append", index=False)
        passport_df[cp_cols].to_sql("table_ml_credit_passport", engine, schema="public", if_exists="append", index=False)
        print("[FreeData.AI] Tables Gold Supabase mises à jour via PostgreSQL.")
    else:
        fc_export.to_csv("freedata_forecasts_t1.csv", index=False)
        passport_df[cp_cols].to_csv("freedata_credit_passport.csv", index=False)
        print("[FreeData.AI] Exports CSV locaux mis à jour (mode hors-ligne).")


if __name__ == "__main__":
    main()