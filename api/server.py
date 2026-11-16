import hmac
import json
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
from src.season_study import StudyBook, study_markdown, with_storage_cost

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


def _finalize_state(hist_df, forecast_df, passport_df, mode: str, alerts_source: str,
                    studies: StudyBook | None = None, track_record: dict | None = None) -> dict:
    """Applique le filtre de fraîcheur (couche API, le modèle n'est pas touché) et construit l'agent."""
    hist_df, _ = filter_fresh(hist_df, "year_month", settings.max_staleness_months)
    forecast_df, stale_excluded = filter_fresh(forecast_df, "last_observed_month", settings.max_staleness_months)
    return {
        "hist_df": hist_df,
        "forecast_df": forecast_df,
        "passport_df": passport_df,
        "agent": FreeDataAIAgent(hist_df, forecast_df, passport_df, studies=studies, track_record=track_record),
        "studies": studies,
        "mode": mode,
        "alerts_source": alerts_source,
        "stale_excluded": stale_excluded,
    }


def _study_payloads(rows: list | None) -> list[dict]:
    """Extrait les études (JSON) des lignes de table_ml_seasonality_studies ; ignore toute ligne mal formée."""
    out = []
    for r in rows or []:
        if isinstance(r, dict) and r.get("kind", "seasonality") != "seasonality":
            continue
        payload = r.get("payload") if isinstance(r, dict) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        if isinstance(payload, dict) and payload.get("status") == "ok" and isinstance(payload.get("commodity"), str):
            out.append(payload)
    return out


def _track_records(rows: list | None) -> dict:
    """{produit: bilan de fiabilité} extrait des lignes kind='track_record' ; toute ligne mal formée est ignorée."""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("kind") != "track_record":
            continue
        p = r.get("payload")
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except ValueError:
                continue
        if (isinstance(p, dict) and isinstance(p.get("commodity"), str) and p.get("verdict") in ("better", "equivalent", "worse")
                and isinstance(p.get("vs_naive_pct"), (int, float)) and isinstance(p.get("months"), int)):
            out[p["commodity"]] = p
    return out


def build_state_from_gold(fc_gold: pd.DataFrame, cp_gold: pd.DataFrame, study_rows: list | None = None) -> dict:
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

    studies = StudyBook(studies=_study_payloads(study_rows)) if study_rows else None
    return _finalize_state(hist, fc, cp_gold, "gold_fast_read", alerts_source, studies=studies,
                           track_record=_track_records(study_rows))


def build_state_full() -> dict:
    """Recalcule tout depuis les données brutes (CSV local / PostgreSQL). Lourd en mémoire."""
    kg_df = load_clean_markets()
    hist_df, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    return _finalize_state(hist_df, forecast_df, passport_df, "full_compute", "model_residual",
                           studies=StudyBook(kg_df=kg_df))


def build_state() -> dict:
    if settings.data_backend == "supabase_rest":
        fc_gold = _fetch_gold_table("table_ml_forecasts")
        cp_gold = _fetch_gold_table("table_ml_credit_passport")
        if fc_gold.empty or cp_gold.empty:
            # Pas de repli vers un recalcul complet : il saturerait la mémoire d'un hébergement gratuit.
            raise RuntimeError(
                "Tables Gold vides : exécuter scripts/update_predictions.py avant de démarrer l'API."
            )
        try:
            study_rows = _fetch_gold_table("table_ml_seasonality_studies").to_dict(orient="records")
        except Exception as exc:  # table absente (sql/05 non appliqué) : le reste de l'API fonctionne
            logger.warning("Études saisonnières indisponibles (table_ml_seasonality_studies) : %s", exc)
            study_rows = []
        return build_state_from_gold(fc_gold, cp_gold, study_rows)
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


def _clean_secret(value: Optional[str]) -> str:
    return (value or "").strip().strip('"').strip("'").strip()


def _premium_key_ok(key: Optional[str]) -> bool:
    """Comparaison en temps constant avec chacune des clés premium configurées."""
    cleaned = _clean_secret(key)
    if not cleaned:
        return False
    ok = False
    for valid in settings.premium_keys:
        ok |= hmac.compare_digest(cleaned.encode(), valid.encode())
    return ok


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
    fc_months = (
        pd.Series(fc["forecast_month"].dropna().astype(str).unique())
        if "forecast_month" in fc.columns
        else pd.Series(dtype=str)
    )
    forecast_month = fc_months.max() if not fc_months.empty else None

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
            "forecast_month": forecast_month,
        },
        "forecast_month": forecast_month,
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
def chat_endpoint(
    payload: ChatRequest,
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
):
    agent: FreeDataAIAgent = state["agent"]
    tier = payload.tier
    # Dès que des clés premium sont configurées, le tier « premium » (LLM payant) n'est plus une simple déclaration.
    if tier == "premium" and settings.premium_keys and not _premium_key_ok(x_premium_key):
        tier = "free"
    result = agent.answer(payload.message, history=payload.history[-8:], tier=tier)
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
        "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae", "forecast_quality",
    ]
    if "forecast_quality" not in df.columns:  # Gold ancien (sql/06 pas encore appliqué)
        df["forecast_quality"] = "standard"
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


@app.get(
    "/api/v1/studies/seasonality",
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def seasonality_study(
    commodity: str = Query(..., min_length=2, max_length=60),
    province: Optional[str] = Query(None, max_length=60),
    storage_cost_pct_month: Optional[float] = Query(None, ge=0.0, le=20.0),
    output: Literal["json", "markdown"] = Query("json", alias="format"),
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
):
    """Étude saisonnière avancée (offre premium) : calendrier, comparaison de provinces, stratégie de stockage rejouée."""
    if not settings.premium_keys:
        raise HTTPException(status_code=503, detail="Études avancées désactivées : PREMIUM_API_KEYS non configuré.")
    if not _premium_key_ok(x_premium_key):
        raise HTTPException(status_code=403, detail="Clé premium invalide.")
    book: StudyBook | None = state.get("studies")
    fc = state["forecast_df"]
    by_lower = {str(c).lower(): str(c) for c in fc["commodity_std"].dropna().unique()}
    comm = by_lower.get(commodity.strip().lower())
    if comm is None:
        raise HTTPException(status_code=404, detail="Produit inconnu.")
    prov = None
    if province:
        provs = {str(p).lower(): str(p) for p in fc["province"].dropna().unique()}
        prov = provs.get(province.strip().lower())
        if prov is None:
            raise HTTPException(status_code=404, detail="Province inconnue.")
    study = book.get(comm, prov) if book is not None else None
    if study is None:
        study = {"status": "insufficient_data", "commodity": comm, "province": prov}
    else:
        study = with_storage_cost(study, storage_cost_pct_month)
    if output == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(study_markdown(study), media_type="text/markdown; charset=utf-8")
    return study
