import hmac
import logging
import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal, Optional
import requests
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport
from src.ai_agent import FreeDataAIAgent
from src.disclaimers import CREDIT_PASSPORT_DISCLAIMER
from src.freshness import filter_fresh

logger = logging.getLogger("freedata.api")

# État servi par l'API. Il n'est remplacé que d'un bloc (STATE.update) une fois le nouvel
# état entièrement construit : une requête ne voit jamais un mélange ancien/nouveau.
STATE: dict = {}
_REFRESH_LOCK = threading.Lock()
_RATE_LIMIT_BUCKET: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_LOCK = threading.Lock()


def check_rate_limit(request: Request, max_per_minute: int = 20):
    """Limite à `max_per_minute` requêtes par minute et par IP sur l'endpoint chat."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _RATE_LIMIT_LOCK:
        window = [ts for ts in _RATE_LIMIT_BUCKET.get(client_ip, ()) if now - ts < 60.0]
        if len(window) >= max_per_minute:
            _RATE_LIMIT_BUCKET[client_ip] = window
            raise HTTPException(
                status_code=429,
                detail="Trop de requêtes. Réessayez dans une minute.",
            )
        window.append(now)
        _RATE_LIMIT_BUCKET[client_ip] = window
        if len(_RATE_LIMIT_BUCKET) > 1000:
            stale_ips = [
                ip
                for ip, timestamps in _RATE_LIMIT_BUCKET.items()
                if not timestamps or now - timestamps[-1] >= 60.0
            ]
            for ip in stale_ips:
                _RATE_LIMIT_BUCKET.pop(ip, None)


enforce_rate_limit = check_rate_limit


def _chat_rate_limit_dependency(request: Request):
    # Encapsule check_rate_limit sans paramètre scalaire pour éviter l'exposition en query param.
    check_rate_limit(request)


def _fetch_gold_table(table_name: str) -> pd.DataFrame:
    """Lit une table Gold pré-calculée via l'API HTTPS Supabase (ultra-léger en RAM)."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}"
    headers = {
        "apikey": settings.read_key,
        "Authorization": f"Bearer {settings.read_key}",
        "Accept": "application/json",
    }
    rows = []
    offset = 0
    batch_size = 1000
    while True:
        resp = requests.get(
            endpoint,
            headers=headers,
            params={"select": "*", "order": "id", "limit": batch_size, "offset": offset},
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


def _finalize_state(hist_df, forecast_df, passport_df, mode: str, alerts_source: str) -> dict:
    """Applique le filtre de fraîcheur (couche API, le modèle n'est pas touché) et construit l'agent."""
    hist_df, _ = filter_fresh(hist_df, "year_month", settings.max_staleness_months)
    forecast_df, stale_excluded = filter_fresh(forecast_df, "last_observed_month", settings.max_staleness_months)
    return {
        "hist_df": hist_df,
        "forecast_df": forecast_df,
        "passport_df": passport_df,
        "agent": FreeDataAIAgent(hist_df, forecast_df, passport_df),
        "mode": mode,
        "alerts_source": alerts_source,
        "stale_excluded": stale_excluded,
    }


def build_state_from_gold(fc_gold: pd.DataFrame, cp_gold: pd.DataFrame) -> dict:
    """Construit l'état à partir des tables Gold (mode production léger)."""
    fc = fc_gold.rename(columns={"last_observed_price": "value"}).copy()
    for col in ("predicted_price", "deviation_pct"):
        if col in fc.columns:
            fc[col] = pd.to_numeric(fc[col], errors="coerce")

    hist = fc.copy()
    hist["year_month"] = hist["last_observed_month"]

    if {"predicted_price", "deviation_pct"} <= set(fc.columns) and fc["deviation_pct"].notna().any():
        # Écart observé / attendu calculé par le modèle pour le dernier mois observé.
        alerts_source = "stored"
    else:
        logger.warning(
            "Colonnes predicted_price/deviation_pct absentes ou vides dans table_ml_forecasts : "
            "alertes APPROXIMÉES (appliquer sql/03 puis relancer scripts/update_predictions.py)."
        )
        hist["predicted_price"] = hist["forecast_t1"]
        hist["deviation_pct"] = (
            ((hist["value"] - hist["predicted_price"]) / hist["predicted_price"]) * 100.0
        ).round(2)
        alerts_source = "approximated"

    return _finalize_state(hist, fc, cp_gold, "gold_fast_read", alerts_source)


def build_state_full() -> dict:
    """Recalcule tout depuis les données brutes (CSV local / PostgreSQL). Lourd en mémoire."""
    kg_df = load_clean_markets()
    hist_df, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    return _finalize_state(hist_df, forecast_df, passport_df, "full_compute", "model_residual")


def build_state() -> dict:
    if settings.data_backend == "supabase_rest":
        fc_gold = _fetch_gold_table("table_ml_forecasts")
        cp_gold = _fetch_gold_table("table_ml_credit_passport")
        if fc_gold.empty or cp_gold.empty:
            # Pas de repli vers un recalcul complet : il saturerait la mémoire d'un hébergement gratuit.
            raise RuntimeError(
                "Tables Gold vides : exécuter scripts/update_predictions.py avant de démarrer l'API."
            )
        return build_state_from_gold(fc_gold, cp_gold)
    return build_state_full()


def refresh_engines():
    """Reconstruit l'état puis le remplace d'un bloc. En cas d'échec, l'ancien état reste servi."""
    with _REFRESH_LOCK:
        new_state = build_state()
        STATE.update(new_state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.read_key_is_privileged:
        logger.warning(
            "L'API lit Supabase avec la clé service_role (SUPABASE_KEY absente). "
            "Utiliser une clé publique (anon) en lecture seule : voir sql/04_rls_policies.sql."
        )
    try:
        refresh_engines()
    except Exception:
        logger.exception("Chargement initial impossible : l'API démarre en mode dégradé (503).")
    yield
    STATE.clear()


app = FastAPI(
    title="FreeData.AI API",
    description="API REST officielle de prévision des prix agricoles, alertes spatiales et Agricultural Credit Passport (Tchad).",
    version="1.2.0",
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


def get_state() -> dict:
    """Instantané de l'état servi ; 503 explicite si les données ne sont pas chargées."""
    snapshot = dict(STATE)
    if "agent" not in snapshot:
        raise HTTPException(status_code=503, detail="Données non chargées. Réessayez dans quelques instants.")
    return snapshot


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    tier: Literal["free", "premium"] = Field(default="free")


class ChatResponse(BaseModel):
    reply: str
    intent: str
    entities: dict = Field(default_factory=dict)
    sources: list[dict] = Field(default_factory=list)
    chart: Optional[dict[str, float]] = None


@app.get("/api/v1/health")
def health_check():
    snapshot = dict(STATE)
    return {
        "status": "ok" if "agent" in snapshot else "degraded",
        "backend": settings.data_backend,
        "engine_mode": snapshot.get("mode", "unknown"),
        "alerts_source": snapshot.get("alerts_source", "unknown"),
        "max_staleness_months": settings.max_staleness_months,
        "stale_series_excluded": snapshot.get("stale_excluded", 0),
        "series_count": len(snapshot.get("forecast_df", [])),
        "passports_count": len(snapshot.get("passport_df", [])),
    }


@app.post("/api/v1/refresh")
def manual_refresh(x_admin_token: Optional[str] = Header(default=None)):
    """Recharge la mémoire de l'API après une mise à jour mensuelle des tables Gold. Protégé par jeton."""
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Endpoint désactivé : ADMIN_TOKEN non configuré.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    try:
        refresh_engines()
    except Exception:
        logger.exception("Rechargement impossible ; l'ancien état reste servi.")
        raise HTTPException(status_code=502, detail="Rechargement impossible ; l'ancien état reste servi.")
    return {"status": "reloaded", "engine_mode": STATE.get("mode")}


@app.get("/api/v1/metadata")
def get_metadata(state: dict = Depends(get_state)):
    fc = state["forecast_df"]
    products = sorted(fc["commodity_std"].dropna().astype(str).unique().tolist())
    cereals = sorted({
        product for product in products
        if any(keyword in product.lower() for keyword in ["millet", "maiz", "sorghum", "rice", "wheat", "cereal", "grain"])
    })
    markets = sorted(fc["market_name"].dropna().astype(str).unique().tolist())
    provinces = sorted(fc["province"].dropna().astype(str).unique().tolist())
    sources = sorted(fc["source"].dropna().astype(str).unique().tolist())

    observed_months = pd.Series(fc["last_observed_month"].dropna().astype(str).unique())
    start_period = observed_months.min() if not observed_months.empty else None
    end_period = observed_months.max() if not observed_months.empty else None

    active_domain = {
        "slug": "markets_and_prices",
        "label": "Marchés et prix des produits",
        "status": "operational",
        "description": "Catalogue en cours d'exploitation : marchés, produits, provinces et sources de données.",
    }

    domains = [
        active_domain,
        {"slug": "agriculture", "label": "Agriculture", "status": "in_preparation", "description": "Données agricoles, climat et production."},
        {"slug": "economy", "label": "Économie", "status": "in_preparation", "description": "Indicateurs et tendances économiques."},
        {"slug": "health", "label": "Santé", "status": "in_preparation", "description": "Données de santé et de vulnérabilité."},
        {"slug": "population", "label": "Population", "status": "in_preparation", "description": "Données démographiques et sociales."},
        {"slug": "environment", "label": "Environnement", "status": "in_preparation", "description": "Conditions environnementales et risques."},
        {"slug": "infrastructure", "label": "Infrastructures", "status": "in_preparation", "description": "Transport, routes et services essentiels."},
        {"slug": "transport", "label": "Transport", "status": "in_preparation", "description": "Flux et mobilité des biens et des personnes."},
    ]

    return {
        "active_domain": active_domain,
        "domains": domains,
        "products": products,
        "cereals": cereals,
        "markets": markets,
        "provinces": provinces,
        "sources": sources,
        "periods_covered": {
            "start": start_period,
            "end": end_period,
        },
        "last_updated": end_period,
        "count": {
            "products": len(products),
            "cereals": len(cereals),
            "markets": len(markets),
            "provinces": len(provinces),
            "sources": len(sources),
        },
        "legacy_fields": {
            "commodities": products,
            "provinces": provinces,
        },
    }


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def chat_endpoint(payload: ChatRequest, state: dict = Depends(get_state)):
    agent: FreeDataAIAgent = state["agent"]
    result = agent.answer(payload.message, history=payload.history[-8:], tier=payload.tier)
    return ChatResponse(**result)


@app.get("/api/v1/forecasts")
def get_forecasts(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=2000),
    state: dict = Depends(get_state),
):
    df = state["forecast_df"].copy()
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
    state: dict = Depends(get_state),
):
    hist = state["hist_df"]
    recent = hist.sort_values("year_month").groupby(["source", "province", "market_name", "commodity_std"]).tail(1).copy()
    alerts = recent[recent["deviation_pct"].notna() & (recent["deviation_pct"] >= threshold_pct)].copy()
    if province:
        alerts = alerts[alerts["province"].str.lower() == province.strip().lower()]
    if commodity:
        alerts = alerts[alerts["commodity_std"].str.lower() == commodity.strip().lower()]
    alerts = alerts.sort_values("deviation_pct", ascending=False).head(limit)
    alerts["month"] = alerts["year_month"].astype(str)
    cols = ["month", "source", "province", "market_name", "commodity_std", "value", "predicted_price", "deviation_pct"]
    return {
        "count": len(alerts),
        "alerts_source": state.get("alerts_source"),
        "items": alerts[cols].to_dict(orient="records"),
    }


@app.get("/api/v1/credit-passport")
def get_credit_passport(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    loan_amount: int = Query(1_000_000, ge=10000),
    state: dict = Depends(get_state),
):
    df = state["passport_df"].copy()
    if province:
        df = df[df["province"].str.lower() == province.strip().lower()]
    if commodity:
        df = df[df["commodity_std"].str.lower() == commodity.strip().lower()]
    df = df.sort_values("credit_score", ascending=False)
    df["recommended_max_loan_xaf"] = (df["ltv_ratio"] * loan_amount).astype(int)
    return {
        "count": len(df),
        "disclaimer": CREDIT_PASSPORT_DISCLAIMER,
        "items": df.to_dict(orient="records"),
    }
