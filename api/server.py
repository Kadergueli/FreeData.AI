import hmac
import ipaddress
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional
import requests
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.data_loader import load_clean_markets
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import INDEX_NAME, PASSPORT_METHODOLOGY, compute_credit_passport, compute_recommended_max_loan
from src.ai_agent import FreeDataAIAgent
from src.disclaimers import CREDIT_PASSPORT_DISCLAIMER
from src.freshness import assess_dataset_freshness, filter_fresh
from src.reports import build_market_study_dossier, render_market_study_pdf
from src.reports.jobs import ReportJobManager
from src.anomalies import detect_anomalies, recent_anomalies
from src.season_study import StudyBook, study_markdown, with_storage_cost
from src.study_context import StudyContext
from src.projects import ProjectStore
from src.governance import LicensingRegistry, PrivacyController, build_default_lineage
from src.analytics import AnalyticsService
from src.ml_engine import ModelRegistry, build_lag_features, evaluate_ridge_chronological
from src.rag_engine import HybridRAGEngine
from src.orchestrator_ml_rag import IntelligenceOrchestrator
from src.data_products import DataProductCatalog
from src.api_keys import ApiKeyManager
from src.domains import DomainRegistry
from src.entitlements import EntitlementManager
from src.monetization import DEFAULT_PLANS, HmacJsonWebhookAdapter, SubscriptionStore, simulate_unit_economics
from src.ai_infra import AIQualityMonitor, ModelRouter, TTLCache, cache_key_for_series
from src.security import filter_rag_hits_for_owner, validate_uploaded_document, verify_signed_user_token
from src.admin import AdminService, ROLE_PERMISSIONS
from src.backup import backup_all_databases
from src.support_feedback import SupportFeedbackStore

logger = logging.getLogger("freedata.api")

# État servi par l'API. Il n'est remplacé que d'un bloc (STATE.update) une fois le nouvel
# état entièrement construit : une requête ne voit jamais un mélange ancien/nouveau.
STATE: dict = {}
_REFRESH_LOCK = threading.Lock()
_RATE_LIMIT_BUCKET: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_LOCK = threading.Lock()
_CHAT_SLOTS = threading.BoundedSemaphore(max(1, settings.chat_max_concurrency))
_CHAT_WAIT_S = 3.0  # attente maximale d'un créneau chat avant de répondre 503


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _peer_is_trusted_proxy(peer: str) -> bool:
    cidrs_raw = getattr(settings, "trusted_proxy_cidrs", "") or ""
    if not cidrs_raw.strip():
        return True
    peer_ip = _valid_ip(peer)
    if peer_ip is None:
        return False
    addr = ipaddress.ip_address(peer_ip)
    for part in cidrs_raw.split(","):
        c = part.strip()
        if not c:
            continue
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


def _client_ip(request: Request) -> str:
    """IP du client. Ne fait confiance à X-Forwarded-For que si le proxy est explicitement configuré et validé."""
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops is None or hops <= 0 or not _peer_is_trusted_proxy(peer):
        return peer
    forwarded = (request.headers.get("x-forwarded-for") or "").strip() if hasattr(request, "headers") else ""
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return peer
    candidate = chain[-hops] if len(chain) >= hops else chain[0]
    return _valid_ip(candidate) or peer


def _hit_memory(bucket_key: str, limit: int, now: float, detail: str) -> None:
    window = [ts for ts in _RATE_LIMIT_BUCKET.get(bucket_key, ()) if now - ts < 60.0]
    if len(window) >= limit:
        _RATE_LIMIT_BUCKET[bucket_key] = window
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": "30"})
    window.append(now)
    _RATE_LIMIT_BUCKET[bucket_key] = window


def _hit_shared_redis(bucket_key: str, limit: int, now: float, detail: str) -> bool:
    """Tente un comptage partagé via Redis REST. Retourne True si traité, False si non configuré ou en erreur."""
    url = (getattr(settings, "rate_limit_redis_rest_url", "") or "").strip().rstrip("/")
    token = (getattr(settings, "rate_limit_redis_rest_token", "") or "").strip()
    if not url or not token:
        return False
    window_id = int(now // 60)
    redis_key = f"freedata:rl:{bucket_key}:{window_id}"
    try:
        resp = requests.post(
            f"{url}/pipeline",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=[["INCR", redis_key], ["EXPIRE", redis_key, 70]],
            timeout=1.5,
        )
        resp.raise_for_status()
        results = resp.json()
        count = int(results[0]["result"])
        if count > limit:
            raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": "30"})
        return True
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Shared rate-limit backend unavailable, falling back to in-memory: %s", exc)
        return False


def _hit(bucket_key: str, limit: int, now: float, detail: str) -> None:
    if _hit_shared_redis(bucket_key, limit, now, detail):
        return
    _hit_memory(bucket_key, limit, now, detail)


def check_rate_limit(request: Request, max_per_minute: int = 20, scope: str = "chat"):
    """`max_per_minute` requêtes par minute et par IP et par catégorie, plus un plafond global indépendant de l'IP."""
    client_ip = _client_ip(request)
    now = time.time()
    with _RATE_LIMIT_LOCK:
        _hit("*global*", settings.global_rate_limit_per_min, now, "Service très sollicité. Réessayez dans un instant.")
        _hit(f"{scope}:{client_ip}", max_per_minute, now, "Trop de requêtes. Réessayez dans une minute.")
        if len(_RATE_LIMIT_BUCKET) > 1000:
            stale = [k for k, ts in _RATE_LIMIT_BUCKET.items() if k != "*global*" and (not ts or now - ts[-1] >= 60.0)]
            for k in stale:
                _RATE_LIMIT_BUCKET.pop(k, None)


enforce_rate_limit = check_rate_limit


def _chat_rate_limit_dependency(request: Request):
    # Encapsule check_rate_limit sans paramètre scalaire pour éviter l'exposition en query param.
    check_rate_limit(request, 20, "chat")


def _data_rate_limit_dependency(request: Request):
    check_rate_limit(request, 120, "data")


def _admin_rate_limit_dependency(request: Request):
    check_rate_limit(request, 10, "admin")


def _fetch_gold_table(table_name: str, privileged: bool = False) -> pd.DataFrame:
    """Lit une table Gold pré-calculée via l'API HTTPS Supabase (ultra-léger en RAM)."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/{table_name}"
    key = settings.write_key if privileged else settings.read_key
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
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
                    studies: StudyBook | None = None, track_record: dict | None = None,
                    anomalies: pd.DataFrame | None = None) -> dict:
    """Applique le filtre de fraîcheur (couche API, le modèle n'est pas touché) et construit l'agent."""
    now_utc = datetime.now(timezone.utc)
    pub_dt = now_utc
    if not forecast_df.empty and "generated_at" in forecast_df.columns:
        parsed_pub = pd.to_datetime(forecast_df["generated_at"], utc=True, errors="coerce").dropna()
        if not parsed_pub.empty:
            pub_dt = parsed_pub.max().to_pydatetime()

    hist_df, _ = filter_fresh(hist_df, "year_month", settings.max_staleness_months)
    forecast_df, stale_excluded = filter_fresh(forecast_df, "last_observed_month", settings.max_staleness_months)
    freshness = {
        "forecasts": assess_dataset_freshness(
            forecast_df,
            "last_observed_month",
            settings.max_staleness_months,
            now_utc=now_utc,
            last_successful_computation_at=now_utc,
            last_publication_at=pub_dt,
        ),
        "historical": assess_dataset_freshness(
            hist_df,
            "year_month",
            settings.max_staleness_months,
            now_utc=now_utc,
            last_successful_computation_at=now_utc,
            last_publication_at=pub_dt,
        ),
    }
    return {
        "hist_df": hist_df,
        "forecast_df": forecast_df,
        "passport_df": passport_df,
        "agent": FreeDataAIAgent(hist_df, forecast_df, passport_df, studies=studies, track_record=track_record,
                                anomalies=anomalies),
        "anomalies": anomalies if anomalies is not None else pd.DataFrame(),
        "studies": studies,
        "track_record": track_record or {},
        "mode": mode,
        "alerts_source": alerts_source,
        "stale_excluded": stale_excluded,
        "freshness": freshness,
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


_ANOMALY_COLS = ["source", "province", "market_name", "commodity_std", "kind", "severity", "month",
                 "value", "reference", "change_pct", "score"]


def _anomaly_frame(rows: list | None) -> pd.DataFrame:
    """Table d'anomalies (lignes Gold) -> DataFrame propre ; vide si absente ou mal formée."""
    if not rows:
        return pd.DataFrame(columns=_ANOMALY_COLS)
    df = pd.DataFrame(rows)
    if not set(_ANOMALY_COLS) <= set(df.columns):
        return pd.DataFrame(columns=_ANOMALY_COLS)
    df = df[_ANOMALY_COLS].copy()
    df["month"] = df["month"].astype(str)
    for col in ("value", "reference", "change_pct", "score"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_state_from_gold(fc_gold: pd.DataFrame, cp_gold: pd.DataFrame, study_rows: list | None = None,
                          anomaly_rows: list | None = None) -> dict:
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
                           track_record=_track_records(study_rows), anomalies=_anomaly_frame(anomaly_rows))


def build_state_full() -> dict:
    """Recalcule tout depuis les données brutes (CSV local / PostgreSQL). Lourd en mémoire."""
    kg_df = load_clean_markets()
    hist_df, forecast_df = run_forecasting_pipeline(kg_df)
    passport_df = compute_credit_passport(kg_df)
    try:
        anomalies = recent_anomalies(detect_anomalies(kg_df), months=6)
    except Exception:  # une anomalie ne doit jamais empêcher le démarrage
        logger.exception("Détection d'anomalies indisponible.")
        anomalies = None
    return _finalize_state(hist_df, forecast_df, passport_df, "full_compute", "model_residual",
                           studies=StudyBook(kg_df=kg_df), anomalies=anomalies)


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
            study_rows = _fetch_gold_table("table_ml_seasonality_studies", privileged=True).to_dict(orient="records")
        except Exception as exc:  # table absente (sql/05 non appliqué) : le reste de l'API fonctionne
            logger.warning("Études saisonnières indisponibles (table_ml_seasonality_studies) : %s", exc)
            study_rows = []
        try:
            anomaly_rows = _fetch_gold_table("table_ml_anomalies", privileged=True).to_dict(orient="records")
        except Exception as exc:  # table absente (sql/07 non appliqué)
            logger.warning("Anomalies indisponibles (table_ml_anomalies) : %s", exc)
            anomaly_rows = []
        return build_state_from_gold(fc_gold, cp_gold, study_rows, anomaly_rows)
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
    logger.info("Premium : %d clé(s) configurée(s)%s ; proxys de confiance : %s ; chat simultané max : %d.",
                len(settings.premium_keys), "" if settings.premium_keys else " (offre premium DÉSACTIVÉE)",
                settings.trusted_proxy_hops if settings.trusted_proxy_hops is not None else "non défini (IP falsifiable)",
                settings.chat_max_concurrency)
    try:
        refresh_engines()
    except Exception:
        logger.exception("Chargement initial impossible : l'API démarre en mode dégradé (503).")
    yield
    STATE.clear()


app = FastAPI(
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
    title="FreeData.AI API",
    description="API REST officielle de prévision des prix agricoles, alertes spatiales et Agricultural Credit Passport (Tchad).",
    version="1.2.0",
    lifespan=lifespan,
)

_METRICS_LOCK = threading.Lock()
_METRICS: dict = {
    "total_requests": 0,
    "error_4xx": 0,
    "error_5xx": 0,
    "chat_requests": 0,
    "pdf_requests": 0,
    "qa_blocked": 0,
    "ml_inference_requests": 0,
    "rag_requests": 0,
    "rate_limit_violations": 0,
    "endpoints": {},
    "total_latency_ms": 0.0,
}


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    req_id = (request.headers.get("x-request-id") or uuid.uuid4().hex[:12]).strip()[:48]
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    with _METRICS_LOCK:
        _METRICS["total_requests"] += 1
        _METRICS["total_latency_ms"] += elapsed_ms
        if 400 <= response.status_code < 500:
            _METRICS["error_4xx"] += 1
        elif response.status_code >= 500:
            _METRICS["error_5xx"] += 1
        if response.status_code == 429:
            _METRICS["rate_limit_violations"] += 1
        path = request.url.path
        ep_map = _METRICS["endpoints"]
        ep_map[path] = ep_map.get(path, 0) + 1
        if path.endswith("/chat"):
            _METRICS["chat_requests"] += 1
        elif "/reports/" in path and path.endswith("/pdf"):
            _METRICS["pdf_requests"] += 1
            if response.status_code == 422:
                _METRICS["qa_blocked"] += 1
        elif "/ml/" in path:
            _METRICS["ml_inference_requests"] += 1
        elif "/rag/" in path:
            _METRICS["rag_requests"] += 1
    response.headers["X-Request-Id"] = req_id
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    return response


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse les corps de requête trop gros ou sans taille annoncée (POST/PUT/PATCH) avant tout traitement."""
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.headers.get("content-length")
        if raw is None:
            return JSONResponse({"detail": "En-tête Content-Length requis."}, status_code=411)
        if not raw.isdigit() or int(raw) > settings.max_body_bytes:
            return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?" if settings.allow_localhost_cors else None,
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
    for valid in settings.premium_keys:  # jamais le jeton administrateur : il ne doit pas circuler côté client
        ok |= hmac.compare_digest(cleaned.encode(), valid.encode())
    return ok


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    tier: Literal["free", "premium"] = Field(default="free")
    study_context: Optional[dict] = None

    @field_validator("history")
    @classmethod
    def _sanitize_history(cls, items: list[dict]) -> list[dict]:
        """Ne garde que {role: user|assistant, content: texte} et tronque à 4000 caractères ; le reste est ignoré (jamais d'erreur)."""
        clean = []
        for item in items:
            role, content = item.get("role", "user"), item.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                clean.append({"role": role, "content": content[:4000]})
        return clean


class ChatResponse(BaseModel):
    reply: str
    intent: str
    entities: dict = Field(default_factory=dict)
    sources: list[dict] = Field(default_factory=list)
    chart: Optional[dict[str, float]] = None
    summary: Optional[dict] = None
    client_state: Optional[dict] = None
    follow_ups: list[str] = Field(default_factory=list)


@app.get("/api/v1/health")
def health_check():
    snapshot = dict(STATE)
    freshness = snapshot.get("freshness") or {}
    fc_fresh = freshness.get("forecasts") or {
        "latest_observation_month": None,
        "last_successful_computation_at": None,
        "last_publication_at": None,
        "data_age_months": None,
        "freshness_status": "unavailable",
    }
    return {
        "status": "ok" if "agent" in snapshot else "degraded",
        "backend": settings.data_backend,
        "engine_mode": snapshot.get("mode", "unknown"),
        "alerts_source": snapshot.get("alerts_source", "unknown"),
        "max_staleness_months": settings.max_staleness_months,
        "stale_series_excluded": snapshot.get("stale_excluded", 0),
        "series_count": len(snapshot.get("forecast_df", [])),
        "passports_count": len(snapshot.get("passport_df", [])),
        "latest_observation_month": fc_fresh.get("latest_observation_month"),
        "last_successful_computation_at": fc_fresh.get("last_successful_computation_at"),
        "last_publication_at": fc_fresh.get("last_publication_at"),
        "data_age_months": fc_fresh.get("data_age_months"),
        "freshness_status": fc_fresh.get("freshness_status", "unavailable"),
        "data_freshness": freshness,
    }


@app.post("/api/v1/refresh", dependencies=[Depends(_admin_rate_limit_dependency)])
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


@app.get("/api/v1/diag/client-ip", dependencies=[Depends(_admin_rate_limit_dependency)])
def diag_client_ip(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    """Aide au réglage de TRUSTED_PROXY_HOPS : montre la chaîne X-Forwarded-For vue par l'API et l'IP retenue."""
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Endpoint désactivé : ADMIN_TOKEN non configuré.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    return {
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
        "peer": request.client.host if request.client else None,
        "trusted_proxy_hops": settings.trusted_proxy_hops,
        "client_ip_used": _client_ip(request),
    }


@app.get("/api/v1/metadata", dependencies=[Depends(_data_rate_limit_dependency)])
def get_metadata(state: dict = Depends(get_state)):
    fc = state["forecast_df"]
    cp = state.get("passport_df")
    products = sorted(fc["commodity_std"].dropna().astype(str).unique().tolist())
    passport_products = (
        sorted(cp["commodity_std"].dropna().astype(str).unique().tolist())
        if cp is not None and not cp.empty and "commodity_std" in cp.columns
        else products
    )
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
    forecast_months = (
        pd.Series(fc["forecast_month"].dropna().astype(str).unique())
        if "forecast_month" in fc.columns
        else pd.Series(dtype=str)
    )
    forecast_month = forecast_months.max() if not forecast_months.empty else None

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
        "passport_products": passport_products,
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
        "track_records": state.get("track_record", {}),
        "count": {
            "products": len(products),
            "passport_products": len(passport_products),
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
    # Le niveau « premium » (LLM payant) exige une clé valide : sans clé configurée ou fournie, repli sur le gratuit.
    if tier == "premium" and not _premium_key_ok(x_premium_key):
        tier = "free"
    # Plafond de requêtes chat simultanées : un appel LLM lent ne doit pas saturer tous les threads de l'API.
    if not _CHAT_SLOTS.acquire(timeout=_CHAT_WAIT_S):
        raise HTTPException(status_code=503, detail="Assistant très sollicité. Réessayez dans un instant.",
                            headers={"Retry-After": "5"})
    try:
        result = agent.answer(
            payload.message,
            history=payload.history,
            tier=tier,
            study_context=payload.study_context,
        )
    finally:
        _CHAT_SLOTS.release()
    return ChatResponse(**result)


@app.get("/api/v1/forecasts", dependencies=[Depends(_data_rate_limit_dependency)])
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
        "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae", "forecast_quality", "interval_status",
    ]
    if "forecast_quality" not in df.columns:  # Gold ancien (sql/06 pas encore appliqué)
        df["forecast_quality"] = "standard"
    if "interval_status" not in df.columns:
        df["interval_status"] = "uncalibrated"
    out = df[cols].rename(columns={"value": "last_observed_price"}).head(limit)
    return {"count": len(out), "items": out.to_dict(orient="records")}


@app.get("/api/v1/alerts", dependencies=[Depends(_data_rate_limit_dependency)])
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


def _require_premium_key(x_premium_key: Optional[str], feature_label: str) -> None:
    if not settings.premium_keys:
        raise HTTPException(
            status_code=503,
            detail=f"{feature_label} indisponible : offre partenaire non activée.",
        )
    if not _premium_key_ok(x_premium_key):
        raise HTTPException(status_code=403, detail="Clé premium invalide.")


@app.get("/api/v1/anomalies", dependencies=[Depends(_data_rate_limit_dependency)])
def get_anomalies(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    kind: Optional[str] = Query(None, pattern="^(jump|divergence|jump\\+divergence|regional|stale|stopped)$"),
    severity: Optional[str] = Query(None, pattern="^(forte|modérée)$"),
    limit: int = Query(100, ge=1, le=1000),
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
):
    """Signaux à vérifier (offre premium) : sauts, divergences entre marchés, séries figées ou arrêtées."""
    _require_premium_key(x_premium_key, "Analyse d'anomalies")
    df = state.get("anomalies")
    if df is None or df.empty:
        return {"count": 0, "items": []}
    df = df.copy()
    if province:
        df = df[df["province"].str.lower() == province.strip().lower()]
    if commodity:
        df = df[df["commodity_std"].str.lower() == commodity.strip().lower()]
    if kind:
        df = df[df["kind"] == kind]
    if severity:
        df = df[df["severity"] == severity]
    df = df.sort_values(["month", "score"], ascending=[False, False], key=lambda c: c.abs() if c.name == "score" else c)
    out = df.head(limit).astype(object).where(df.head(limit).notna(), None)
    return {"count": len(out), "items": out.to_dict(orient="records")}


@app.get("/api/v1/credit-passport", dependencies=[Depends(_data_rate_limit_dependency)])
def get_credit_passport(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    collateral_value_xaf: Optional[int] = Query(None, ge=0, le=1_000_000_000_000),
    loan_amount: Optional[int] = Query(None, ge=0, le=1_000_000_000_000),
    state: dict = Depends(get_state),
):
    df = state["passport_df"].copy()
    if province:
        df = df[df["province"].str.lower() == province.strip().lower()]
    if commodity:
        df = df[df["commodity_std"].str.lower() == commodity.strip().lower()]
    df = df.sort_values("credit_score", ascending=False)
    effective_collateral = (
        collateral_value_xaf
        if collateral_value_xaf is not None
        else (loan_amount if loan_amount is not None else 1_000_000)
    )
    df["recommended_max_loan_xaf"] = [
        compute_recommended_max_loan(effective_collateral, float(r)) for r in df["ltv_ratio"]
    ]
    return {
        "index_name": INDEX_NAME,
        "collateral_value_xaf": effective_collateral,
        "methodology": PASSPORT_METHODOLOGY,
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
    _require_premium_key(x_premium_key, "Études avancées")
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


class MarketStudyRequest(BaseModel):
    commodity: str = Field(..., min_length=2, max_length=60)
    origin_province: str = Field(..., min_length=2, max_length=60)
    dest_province: Optional[str] = Field(None, max_length=60)
    capital_xaf: float = Field(..., gt=0, le=1_000_000_000_000)
    transport_cost_per_kg: Optional[float] = Field(None, ge=0, le=50_000)
    loss_rate_pct: float = Field(5.0, ge=0.0, le=50.0)
    monthly_fixed_costs_xaf: float = Field(35_000.0, ge=0.0, le=100_000_000)
    promoter_name: Optional[str] = Field(None, max_length=120)
    user_instructions: list[str] = Field(default_factory=list)
    study_context: Optional[dict] = None


def _build_study_dossier_or_404(payload: MarketStudyRequest, state: dict) -> dict:
    agent: FreeDataAIAgent = state["agent"]
    ctx = StudyContext.from_dict(payload.study_context) if payload.study_context else None
    fields_set = getattr(payload, "model_fields_set", set())

    eff_transport = payload.transport_cost_per_kg
    if eff_transport is None and ctx is not None:
        eff_transport = ctx.budget_and_assumptions.get("transport_cost_per_kg")
    eff_loss = (
        payload.loss_rate_pct
        if ("loss_rate_pct" in fields_set or ctx is None)
        else float(ctx.budget_and_assumptions.get("loss_rate_pct", payload.loss_rate_pct))
    )
    eff_fixed = (
        payload.monthly_fixed_costs_xaf
        if ("monthly_fixed_costs_xaf" in fields_set or ctx is None)
        else float(ctx.budget_and_assumptions.get("monthly_fixed_costs_xaf", payload.monthly_fixed_costs_xaf))
    )
    eff_promoter = payload.promoter_name or (ctx.promoter_info.get("name") if ctx else None)
    merged_instructions: list[str] = []
    for inst in (ctx.user_instructions if ctx else []) + list(payload.user_instructions or []):
        if inst and inst not in merged_instructions:
            merged_instructions.append(inst)

    try:
        return build_market_study_dossier(
            provider=agent.provider,
            commodity=payload.commodity,
            origin_province=payload.origin_province,
            dest_province=payload.dest_province,
            capital_xaf=payload.capital_xaf,
            transport_cost_per_kg=eff_transport if eff_transport is not None else 25.0,
            loss_rate_pct=eff_loss,
            monthly_fixed_costs_xaf=eff_fixed,
            transport_is_user_provided=eff_transport is not None,
            capital_is_user_provided=True,
            promoter_name=eff_promoter,
            user_instructions=merged_instructions,
            study_context=ctx.to_dict() if ctx else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/api/v1/reports/market-study",
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def generate_market_study_json(
    payload: MarketStudyRequest,
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
):
    """Génère le dossier structuré d'étude de marché PRO (100 % données réelles, zéro hallucination)."""
    _require_premium_key(x_premium_key, "Rapports d'étude de marché PRO")
    return _build_study_dossier_or_404(payload, state)


@app.post(
    "/api/v1/reports/market-study/pdf",
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def generate_market_study_pdf(
    payload: MarketStudyRequest,
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
):
    """Génère et retourne le rapport PDF professionnel d'étude de marché PRO."""
    _require_premium_key(x_premium_key, "Rapports d'étude de marché PDF PRO")
    dossier = _build_study_dossier_or_404(payload, state)
    validation = dossier.get("validation") or {}
    if not validation.get("can_deliver_pdf", True):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La validation qualité du rapport a bloqué la génération du PDF.",
                "validation": validation,
            },
        )
    pdf_bytes = render_market_study_pdf(dossier)
    safe_slug = "".join(c if c.isalnum() else "_" for c in dossier["commodity"].lower()).strip("_") or "marche"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="freedata_etude_{safe_slug}.pdf"',
            "X-Report-QA-Status": str(validation.get("overall_status", "PASSED")),
        },
    )


# ---------------------------------------------------------------------------
# Phase 5 — Persistent Projects, Conversations & Study Version Management
# ---------------------------------------------------------------------------
_PROJECT_STORE: Optional[ProjectStore] = None


def get_project_store() -> ProjectStore:
    global _PROJECT_STORE
    if _PROJECT_STORE is None:
        _PROJECT_STORE = ProjectStore()
    return _PROJECT_STORE


def _require_project_owner(
    x_user_id: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> str:
    auth_secret = os.getenv("AUTH_SECRET", "").strip()
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        tok = authorization.split(" ", 1)[1].strip()
        sub = verify_signed_user_token(tok, auth_secret)
        if sub:
            return f"user:{sub}"
        raise HTTPException(status_code=401, detail="Jeton Bearer invalide ou expiré.")
    if x_premium_key and _premium_key_ok(x_premium_key):
        import hashlib
        digest = hashlib.sha256(x_premium_key.strip().encode("utf-8")).hexdigest()[:16]
        return f"key:{digest}"
    require_signed = os.getenv("REQUIRE_SIGNED_USER_AUTH", "0").strip().lower() in ("1", "true", "yes")
    if not require_signed and x_user_id and len(x_user_id.strip()) >= 3:
        return f"user:{x_user_id.strip()[:80]}"
    raise HTTPException(status_code=401, detail="Authentification requise (Bearer token, X-Premium-Key, ou X-User-Id en mode dev).")


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field("", max_length=1000)
    study_context: Optional[dict] = None
    idempotency_key: Optional[str] = Field(None, max_length=80)


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[Literal["active", "archived"]] = None
    study_context: Optional[dict] = None


class ProjectConversationCreateRequest(BaseModel):
    title: str = Field("Nouvelle conversation", min_length=1, max_length=120)


class ProjectMessageRequest(BaseModel):
    role: Literal["user", "assistant"] = "user"
    content: str = Field(..., min_length=1, max_length=4000)
    metadata: dict = Field(default_factory=dict)
    study_context: Optional[dict] = None


class ProjectStudyCreateRequest(MarketStudyRequest):
    study_id: Optional[str] = Field(None, max_length=80)


@app.post("/api/v1/projects", dependencies=[Depends(_data_rate_limit_dependency)])
def create_project_endpoint(
    payload: ProjectCreateRequest,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    return store.create_project(
        owner_id=owner_id,
        name=payload.name,
        description=payload.description,
        study_context=payload.study_context,
        idempotency_key=payload.idempotency_key,
    )


@app.get("/api/v1/projects", dependencies=[Depends(_data_rate_limit_dependency)])
def list_projects_endpoint(
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    return {"projects": store.list_projects(owner_id, include_archived=include_archived, limit=limit, offset=offset)}


@app.get("/api/v1/projects/{project_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def get_project_endpoint(
    project_id: str,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.get_project(owner_id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/v1/projects/{project_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def update_project_endpoint(
    project_id: str,
    payload: ProjectUpdateRequest,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.update_project(
            owner_id,
            project_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            study_context=payload.study_context,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/v1/projects/{project_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_project_endpoint(
    project_id: str,
    confirm: bool = Query(False),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    try:
        store.delete_project(owner_id, project_id)
        return {"deleted": True, "project_id": project_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/conversations", dependencies=[Depends(_data_rate_limit_dependency)])
def create_project_conversation_endpoint(
    project_id: str,
    payload: ProjectConversationCreateRequest,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.create_conversation(owner_id, project_id, title=payload.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/conversations/{conversation_id}/messages", dependencies=[Depends(_data_rate_limit_dependency)])
def add_project_message_endpoint(
    project_id: str,
    conversation_id: str,
    payload: ProjectMessageRequest,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.add_message(
            owner_id,
            project_id,
            conversation_id,
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
            updated_study_context=payload.study_context,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/studies", dependencies=[Depends(_chat_rate_limit_dependency)])
def create_project_study_version_endpoint(
    project_id: str,
    payload: ProjectStudyCreateRequest,
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        proj = store.get_project(owner_id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    merged_ctx = payload.study_context or proj.get("study_context")
    study_req = MarketStudyRequest(
        commodity=payload.commodity,
        origin_province=payload.origin_province,
        dest_province=payload.dest_province,
        capital_xaf=payload.capital_xaf,
        transport_cost_per_kg=payload.transport_cost_per_kg,
        loss_rate_pct=payload.loss_rate_pct,
        monthly_fixed_costs_xaf=payload.monthly_fixed_costs_xaf,
        promoter_name=payload.promoter_name,
        user_instructions=payload.user_instructions,
        study_context=merged_ctx,
    )
    dossier = _build_study_dossier_or_404(study_req, state)
    validation = dossier.get("validation") or {}
    if not validation.get("can_deliver_pdf", True):
        raise HTTPException(status_code=422, detail={"message": "Validation QA échouée.", "validation": validation})

    pdf_bytes = render_market_study_pdf(dossier)
    return store.create_study_version(
        owner_id,
        project_id,
        study_id=payload.study_id,
        dossier=dossier,
        generation_params=payload.model_dump(exclude={"study_context"}),
        pdf_bytes=pdf_bytes,
    )


@app.get("/api/v1/projects/{project_id}/studies/{study_id}/versions", dependencies=[Depends(_data_rate_limit_dependency)])
def list_study_versions_endpoint(
    project_id: str,
    study_id: str,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return {"versions": store.list_study_versions(owner_id, project_id, study_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/studies/{study_id}/compare", dependencies=[Depends(_data_rate_limit_dependency)])
def compare_study_versions_endpoint(
    project_id: str,
    study_id: str,
    v1: int = Query(..., ge=1),
    v2: int = Query(..., ge=1),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.compare_study_versions(owner_id, project_id, study_id, v1, v2)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/studies/{study_id}/versions/{version_number}/pdf", dependencies=[Depends(_data_rate_limit_dependency)])
def download_study_version_pdf_endpoint(
    project_id: str,
    study_id: str,
    version_number: int,
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    try:
        pdf_bytes = store.get_study_version_pdf(owner_id, project_id, study_id, version_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="freedata_{study_id}_v{version_number}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 6 — Observability Metrics & Background Report Jobs
# ---------------------------------------------------------------------------
_REPORT_JOB_MANAGER = ReportJobManager(max_workers=2)


def get_report_job_manager() -> ReportJobManager:
    return _REPORT_JOB_MANAGER


@app.get("/api/v1/metrics", dependencies=[Depends(_admin_rate_limit_dependency)])
def get_metrics(x_admin_token: Optional[str] = Header(default=None)):
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Endpoint désactivé : ADMIN_TOKEN non configuré.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    with _METRICS_LOCK:
        snap = dict(_METRICS)
    total = max(1, snap["total_requests"])
    snap["avg_latency_ms"] = round(snap.pop("total_latency_ms") / total, 2)
    return snap


class ReportJobCreateRequest(MarketStudyRequest):
    project_id: Optional[str] = Field(None, max_length=80)
    study_id: Optional[str] = Field(None, max_length=80)


@app.post("/api/v1/reports/jobs", dependencies=[Depends(_chat_rate_limit_dependency)])
def create_report_job_endpoint(
    payload: ReportJobCreateRequest,
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    store: ProjectStore = Depends(get_project_store),
    jobs: ReportJobManager = Depends(get_report_job_manager),
):
    _require_premium_key(x_premium_key, "Génération asynchrone de rapports PDF PRO")

    def _task(progress_cb):
        progress_cb(30)
        dossier = _build_study_dossier_or_404(payload, state)
        validation = dossier.get("validation") or {}
        if not validation.get("can_deliver_pdf", True):
            raise ValueError("Validation QA échouée : " + "; ".join(validation.get("required_corrections") or []))
        progress_cb(70)
        pdf_bytes = render_market_study_pdf(dossier)
        ver_info = {}
        if payload.project_id:
            ver_info = store.create_study_version(
                owner_id,
                payload.project_id,
                study_id=payload.study_id,
                dossier=dossier,
                generation_params=payload.model_dump(exclude={"study_context", "project_id", "study_id"}),
                pdf_bytes=pdf_bytes,
            )
        return {
            "pdf_bytes": pdf_bytes,
            "validation": validation,
            "study_id": ver_info.get("study_id") or dossier.get("study_id"),
            "version_number": ver_info.get("version_number"),
        }

    return jobs.submit(owner_id, _task)


@app.get("/api/v1/reports/jobs/{job_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def get_report_job_status_endpoint(
    job_id: str,
    owner_id: str = Depends(_require_project_owner),
    jobs: ReportJobManager = Depends(get_report_job_manager),
):
    try:
        return jobs.get_status(owner_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/reports/jobs/{job_id}/pdf", dependencies=[Depends(_data_rate_limit_dependency)])
def download_report_job_pdf_endpoint(
    job_id: str,
    owner_id: str = Depends(_require_project_owner),
    jobs: ReportJobManager = Depends(get_report_job_manager),
):
    try:
        pdf_bytes = jobs.get_pdf(owner_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="freedata_job_{job_id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 9 — Data Governance, Licensing Registry, Lineage & Privacy Deletion
# ---------------------------------------------------------------------------
_LICENSING_REGISTRY = LicensingRegistry()


def get_licensing_registry() -> LicensingRegistry:
    return _LICENSING_REGISTRY


class GovernanceDecisionRequest(BaseModel):
    action: Literal["approve_publication", "suspend_dataset", "review_license", "record_quality_issue"]
    reason: str = Field("", max_length=500)
    license_category: Optional[Literal["open_data", "publicly_accessible", "attribution_required", "restricted", "unclear_licensing"]] = None
    redistribution_allowed: Optional[bool] = None


@app.get("/api/v1/governance/registry", dependencies=[Depends(_data_rate_limit_dependency)])
def get_governance_registry_endpoint(registry: LicensingRegistry = Depends(get_licensing_registry)):
    """Transparence publique : licences, attribution, lignage et politique de rétention."""
    return {
        "datasets": registry.list_entries(),
        "lineage": build_default_lineage(),
        "privacy_notice": {
            "data_minimization": "Seuls les identifiants techniques de projet et le StudyContext sont persistés ; aucune clé API n'est stockée dans StudyContext.",
            "deletion_endpoint": "DELETE /api/v1/privacy/my-data?confirm=true",
        },
    }


@app.post("/api/v1/governance/datasets/{dataset_id}/decision", dependencies=[Depends(_admin_rate_limit_dependency)])
def governance_admin_decision_endpoint(
    dataset_id: str,
    payload: GovernanceDecisionRequest,
    x_admin_token: Optional[str] = Header(default=None),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis pour les décisions de gouvernance.")
    try:
        return registry.admin_decision(
            dataset_id,
            action=payload.action,
            actor="admin",
            reason=payload.reason,
            license_category=payload.license_category,
            redistribution_allowed=payload.redistribution_allowed,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/privacy/my-data", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_my_data_endpoint(
    confirm: bool = Query(False),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    return PrivacyController.delete_user_data(store, owner_id)


# ---------------------------------------------------------------------------
# Phase 10 — Data Intelligence & Advanced Analytics API
# ---------------------------------------------------------------------------
_ANALYTICS_SERVICE = AnalyticsService()


def get_analytics_service() -> AnalyticsService:
    return _ANALYTICS_SERVICE


@app.get("/api/v1/analytics/profile", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_profile_endpoint(
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_profile(state["forecast_df"], state.get("hist_df", pd.DataFrame()))


@app.get("/api/v1/analytics/summary", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_summary_endpoint(
    commodity: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_summary(
        state["forecast_df"],
        state.get("passport_df", pd.DataFrame()),
        commodity=commodity,
        province=province,
    )


@app.get("/api/v1/analytics/trends", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_trends_endpoint(
    commodity: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_trends(
        state.get("hist_df", pd.DataFrame()),
        commodity=commodity,
        province=province,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/analytics/regional-comparison", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_regional_comparison_endpoint(
    commodity: Optional[str] = Query(None),
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_regional_comparison(state["forecast_df"], commodity=commodity)


@app.get("/api/v1/analytics/anomalies", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_anomalies_endpoint(
    province: Optional[str] = Query(None),
    commodity: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_anomalies(
        state.get("anomalies_df", pd.DataFrame()),
        province=province,
        commodity=commodity,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/analytics/forecast-benchmark", dependencies=[Depends(_data_rate_limit_dependency)])
def analytics_forecast_benchmark_endpoint(
    commodity: str = Query(..., min_length=2),
    province: str = Query(..., min_length=2),
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
):
    return svc.get_forecast_benchmark(
        state.get("hist_df", pd.DataFrame()),
        commodity=commodity,
        province=province,
    )


# ---------------------------------------------------------------------------
# Phase 10B — ML Registry, Hybrid RAG & Intelligence Orchestration API
# ---------------------------------------------------------------------------
_MODEL_REGISTRY = ModelRegistry()
_HYBRID_RAG: Optional[HybridRAGEngine] = None


def get_hybrid_rag() -> HybridRAGEngine:
    global _HYBRID_RAG
    if _HYBRID_RAG is None:
        rag = HybridRAGEngine()
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for doc_name in ("METHODOLOGY.md", "DATA_CATALOG.md", "DATA_GOVERNANCE_POLICY.md", "DATA_LICENSING_POLICY.md", "RESPONSIBLE_AI_POLICY.md"):
            p = root / doc_name
            if p.is_file():
                rag.ingest_file(p, source=doc_name)
        _HYBRID_RAG = rag
    return _HYBRID_RAG


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(4, ge=1, le=20)
    province: Optional[str] = None
    commodity: Optional[str] = None


class IntelligenceQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000)
    commodity: Optional[str] = None
    province: Optional[str] = None


@app.get("/api/v1/ml/models", dependencies=[Depends(_data_rate_limit_dependency)])
def list_ml_models_endpoint():
    return {"models": _MODEL_REGISTRY.list_models()}


_ML_CACHE = TTLCache(ttl_seconds=300.0, max_size=256)
_RAG_CACHE = TTLCache(ttl_seconds=300.0, max_size=256)
_AI_MONITOR = AIQualityMonitor()
_MODEL_ROUTER = ModelRouter()


@app.post("/api/v1/rag/search", dependencies=[Depends(_data_rate_limit_dependency)])
def rag_hybrid_search_endpoint(
    payload: RagSearchRequest,
    rag: HybridRAGEngine = Depends(get_hybrid_rag),
):
    filters = {k: v for k, v in {"province": payload.province, "commodity": payload.commodity}.items() if v}
    ckey = f"{payload.query.strip().lower()}|{payload.top_k}|{sorted(filters.items())}"
    cached = _RAG_CACHE.get(ckey)
    if cached is not None:
        return {"hits": cached, "cached": True}
    hits = filter_rag_hits_for_owner(
        rag.search(payload.query, top_k=payload.top_k, filters=filters or None),
        owner_id=None,
    )
    _RAG_CACHE.set(ckey, hits)
    return {"hits": hits, "cached": False}


@app.post("/api/v1/intelligence/query", dependencies=[Depends(_data_rate_limit_dependency)])
def intelligence_orchestrate_endpoint(
    payload: IntelligenceQueryRequest,
    state: dict = Depends(get_state),
    svc: AnalyticsService = Depends(get_analytics_service),
    rag: HybridRAGEngine = Depends(get_hybrid_rag),
):
    orch = IntelligenceOrchestrator(analytics=svc, rag=rag)
    return orch.handle(
        payload.query,
        forecast_df=state["forecast_df"],
        hist_df=state.get("hist_df", pd.DataFrame()),
        passport_df=state.get("passport_df", pd.DataFrame()),
        anomalies_df=state.get("anomalies_df", pd.DataFrame()),
        commodity=payload.commodity,
        province=payload.province,
    )


# ---------------------------------------------------------------------------
# Phase 11 — Data Products, ML-as-a-Service & Developer API Key Management
# ---------------------------------------------------------------------------
_DATA_CATALOG = DataProductCatalog()
_API_KEY_MANAGER = ApiKeyManager()


def get_api_key_manager() -> ApiKeyManager:
    return _API_KEY_MANAGER


def _require_developer_or_premium_key(
    x_api_key: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
) -> str:
    candidate = x_api_key or x_premium_key
    if candidate and candidate.strip().startswith("fd_"):
        try:
            meta = km.validate_and_consume(candidate)
            if meta:
                return meta["owner_id"]
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        raise HTTPException(status_code=403, detail="Clé API développeur invalide.")
    _require_premium_key(x_premium_key or x_api_key, "Services ML/IA")
    return "premium_key"


@app.get("/api/v1/products", dependencies=[Depends(_data_rate_limit_dependency)])
def list_data_products_endpoint(
    state: dict = Depends(get_state),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    return {"products": _DATA_CATALOG.list_products(registry, state["forecast_df"])}


@app.get("/api/v1/products/{product_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def get_data_product_endpoint(
    product_id: str,
    state: dict = Depends(get_state),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    try:
        return _DATA_CATALOG.get_product(product_id, registry, state["forecast_df"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/products/{product_id}/export", dependencies=[Depends(_data_rate_limit_dependency)])
def export_data_product_endpoint(
    product_id: str,
    format: Literal["json", "csv"] = Query("json"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: dict = Depends(get_state),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    try:
        exported = _DATA_CATALOG.export_product(
            product_id,
            registry=registry,
            forecast_df=state["forecast_df"],
            passport_df=state.get("passport_df", pd.DataFrame()),
            limit=limit,
            offset=offset,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if format == "csv":
        csv_text = pd.DataFrame(exported["records"]).to_csv(index=False)
        return Response(
            content=csv_text.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{product_id}.csv"'},
        )
    return exported


class MLPredictRequest(BaseModel):
    series_prices: list[float] = Field(..., min_length=8, max_length=120)


@app.post("/api/v1/ml/predict", dependencies=[Depends(_chat_rate_limit_dependency)])
def ml_predict_endpoint(
    payload: MLPredictRequest,
    _caller: str = Depends(_require_developer_or_premium_key),
):
    import numpy as np
    arr = np.array(payload.series_prices, dtype=float)
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise HTTPException(status_code=422, detail="Tous les prix doivent être finis et strictement positifs.")
    ckey = cache_key_for_series(payload.series_prices)
    cached = _ML_CACHE.get(ckey)
    if cached is not None:
        return {**cached, "cached": True}
    ev = evaluate_ridge_chronological(arr)
    if ev.get("status") != "evaluated":
        raise HTTPException(status_code=422, detail="Historique insuffisant pour valider le modèle.")
    model = ev.pop("model")
    X_all, _ = build_lag_features(np.append(arr, arr[-1]))
    pred = float(model.predict(X_all[-1:])[0])
    mae = float(ev["ridge_mae_xaf_kg"])
    out = {
        "model": "RidgePriceRegressor",
        "prediction_xaf_kg": round(pred, 1),
        "ci_low_80": round(max(0.0, pred - 1.28 * mae), 1),
        "ci_high_80": round(pred + 1.28 * mae, 1),
        "evaluation": ev,
    }
    _ML_CACHE.set(ckey, out)
    return {**out, "cached": False}


class DeveloperKeyCreateRequest(BaseModel):
    owner_id: str = Field(..., min_length=3, max_length=80)
    label: str = Field("default", max_length=60)
    daily_quota: int = Field(500, ge=1, le=50000)


@app.post("/api/v1/developer/keys", dependencies=[Depends(_admin_rate_limit_dependency)])
def issue_developer_key_endpoint(
    payload: DeveloperKeyCreateRequest,
    x_admin_token: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis.")
    return km.issue_key(payload.owner_id, label=payload.label, daily_quota=payload.daily_quota)


@app.post("/api/v1/developer/keys/{key_id}/revoke", dependencies=[Depends(_admin_rate_limit_dependency)])
def revoke_developer_key_endpoint(
    key_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis.")
    try:
        return km.revoke_key(key_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/developer/keys", dependencies=[Depends(_admin_rate_limit_dependency)])
def list_developer_keys_endpoint(
    x_admin_token: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis.")
    return {"keys": km.list_keys()}


# ---------------------------------------------------------------------------
# Phase 11B — Multi-Domain Platform & Free/Premium Entitlements
# ---------------------------------------------------------------------------
_ENTITLEMENTS = EntitlementManager()


def get_entitlement_manager() -> EntitlementManager:
    return _ENTITLEMENTS


class PlatformChatRequest(ChatRequest):
    domain: Optional[str] = Field(None, max_length=60)
    project_id: Optional[str] = Field(None, max_length=80)


@app.get("/api/v1/domains", dependencies=[Depends(_data_rate_limit_dependency)])
def list_domains_endpoint(
    x_user_id: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    ent: EntitlementManager = Depends(get_entitlement_manager),
):
    eff_tier = "premium" if _premium_key_ok(x_premium_key) else "free"
    uid = (x_user_id or "anonymous").strip()[:80]
    return {
        "domains": DomainRegistry.list_domains(),
        "entitlements": ent.get_entitlements(eff_tier, uid),
    }


@app.post("/api/v1/platform/chat", dependencies=[Depends(_chat_rate_limit_dependency)])
def platform_chat_endpoint(
    payload: PlatformChatRequest,
    state: dict = Depends(get_state),
    x_user_id: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    rag: HybridRAGEngine = Depends(get_hybrid_rag),
    svc: AnalyticsService = Depends(get_analytics_service),
    ent: EntitlementManager = Depends(get_entitlement_manager),
):
    eff_tier = "premium" if (payload.tier == "premium" and _premium_key_ok(x_premium_key)) else "free"
    uid = (x_user_id or "anonymous").strip()[:80]
    try:
        quota_info = ent.consume_chat_quota(eff_tier, uid)
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    domain_mod = DomainRegistry.classify_domain(payload.message, explicit_domain=payload.domain)
    agent: FreeDataAIAgent = state["agent"]

    if domain_mod.domain_id in ("chad_intelligence", "agriculture", "business_entrepreneurship", "finance"):
        res = agent.answer(
            payload.message,
            history=payload.history,
            tier=eff_tier,
            study_context=payload.study_context,
        )
        return {**res, "domain": domain_mod.domain_id, "domain_label": domain_mod.label_fr, "quota": quota_info}

    if domain_mod.domain_id == "data_science":
        orch = IntelligenceOrchestrator(analytics=svc, rag=rag)
        out = orch.handle(
            payload.message,
            forecast_df=state["forecast_df"],
            hist_df=state.get("hist_df", pd.DataFrame()),
            passport_df=state.get("passport_df", pd.DataFrame()),
            anomalies_df=state.get("anomalies_df", pd.DataFrame()),
        )
        return {
            "reply": f"**[{domain_mod.label_fr}]** Outil exécuté : `{out['tool_used']}` (portée : {out['geographic_scope']}, méthodologie : {out['methodology']}).",
            "intent": out["tool_used"],
            "entities": {},
            "sources": [{"title": str(s)} for s in out.get("sources", [])],
            "summary": out["result"],
            "domain": domain_mod.domain_id,
            "domain_label": domain_mod.label_fr,
            "quota": quota_info,
        }

    # General AI, Education, Academic Research, Tech & Programming, Productivity
    rag_hits = rag.search(payload.message, top_k=3)
    sources = [{"title": h["title"], "source": h["source"], "score": h["score"]} for h in rag_hits]
    if eff_tier == "premium" and settings.llm_api_key:
        llm_reply = agent._converse_with_llm(
            payload.message,
            payload.history,
            f"domaine {domain_mod.label_fr} — {domain_mod.instructions}",
        )
        reply = llm_reply or _fallback_domain_reply(domain_mod, payload.message, rag_hits)
    else:
        reply = _fallback_domain_reply(domain_mod, payload.message, rag_hits)

    return {
        "reply": reply,
        "intent": f"domain_{domain_mod.domain_id}",
        "entities": {},
        "sources": sources,
        "domain": domain_mod.domain_id,
        "domain_label": domain_mod.label_fr,
        "quota": quota_info,
    }


def _fallback_domain_reply(domain_mod, query: str, rag_hits: list[dict]) -> str:
    base = f"**[{domain_mod.label_fr}]** {domain_mod.instructions}"
    if rag_hits:
        excerpts = "\n".join(f"- *{h['source']}* : {h['compressed_excerpt']}" for h in rag_hits[:2])
        return f"{base}\n\n**Références trouvées dans la base de connaissances :**\n{excerpts}"
    return f"{base}\n\nVotre demande (« {query[:120]} ») est prête à être approfondie ; précisez le contexte ou les contraintes souhaitées."


# ---------------------------------------------------------------------------
# Phase 12 — Subscription Lifecycle, Atomic Usage Metering & Cost Simulation
# ---------------------------------------------------------------------------
_SUBSCRIPTION_STORE: Optional[SubscriptionStore] = None


def get_subscription_store() -> SubscriptionStore:
    global _SUBSCRIPTION_STORE
    if _SUBSCRIPTION_STORE is None:
        _SUBSCRIPTION_STORE = SubscriptionStore()
    return _SUBSCRIPTION_STORE


@app.get("/api/v1/billing/plans", dependencies=[Depends(_data_rate_limit_dependency)])
def list_billing_plans_endpoint():
    return {
        "plans": list(DEFAULT_PLANS.values()),
        "payment_provider_status": "provider_agnostic_manual_activation_enabled",
        "note": "Aucun plan n'est illimité ; les quotas journaliers/mensuels sont appliqués côté serveur.",
    }


@app.get("/api/v1/billing/me", dependencies=[Depends(_data_rate_limit_dependency)])
def get_my_billing_endpoint(
    owner_id: str = Depends(_require_project_owner),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    return sub_store.get_usage_summary(owner_id)


class AdminSubscriptionActivateRequest(BaseModel):
    target_user_id: str = Field(..., min_length=3, max_length=100)
    plan_id: Literal["free", "trial", "premium"]
    status: Literal["active", "trialing", "grace_period", "past_due", "cancelled", "expired"] = "active"
    period_days: int = Field(30, ge=0, le=365)
    grace_days: int = Field(3, ge=0, le=30)
    reason: str = Field("", max_length=300)


@app.post("/api/v1/billing/admin/activate", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_activate_subscription_endpoint(
    payload: AdminSubscriptionActivateRequest,
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis.")
    return sub_store.admin_update_subscription(
        actor="admin",
        target_user_id=payload.target_user_id,
        plan_id=payload.plan_id,
        status=payload.status,
        period_days=payload.period_days,
        grace_days=payload.grace_days,
        provider="manual",
        reason=payload.reason,
    )


@app.post("/api/v1/billing/webhook/{provider}", dependencies=[Depends(_data_rate_limit_dependency)])
async def payment_webhook_endpoint(
    provider: str,
    request: Request,
    x_webhook_signature: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    secret = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook paiement non configuré (PAYMENT_WEBHOOK_SECRET manquant).")
    raw_body = await request.body()
    adapter = HmacJsonWebhookAdapter(provider_name=provider)
    try:
        return sub_store.process_webhook_idempotent(adapter, raw_body, x_webhook_signature or "", secret)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CostSimulationRequest(BaseModel):
    active_users: int = Field(100, ge=1, le=1_000_000)
    paid_users: int = Field(20, ge=0, le=1_000_000)
    monthly_subscription_price_xaf: float = Field(0.0, ge=0.0)
    avg_chats_per_user_month: int = Field(25, ge=0, le=10000)
    avg_pdfs_per_paid_user_month: int = Field(3, ge=0, le=1000)
    cost_per_chat_xaf: float = Field(2.0, ge=0.0)
    cost_per_pdf_xaf: float = Field(5.0, ge=0.0)
    cost_per_ml_rag_op_xaf: float = Field(0.5, ge=0.0)
    monthly_infra_fixed_xaf: float = Field(15000.0, ge=0.0)


@app.post("/api/v1/billing/cost-simulation", dependencies=[Depends(_admin_rate_limit_dependency)])
def billing_cost_simulation_endpoint(
    payload: CostSimulationRequest,
    x_admin_token: Optional[str] = Header(default=None),
):
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur requis.")
    return simulate_unit_economics(**payload.model_dump())


# ---------------------------------------------------------------------------
# Phase 13 — AI Infrastructure Routing & Quality Monitoring
# ---------------------------------------------------------------------------
class AIRouteRequest(BaseModel):
    task_type: str = Field(..., min_length=2, max_length=60)
    subscription_tier: Literal["free", "premium"] = "free"
    context_length: int = Field(0, ge=0, le=100000)
    require_high_accuracy: bool = False


@app.post("/api/v1/ai/route", dependencies=[Depends(_data_rate_limit_dependency)])
def ai_route_preview_endpoint(payload: AIRouteRequest):
    try:
        return _MODEL_ROUTER.select_model(
            task_type=payload.task_type,
            subscription_tier=payload.subscription_tier,
            context_length=payload.context_length,
            require_high_accuracy=payload.require_high_accuracy,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/v1/ai/infra-metrics", dependencies=[Depends(_admin_rate_limit_dependency)])
def ai_infra_metrics_endpoint(x_admin_token: Optional[str] = Header(default=None)):
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Endpoint désactivé : ADMIN_TOKEN non configuré.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    return _AI_MONITOR.snapshot(_ML_CACHE, _RAG_CACHE)


class DocumentValidateRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=180)
    content_base64: str = Field(..., min_length=1)
    mime_type: Optional[str] = Field(None, max_length=100)


@app.post("/api/v1/documents/validate", dependencies=[Depends(_data_rate_limit_dependency)])
def validate_document_endpoint(
    payload: DocumentValidateRequest,
    owner_id: str = Depends(_require_project_owner),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    import base64
    sub = sub_store.get_subscription(owner_id)
    max_bytes = int(sub["limits"].get("max_file_mb", 2)) * 1024 * 1024
    try:
        raw_bytes = base64.b64decode(payload.content_base64, validate=True)
        return validate_uploaded_document(
            payload.filename,
            raw_bytes,
            mime_type=payload.mime_type,
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Encodage base64 invalide.") from exc


# ---------------------------------------------------------------------------
# Phase 14 — Centralized Admin Dashboard, RBAC & System Operations
# ---------------------------------------------------------------------------
_ADMIN_SERVICE: Optional[AdminService] = None


def get_admin_service() -> AdminService:
    global _ADMIN_SERVICE
    if _ADMIN_SERVICE is None:
        _ADMIN_SERVICE = AdminService()
    return _ADMIN_SERVICE


def _require_admin_actor(
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_actor: Optional[str] = Header(default=None),
    x_admin_role: Optional[str] = Header(default=None),
) -> tuple[str, str]:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Administration désactivée : ADMIN_TOKEN non configuré.")
    if not isinstance(x_admin_token, str) or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    actor = x_admin_actor.strip()[:80] if isinstance(x_admin_actor, str) and x_admin_actor.strip() else "root_admin"
    role = x_admin_role.strip() if isinstance(x_admin_role, str) and x_admin_role.strip() in ROLE_PERMISSIONS else "super_admin"
    return actor, role


@app.get("/api/v1/admin/overview", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_overview_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    state: dict = Depends(get_state),
    admin: AdminService = Depends(get_admin_service),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    with _METRICS_LOCK:
        api_metrics = dict(_METRICS)
    api_metrics["avg_latency_ms"] = round(api_metrics.pop("total_latency_ms", 0.0) / max(1, api_metrics.get("total_requests", 1)), 2)

    users = admin.list_users(sub_store, limit=500, offset=0)
    plan_counts = {"free": 0, "trial": 0, "premium": 0}
    for u in users:
        p = u["plan_id"]
        plan_counts[p] = plan_counts.get(p, 0) + 1

    return {
        "api_health": {"status": "ok" if "agent" in state else "degraded", "version": app.version, "engine_mode": state.get("mode", "unknown")},
        "api_metrics": api_metrics,
        "ai_infra": _AI_MONITOR.snapshot(_ML_CACHE, _RAG_CACHE),
        "model_flags": admin.list_model_flags(),
        "ml_models": _MODEL_REGISTRY.list_models(),
        "users_summary": {"total_known_users": len(users), "by_plan": plan_counts},
        "datasets": registry.list_entries(),
        "recent_audit_logs": admin.list_audit_logs(limit=20),
    }


@app.get("/api/v1/admin/users", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_users_endpoint(
    q: Optional[str] = Query(None),
    status: Optional[Literal["active", "suspended"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"users": admin.list_users(sub_store, q=q, status=status, limit=limit, offset=offset)}


class AdminUserStatusRequest(BaseModel):
    status: Literal["active", "suspended"]
    reason: str = Field("", max_length=300)


@app.post("/api/v1/admin/users/{target_user_id}/status", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_set_user_status_endpoint(
    target_user_id: str,
    payload: AdminUserStatusRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        return admin.set_user_status(actor=actor, actor_role=role, target_user_id=target_user_id, status=payload.status, reason=payload.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


class AdminAssignRoleRequest(BaseModel):
    role: Literal["user", "read_only_analyst", "support_admin", "platform_admin", "super_admin"]
    reason: str = Field("", max_length=300)


@app.post("/api/v1/admin/users/{target_user_id}/role", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_assign_role_endpoint(
    target_user_id: str,
    payload: AdminAssignRoleRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        return admin.assign_role(actor=actor, actor_role=role, target_user_id=target_user_id, new_role=payload.role, reason=payload.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.delete("/api/v1/admin/users/{target_user_id}", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_delete_user_data_endpoint(
    target_user_id: str,
    confirm: bool = Query(False),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    store: ProjectStore = Depends(get_project_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    actor, role = actor_info
    try:
        admin.check_permission(role, "delete_user_data")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    out = PrivacyController.delete_user_data(store, target_user_id)
    admin.log_action(actor=actor, actor_role=role, action="delete_user_data", resource_type="user", resource_id=target_user_id, details="Admin deletion")
    return out


class AdminModelFlagRequest(BaseModel):
    enabled: bool
    reason: str = Field("", max_length=300)


@app.post("/api/v1/admin/models/{profile_id}", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_toggle_model_endpoint(
    profile_id: str,
    payload: AdminModelFlagRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        return admin.set_model_enabled(actor=actor, actor_role=role, profile_id=profile_id, enabled=payload.enabled, reason=payload.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/v1/admin/audit-logs", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_audit_logs_endpoint(
    limit: int = Query(50, ge=1, le=200),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"audit_logs": admin.list_audit_logs(limit=limit)}


@app.post("/api/v1/reports/jobs/{job_id}/retry", dependencies=[Depends(_chat_rate_limit_dependency)])
def retry_report_job_endpoint(
    job_id: str,
    owner_id: str = Depends(_require_project_owner),
    jobs: ReportJobManager = Depends(get_report_job_manager),
):
    try:
        return jobs.retry_job(owner_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.post("/api/v1/admin/backup", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_trigger_backup_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    store: ProjectStore = Depends(get_project_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_system")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    backup_root = Path(os.getenv("FREEDATA_BACKUP_DIR", "data/backups"))
    results = backup_all_databases([store.db_path, sub_store.db_path, admin.db_path], backup_root)
    admin.log_action(
        actor=actor,
        actor_role=role,
        action="trigger_sqlite_backup",
        resource_type="database",
        resource_id="all_sqlite",
        details=f"{len(results)} database(s) processed",
    )
    return {"backups": results}


# ---------------------------------------------------------------------------
# Phase 16 — User Support, Structured Feedback & Product Analytics
# ---------------------------------------------------------------------------
_SUPPORT_STORE: Optional[SupportFeedbackStore] = None


def get_support_store() -> SupportFeedbackStore:
    global _SUPPORT_STORE
    if _SUPPORT_STORE is None:
        _SUPPORT_STORE = SupportFeedbackStore()
    return _SUPPORT_STORE


class SupportTicketCreateRequest(BaseModel):
    category: Literal["technical_bug", "incorrect_ai", "pdf_issue", "account_help", "feature_request"]
    subject: str = Field(..., min_length=3, max_length=140)
    description: str = Field(..., min_length=5, max_length=2000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class FeedbackSubmitRequest(BaseModel):
    feature: Literal["ai_response", "rag_relevance", "ml_prediction", "pdf_quality", "usability", "feature_request"]
    rating: int = Field(..., ge=1, le=5)
    category: str = Field("general", max_length=60)
    comment: str = Field("", max_length=1000)


class ProductEventRequest(BaseModel):
    event_name: str = Field(..., min_length=2, max_length=60)
    properties: dict = Field(default_factory=dict)


class AdminTicketUpdateRequest(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = None
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None


@app.post("/api/v1/support/tickets", dependencies=[Depends(_data_rate_limit_dependency)])
def create_support_ticket_endpoint(
    payload: SupportTicketCreateRequest,
    owner_id: str = Depends(_require_project_owner),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    return sup.create_ticket(
        owner_id,
        category=payload.category,
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
    )


@app.get("/api/v1/support/tickets", dependencies=[Depends(_data_rate_limit_dependency)])
def list_my_support_tickets_endpoint(
    owner_id: str = Depends(_require_project_owner),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    return {"tickets": sup.list_user_tickets(owner_id)}


@app.post("/api/v1/feedback", dependencies=[Depends(_data_rate_limit_dependency)])
def submit_feedback_endpoint(
    payload: FeedbackSubmitRequest,
    owner_id: str = Depends(_require_project_owner),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    return sup.submit_feedback(
        owner_id,
        feature=payload.feature,
        rating=payload.rating,
        category=payload.category,
        comment=payload.comment,
    )


@app.post("/api/v1/analytics/events", dependencies=[Depends(_data_rate_limit_dependency)])
def record_product_event_endpoint(
    payload: ProductEventRequest,
    owner_id: str = Depends(_require_project_owner),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    ev_id = sup.record_product_event(owner_id, event_name=payload.event_name, properties=payload.properties)
    return {"recorded": True, "event_id": ev_id}


@app.get("/api/v1/admin/support/overview", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_support_overview_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return sup.get_admin_overview()


@app.get("/api/v1/admin/support/tickets", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_tickets_endpoint(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"tickets": sup.admin_list_tickets(status=status, category=category, limit=limit)}


@app.patch("/api/v1/admin/support/tickets/{ticket_id}", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_update_ticket_endpoint(
    ticket_id: str,
    payload: AdminTicketUpdateRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    sup: SupportFeedbackStore = Depends(get_support_store),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_users")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        updated = sup.admin_update_ticket(ticket_id, status=payload.status, priority=payload.priority)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    admin.log_action(
        actor=actor,
        actor_role=role,
        action="update_support_ticket",
        resource_type="support_ticket",
        resource_id=ticket_id,
        details=f"status={updated['status']}, priority={updated['priority']}",
    )
    return updated
