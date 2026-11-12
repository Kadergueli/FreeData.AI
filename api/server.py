import os
import sys
from contextlib import asynccontextmanager
from typing import Optional
import requests
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport
from src.ai_agent import FreeDataAIAgent

STATE = {}


def _fetch_gold_table(table_name: str) -> pd.DataFrame:
    """Lit une table Gold pré-calculée via l'API HTTPS Supabase (ultra-léger en RAM)."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}"
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Accept": "application/json",
    }
    rows = []
    offset = 0
    batch_size = 1000
    while True:
        resp = requests.get(
            endpoint,
            headers=headers,
            params={"select": "*", "limit": batch_size, "offset": offset},
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return pd.DataFrame(rows)


def refresh_engines():
    # Mode Production léger (Render Free < 512 Mo RAM) : lecture directe des tables Gold
    if settings.data_backend == "supabase_rest":
        fc_gold = _fetch_gold_table("table_ml_forecasts")
        cp_gold = _fetch_gold_table("table_ml_credit_passport")

        if not fc_gold.empty and not cp_gold.empty:
            fc_gold = fc_gold.rename(columns={"last_observed_price": "value"})
            # Reconstitution légère des alertes de tension (> +15%) depuis les écarts observés/prévus
            hist_light = fc_gold.copy()
            hist_light["year_month"] = hist_light["last_observed_month"]
            hist_light["predicted_price"] = hist_light["forecast_t1"]
            hist_light["deviation_pct"] = (
                ((hist_light["value"] - hist_light["predicted_price"]) / hist_light["predicted_price"]) * 100.0
            ).round(2)

            STATE["hist_df"] = hist_light
            STATE["forecast_df"] = fc_gold
            STATE["passport_df"] = cp_gold
            STATE["agent"] = FreeDataAIAgent(hist_light, fc_gold, cp_gold)
            STATE["mode"] = "gold_fast_read"
            return

    # Fallback complet (si tables Gold vides ou mode CSV local)
    kg_df = load_clean_markets()
    hist_df, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    STATE["hist_df"] = hist_df
    STATE["forecast_df"] = forecast_df
    STATE["passport_df"] = passport_df
    STATE["agent"] = FreeDataAIAgent(hist_df, forecast_df, passport_df)
    STATE["mode"] = "full_compute"


@asynccontextmanager
async def lifespan(app: FastAPI):
    refresh_engines()
    yield
    STATE.clear()


app = FastAPI(
    title="FreeData.AI API",
    description="API REST officielle de prévision des prix agricoles, alertes spatiales et Agricultural Credit Passport (Tchad).",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=1000)


class ChatResponse(BaseModel):
    reply: str
    intent: str
    entities: dict


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "ok",
        "backend": settings.data_backend,
        "engine_mode": STATE.get("mode", "unknown"),
        "series_count": len(STATE.get("forecast_df", [])),
        "passports_count": len(STATE.get("passport_df", [])),
    }


@app.post("/api/v1/refresh")
def manual_refresh():
    """Permet de recharger la mémoire de l'API après une mise à jour mensuelle des tables Gold."""
    refresh_engines()
    return {"status": "reloaded", "engine_mode": STATE.get("mode")}


@app.get("/api/v1/metadata")
def get_metadata():
    fc = STATE["forecast_df"]
    return {
        "provinces": sorted(fc["province"].dropna().unique().tolist()),
        "commodities": sorted(fc["commodity_std"].dropna().unique().tolist()),
    }


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest):
    agent: FreeDataAIAgent = STATE["agent"]
    result = agent.answer_with_metadata(payload.message)
    return ChatResponse(**result)


@app.get("/api/v1/forecasts")
def get_forecasts(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=2000),
):
    df = STATE["forecast_df"].copy()
    if province:
        df = df[df["province"].str.lower() == province.strip().lower()]
    if commodity:
        df = df[df["commodity_std"].str.lower() == commodity.strip().lower()]
    cols = [
        "source", "province", "market_name", "commodity_std",
        "last_observed_month", "value", "forecast_month",
        "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae",
    ]
    out = df[cols].rename(columns={"value": "last_observed_price"}).head(limit)
    return {"count": len(out), "items": out.to_dict(orient="records")}


@app.get("/api/v1/alerts")
def get_alerts(
    threshold_pct: float = Query(15.0, ge=0.0, le=500.0),
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    hist = STATE["hist_df"]
    recent = hist.sort_values("year_month").groupby(["source", "province", "market_name", "commodity_std"]).tail(1).copy()
    alerts = recent[recent["deviation_pct"] >= threshold_pct].copy()
    if province:
        alerts = alerts[alerts["province"].str.lower() == province.strip().lower()]
    if commodity:
        alerts = alerts[alerts["commodity_std"].str.lower() == commodity.strip().lower()]
    alerts = alerts.sort_values("deviation_pct", ascending=False).head(limit)
    alerts["month"] = alerts["year_month"].astype(str)
    cols = ["month", "source", "province", "market_name", "commodity_std", "value", "predicted_price", "deviation_pct"]
    return {"count": len(alerts), "items": alerts[cols].to_dict(orient="records")}


@app.get("/api/v1/credit-passport")
def get_credit_passport(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    loan_amount: int = Query(1_000_000, ge=10000),
):
    df = STATE["passport_df"].copy()
    if province:
        df = df[df["province"].str.lower() == province.strip().lower()]
    if commodity:
        df = df[df["commodity_std"].str.lower() == commodity.strip().lower()]
    df = df.sort_values("credit_score", ascending=False)
    df["recommended_max_loan_xaf"] = (df["ltv_ratio"] * loan_amount).astype(int)
    return {"count": len(df), "items": df.to_dict(orient="records")}