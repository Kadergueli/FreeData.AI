import hmac
import ipaddress
import json
import logging
import os
import sys
import re
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal, Optional
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
from src.ml_benchmark import BenchmarkJobManager, DatasetSpec, MAX_CSV_BYTES, promotion_blockers
from src.ml_engine import ModelRegistry, build_lag_features, evaluate_ridge_chronological
from src.rag_engine import HybridRAGEngine
from src.orchestrator_ml_rag import IntelligenceOrchestrator
from src.data_products import DataProductCatalog
from src.api_keys import ApiKeyManager
from src.domains import DomainRegistry
from src.agro_indicators import AgroIndicatorStore, canonical_region, NATIONAL as AGRO_NATIONAL, HUBS as AGRO_HUBS
from src.agro_assessments import AgroFieldAssessmentStore, AgronomistProfileStore
from src.agro_engine import (
    build_campaign_radar,
    build_zone_profile,
    build_zones_overview,
    compare_agro_assessments,
    compute_gps_logistics,
    evaluate_field_assessment,
    validate_field_assessment_qa,
)
from src.reports.agro_pdf import render_agro_assessment_pdf
from src.market_pro import (
    MarketWatchlistStore,
    build_validated_forecasts_overview,
    compute_agro_credit_passport,
    compute_inter_province_arbitrage,
    compute_spatial_arbitrage_detailed,
    evaluate_watchlists,
    export_validated_forecasts_csv,
)
from src.entitlements import EntitlementManager
from src.auth import AuthStore, DEFAULT_TOKEN_TTL_SECONDS, MAX_SESSION_LIFETIME_SECONDS, get_auth_secret
from src.conversations import ConversationStore
from src.user_documents import UserDocumentStore
from src.monetization import (
    DEFAULT_PLANS,
    HmacJsonWebhookAdapter,
    StripeWebhookAdapter,
    SubscriptionStore,
    get_configured_plans,
    get_payment_methods,
    simulate_unit_economics,
)
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


def _admin_rate_limit_dependency(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    """60 req/min pour un jeton valide (tableau de bord) ; 10 req/min pour les jetons invalides (anti-devinette)."""
    if _admin_credentials() and _resolve_admin(x_admin_token) is None:
        check_rate_limit(request, 10, "admin_fail")
    check_rate_limit(request, 60, "admin")


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
    if os.getenv("RENDER") and os.getenv("REQUIRE_SIGNED_USER_AUTH", "0").strip().lower() not in ("1", "true", "yes"):
        logger.warning(
            "SÉCURITÉ PRODUCTION : REQUIRE_SIGNED_USER_AUTH n'est pas activé (=1) sur Render. "
            "Activez REQUIRE_SIGNED_USER_AUTH=1 et AUTH_SECRET (>= 32 car.) en production."
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
    "document_indexing_requests": 0,
    "rate_limit_violations": 0,
    "error_categories": {
        "auth_failure": 0,
        "authorization_failure": 0,
        "quota_violation": 0,
        "validation_error": 0,
        "server_error": 0,
    },
    "recent_errors": [],
    "endpoints": {},
    "total_latency_ms": 0.0,
}


def _classify_http_error(status_code: int) -> Optional[str]:
    if status_code == 401:
        return "auth_failure"
    if status_code == 403:
        return "authorization_failure"
    if status_code == 429:
        return "quota_violation"
    if status_code in (400, 422):
        return "validation_error"
    if status_code >= 500:
        return "server_error"
    return None


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
        elif path.startswith("/api/v1/documents/upload"):
            _METRICS["document_indexing_requests"] += 1

        err_cat = _classify_http_error(response.status_code)
        if err_cat:
            cats = _METRICS["error_categories"]
            cats[err_cat] = cats.get(err_cat, 0) + 1
            recent = _METRICS["recent_errors"]
            recent.append({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "request_id": req_id,
                "category": err_cat,
                "status_code": response.status_code,
                "path": path,
            })
            if len(recent) > 20:
                del recent[:-20]
    response.headers["X-Request-Id"] = req_id
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith(("/api/v1/auth", "/api/v1/admin", "/api/v1/privacy")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Refuse les corps de requête trop gros ou sans taille annoncée (POST/PUT/PATCH) avant tout traitement."""
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.headers.get("content-length")
        if raw is None:
            return JSONResponse({"detail": "En-tête Content-Length requis."}, status_code=411)
        if request.url.path.startswith("/api/v1/documents"):
            max_allowed = max(settings.max_body_bytes, 12 * 1024 * 1024)
        elif request.url.path.startswith("/api/v1/admin/ai/benchmark"):
            max_allowed = max(settings.max_body_bytes, 7 * 1024 * 1024)
        elif request.url.path.startswith("/api/v1/conversations"):
            max_allowed = max(settings.max_body_bytes, 524_288)
        else:
            max_allowed = settings.max_body_bytes
        if not raw.isdigit() or int(raw) > max_allowed:
            return JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?" if settings.allow_localhost_cors else None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-User-Id",
        "X-Premium-Key",
        "X-Api-Key",
        "X-Admin-Token",
        "X-Request-Id",
    ],
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
    project_id: Optional[str] = Field(None, max_length=80)

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
    _require_admin_token(x_admin_token, "manage_system")
    try:
        refresh_engines()
    except Exception:
        logger.exception("Rechargement impossible ; l'ancien état reste servi.")
        raise HTTPException(status_code=502, detail="Rechargement impossible ; l'ancien état reste servi.")
    return {"status": "reloaded", "engine_mode": STATE.get("mode")}


@app.get("/api/v1/diag/client-ip", dependencies=[Depends(_admin_rate_limit_dependency)])
def diag_client_ip(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    """Aide au réglage de TRUSTED_PROXY_HOPS : montre la chaîne X-Forwarded-For vue par l'API et l'IP retenue."""
    _require_admin_token(x_admin_token, "manage_system")
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

    active_domain, domains = DomainRegistry.metadata_domains()

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


_SUBSCRIPTION_STORE: Optional[SubscriptionStore] = None
_AUTH_STORE: Optional[AuthStore] = None
_CONVERSATION_STORE: Optional[ConversationStore] = None
_USER_DOCUMENT_STORE: Optional[UserDocumentStore] = None
_AGRO_STORE: Optional[AgroIndicatorStore] = None
_AGRO_SEED_LOCK = threading.Lock()


def get_agro_store() -> AgroIndicatorStore:
    """Store des indicateurs agricoles ; graine idempotente depuis le CSV commercial propre si la table est vide."""
    global _AGRO_STORE
    if _AGRO_STORE is None:
        with _AGRO_SEED_LOCK:
            if _AGRO_STORE is None:
                try:
                    store = AgroIndicatorStore()
                    seed_path = os.getenv("AGRO_SEED_CSV", "freedatatd-agriculture-commercial-clean.csv").strip()
                    if seed_path and os.path.isfile(seed_path) and store.count() == 0:
                        try:
                            report = store.ingest_csv(seed_path)
                            logger.info("Indicateurs agricoles ingérés depuis %s : %s lignes", seed_path, report.get("written"))
                        except Exception as exc:  # fichier non conforme : on n'écrit rien et on le journalise
                            logger.error("Ingestion agricole refusée (%s) : %s", seed_path, exc)
                    _AGRO_STORE = store
                except Exception as exc:
                    logger.exception("Échec connexion AgroIndicatorStore (vérifier SUPABASE_DB_URL) : %s", exc)
                    raise HTTPException(
                        status_code=503,
                        detail=f"Base des indicateurs agricoles indisponible : {type(exc).__name__}",
                    ) from exc
    return _AGRO_STORE


@app.get("/api/v1/agro/zones", dependencies=[Depends(_data_rate_limit_dependency)])
def agro_zones_endpoint(store: AgroIndicatorStore = Depends(get_agro_store)):
    """Pôles agro-climatiques couverts (NASA POWER Agro) et fraîcheur, avec provenance et limites."""
    return build_zones_overview(store.rows())


@app.get("/api/v1/agro/zone-profile", dependencies=[Depends(_data_rate_limit_dependency)])
def agro_zone_profile_endpoint(
    region: str = Query(..., min_length=2, max_length=80),
    store: AgroIndicatorStore = Depends(get_agro_store),
):
    """Pré-diagnostic agro-climatique de zone : humidité des sols, PAR, anomalies vs normale 2020–2023, indicateurs nationaux."""
    hub = canonical_region(region)
    if hub is None or hub == AGRO_NATIONAL:
        raise HTTPException(
            status_code=404,
            detail=f"Zone inconnue. Pôles couverts : {', '.join(AGRO_HUBS)}.",
        )
    regional = store.regional_rows(hub)
    if not regional:
        raise HTTPException(status_code=503, detail="Données agro-climatiques non encore disponibles pour cette zone.")
    profile = build_zone_profile(hub, regional, store.national_rows())
    fc_df = STATE.get("forecast_df")
    if fc_df is not None and not getattr(fc_df, "empty", True):
        profile["validated_crop_prices"] = build_validated_forecasts_overview(
            fc_df, STATE.get("track_record") or {}
        )
    return profile


_AGRO_ASSESSMENT_STORE: Optional[AgroFieldAssessmentStore] = None
_AGRO_PROFILE_STORE: Optional[AgronomistProfileStore] = None


def get_agro_assessment_store() -> AgroFieldAssessmentStore:
    global _AGRO_ASSESSMENT_STORE
    if _AGRO_ASSESSMENT_STORE is None:
        try:
            _AGRO_ASSESSMENT_STORE = AgroFieldAssessmentStore()
        except Exception as exc:
            logger.exception("Échec connexion AgroFieldAssessmentStore : %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Base des diagnostics agronomiques indisponible : {type(exc).__name__}",
            ) from exc
    return _AGRO_ASSESSMENT_STORE



def get_user_document_store() -> UserDocumentStore:
    global _USER_DOCUMENT_STORE
    if _USER_DOCUMENT_STORE is None:
        try:
            _USER_DOCUMENT_STORE = UserDocumentStore()
        except Exception as exc:
            logger.exception("Échec connexion UserDocumentStore (vérifier SUPABASE_DB_URL) : %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Base de données des documents indisponible (vérifiez SUPABASE_DB_URL sur Render) : {type(exc).__name__}",
            ) from exc
    return _USER_DOCUMENT_STORE


def get_subscription_store() -> SubscriptionStore:
    global _SUBSCRIPTION_STORE
    if _SUBSCRIPTION_STORE is None:
        try:
            _SUBSCRIPTION_STORE = SubscriptionStore()
        except Exception as exc:
            logger.exception("Échec connexion SubscriptionStore (vérifier SUPABASE_DB_URL) : %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Base de données applicative indisponible (vérifiez SUPABASE_DB_URL sur Render) : {type(exc).__name__}",
            ) from exc
    return _SUBSCRIPTION_STORE


def get_auth_store() -> AuthStore:
    global _AUTH_STORE
    if _AUTH_STORE is None:
        try:
            _AUTH_STORE = AuthStore()
        except Exception as exc:
            logger.exception("Échec connexion AuthStore (vérifier SUPABASE_DB_URL) : %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Base de données des comptes indisponible (vérifiez SUPABASE_DB_URL sur Render) : {type(exc).__name__}",
            ) from exc
    return _AUTH_STORE


def get_conversation_store() -> ConversationStore:
    global _CONVERSATION_STORE
    if _CONVERSATION_STORE is None:
        try:
            _CONVERSATION_STORE = ConversationStore()
        except Exception as exc:
            logger.exception("Échec connexion ConversationStore (vérifier SUPABASE_DB_URL) : %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Base de données des conversations indisponible (vérifiez SUPABASE_DB_URL sur Render) : {type(exc).__name__}",
            ) from exc
    return _CONVERSATION_STORE


_PROJECT_STORE: Optional[ProjectStore] = None


def get_project_store() -> ProjectStore:
    global _PROJECT_STORE
    if _PROJECT_STORE is None:
        _PROJECT_STORE = ProjectStore()
    return _PROJECT_STORE


_STRONG_UID_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
_ACCOUNT_ID_RE = re.compile(r"^u[0-9a-f]{32}$")


def _assert_not_suspended(owner_id: Optional[str], *, skip_auth_store_check: bool = False) -> None:
    if not owner_id:
        return
    msg = "Compte suspendu par l'administrateur. Contactez le support."
    # Le service est instancié à la demande : s'appuyer sur `_ADMIN_SERVICE` (None après un redémarrage)
    # laissait les comptes suspendus actifs jusqu'au premier appel d'une route admin.
    try:
        if get_admin_service().is_user_suspended(owner_id):
            raise HTTPException(status_code=403, detail=msg)
    except HTTPException:
        raise
    except Exception as exc:  # base admin indisponible : ne pas bloquer tout le trafic
        logger.warning("Vérification de suspension (admin_accounts) impossible : %s", exc)
    if not skip_auth_store_check and owner_id.startswith("user:"):
        try:
            u = get_auth_store().get_user(owner_id)
        except HTTPException:
            u = None
        if u and u.get("status") == "suspended":
            raise HTTPException(status_code=403, detail=msg)


def _is_registered_account_id(uid: str) -> bool:
    """True si `uid` est l'identifiant d'un compte enregistré (donc protégé par mot de passe / jeton Bearer)."""
    try:
        return get_auth_store().get_user(uid) is not None
    except Exception:
        return False


def _resolve_owner_id_optional(
    x_user_id: Optional[str] = None,
    x_premium_key: Optional[str] = None,
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Résout un owner_id canonique unique (partagé entre chat, PDF, projets, support et /billing/me)."""
    auth_secret = os.getenv("AUTH_SECRET", "").strip()
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        tok = authorization.split(" ", 1)[1].strip()
        sub = verify_signed_user_token(tok, auth_secret)
        if sub:
            auth_store = get_auth_store()
            check = auth_store.get_auth_check_state(tok, sub)
            if check["revoked"]:
                raise HTTPException(status_code=401, detail="Session révoquée. Veuillez vous reconnecter.")
            # Compte supprimé : un jeton encore valide ne doit plus ouvrir d'espace (identifiants émis par /auth/*).
            if _ACCOUNT_ID_RE.fullmatch(sub):
                if not check["exists"]:
                    raise HTTPException(status_code=401, detail="Compte introuvable ou supprimé. Veuillez vous reconnecter.")
                if check["stale"]:
                    raise HTTPException(status_code=401, detail="Session expirée (mot de passe modifié). Veuillez vous reconnecter.")
                if check["status"] == "suspended":
                    raise HTTPException(status_code=403, detail="Compte suspendu par l'administrateur. Contactez le support.")
            owner = f"user:{sub}"
            _assert_not_suspended(owner, skip_auth_store_check=True)
            return owner
        raise HTTPException(status_code=401, detail="Jeton Bearer invalide ou expiré.")

    require_signed = os.getenv("REQUIRE_SIGNED_USER_AUTH", "0").strip().lower() in ("1", "true", "yes")
    uid = x_user_id.strip() if isinstance(x_user_id, str) else ""
    pkey = x_premium_key if isinstance(x_premium_key, str) else None
    strong = _STRONG_UID_RE.fullmatch(uid) is not None
    # En mode strict (REQUIRE_SIGNED_USER_AUTH=1), un en-tête X-User-Id non signé ne doit JAMAIS
    # permettre d'usurper l'espace `user:<uid>` d'un autre utilisateur, même avec une clé PRO partagée.
    if not require_signed and strong:
        # L'identifiant d'un compte enregistré n'est PAS un secret : sans jeton Bearer il ne donne accès qu'à un
        # espace anonyme distinct (`anon:`), jamais aux données du compte (usurpation par X-User-Id).
        owner = f"anon:{uid}" if _is_registered_account_id(uid) else f"user:{uid}"
        _assert_not_suspended(owner)
        return owner
    if not require_signed and uid and settings.allow_weak_user_id and len(uid) >= 3:
        owner = f"user:{uid[:80]}"
        _assert_not_suspended(owner)
        return owner
    if pkey and _premium_key_ok(pkey):
        import hashlib
        digest = hashlib.sha256(pkey.strip().encode("utf-8")).hexdigest()[:16]
        return f"key:{digest}"
    return None


def _assert_project_owned(owner_id: Optional[str], project_id: Optional[str], project_store: Any) -> Optional[str]:
    """Vérifie qu'un `project_id` soumis existe et appartient strictement à `owner_id`.
    Lève HTTP 404 si inexistant ou détenu par un autre utilisateur (évite l'énumération d'IDs et les documents orphelins).
    """
    if not isinstance(project_id, str) or not project_id.strip():
        return None
    clean_pid = project_id.strip()[:80]
    if not owner_id:
        raise HTTPException(status_code=401, detail="Authentification requise pour associer un projet.")
    if isinstance(project_store, ProjectStore):
        try:
            project_store.get_project(owner_id, clean_pid)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Projet introuvable ou accès non autorisé.",
            ) from exc
    return clean_pid


def _has_pro_access(
    owner_id: Optional[str],
    x_premium_key: Optional[str],
    sub_store: Any = None,
) -> bool:
    """True si clé partenaire PRO valide OU abonnement actif trial/premium en base."""
    pkey = x_premium_key if isinstance(x_premium_key, str) else None
    if _premium_key_ok(pkey):
        return True
    if owner_id and isinstance(sub_store, SubscriptionStore):
        sub = sub_store.get_subscription(owner_id)
        if sub.get("effective_plan_id") in ("trial", "premium"):
            return True
    return False


def _require_pro_access(
    owner_id: Optional[str],
    x_premium_key: Optional[str],
    sub_store: Any,
    feature_label: str,
) -> None:
    if _has_pro_access(owner_id, x_premium_key, sub_store):
        return
    _require_premium_key(x_premium_key, feature_label)


def _consume_user_quota(
    owner_id: Optional[str],
    x_premium_key: Optional[str],
    metric: str,
    sub_store: Any,
    limit_message: str,
) -> None:
    if not owner_id or not isinstance(sub_store, SubscriptionStore):
        return
    pkey = x_premium_key if isinstance(x_premium_key, str) else None
    sub = sub_store.get_subscription(owner_id)
    limits = sub["limits"]
    if _premium_key_ok(pkey) and sub.get("plan_id") == "free" and sub.get("status") == "active":
        limits = DEFAULT_PLANS["premium"]
    limit_val = int(limits.get(f"{metric}_limit", 0))
    try:
        sub_store.consume_usage_atomic(owner_id, metric, limit_val)
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=limit_message) from exc


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def chat_endpoint(
    payload: ChatRequest,
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    agent: FreeDataAIAgent = state["agent"]
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    verified_project_id = _assert_project_owned(owner_id, payload.project_id, project_store)
    tier = payload.tier
    # Le niveau « premium » (LLM payant) exige une clé valide ou un abonnement PRO actif : sinon repli sur le gratuit.
    if tier == "premium" and not _has_pro_access(owner_id, x_premium_key, sub_store):
        tier = "free"
    _consume_user_quota(owner_id, x_premium_key, "daily_chat", sub_store, "Quota journalier de messages atteint.")
    private_chunks: list[dict] = []
    if owner_id and isinstance(doc_store, UserDocumentStore):
        try:
            private_chunks = doc_store.retrieve_for_owner(
                owner_id,
                payload.message,
                project_id=verified_project_id,
                top_k=5,
            )
        except Exception:
            private_chunks = []
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
            private_chunks=private_chunks,
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
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Signaux à vérifier (offre premium) : sauts, divergences entre marchés, séries figées ou arrêtées."""
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    _require_pro_access(owner_id, x_premium_key, sub_store, "Analyse d'anomalies")
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
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Étude saisonnière avancée (offre premium) : calendrier, comparaison de provinces, stratégie de stockage rejouée."""
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    _require_pro_access(owner_id, x_premium_key, sub_store, "Études avancées")
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
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Génère le dossier structuré d'étude de marché PRO (100 % données réelles, zéro hallucination)."""
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    _require_pro_access(owner_id, x_premium_key, sub_store, "Rapports d'étude de marché PRO")
    return _build_study_dossier_or_404(payload, state)


@app.post(
    "/api/v1/reports/market-study/pdf",
    dependencies=[Depends(_chat_rate_limit_dependency)],
)
def generate_market_study_pdf(
    payload: MarketStudyRequest,
    state: dict = Depends(get_state),
    x_premium_key: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Génère et retourne le rapport PDF professionnel d'étude de marché PRO."""
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    _require_pro_access(owner_id, x_premium_key, sub_store, "Rapports d'étude de marché PDF PRO")
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
    _consume_user_quota(owner_id, x_premium_key, "monthly_pdf", sub_store, "Quota mensuel de PDF atteint.")
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


def _require_project_owner(
    x_user_id: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> str:
    owner_id = _resolve_owner_id_optional(
        x_user_id=x_user_id,
        x_premium_key=x_premium_key,
        authorization=authorization,
    )
    if owner_id:
        return owner_id
    require_signed = os.getenv("REQUIRE_SIGNED_USER_AUTH", "0").strip().lower() in ("1", "true", "yes")
    if not require_signed and (x_user_id or "").strip():
        raise HTTPException(
            status_code=401,
            detail="Identifiant d'espace trop faible : mettez à jour l'application "
                   "(identifiant aléatoire d'au moins 32 caractères requis).",
        )
    if require_signed:
        raise HTTPException(status_code=401, detail="Authentification requise (Bearer token).")
    raise HTTPException(status_code=401, detail="Authentification requise (Bearer token, X-Premium-Key, ou X-User-Id).")


def get_agro_profile_store() -> AgronomistProfileStore:
    global _AGRO_PROFILE_STORE
    if _AGRO_PROFILE_STORE is None:
        _AGRO_PROFILE_STORE = AgronomistProfileStore()
    return _AGRO_PROFILE_STORE


class AgroOfficialProfileRequest(BaseModel):
    firm_name: str = Field(..., min_length=2, max_length=120)
    license_number: str = Field(..., min_length=2, max_length=120)
    address: str = Field("", max_length=200)
    contact: str = Field("", max_length=160)


class AgroProfileReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    admin_note: str = Field("", max_length=400)


@app.get("/api/v1/agro/profile", dependencies=[Depends(_data_rate_limit_dependency)])
def get_my_agro_profile_endpoint(
    owner_id: str = Depends(_require_project_owner),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
):
    """Retourne le profil officiel d'agronome / cabinet lié au compte utilisateur."""
    return {"profile": profile_store.get_profile(owner_id)}


@app.put("/api/v1/agro/profile", dependencies=[Depends(_chat_rate_limit_dependency)])
def submit_my_agro_profile_endpoint(
    payload: AgroOfficialProfileRequest,
    owner_id: str = Depends(_require_project_owner),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
):
    """Soumet les informations officielles de l'agronome / cabinet pour validation par l'administrateur."""
    prof = profile_store.submit_profile(
        owner_id,
        firm_name=payload.firm_name,
        license_number=payload.license_number,
        address=payload.address,
        contact=payload.contact,
    )
    return {"profile": prof}


@app.get("/api/v1/admin/agro-profiles", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_agro_profiles_endpoint(
    status: Optional[str] = Query(None, max_length=20),
    x_admin_token: Optional[str] = Header(default=None),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
):
    _require_admin_token(x_admin_token, "manage_subscriptions")
    items = profile_store.list_profiles(status=status)
    return {"count": len(items), "profiles": items}


@app.post("/api/v1/admin/agro-profiles/{target_owner_id}/review", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_review_agro_profile_endpoint(
    target_owner_id: str,
    payload: AgroProfileReviewRequest,
    x_admin_token: Optional[str] = Header(default=None),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
):
    actor, _ = _require_admin_token(x_admin_token, "manage_subscriptions")
    try:
        prof = profile_store.review_profile(
            target_owner_id,
            status=payload.status,
            admin_note=payload.admin_note,
            reviewed_by=actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"profile": prof}


class AgroFieldAssessmentRequest(BaseModel):
    province_hub: Optional[str] = Field(None, max_length=80)
    project_id: Optional[str] = Field(None, max_length=80)
    gps_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    gps_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    area_hectares: Optional[float] = Field(None, gt=0.0, le=500000.0)
    custom_yield_kg_ha: Optional[float] = Field(None, gt=0.0, le=20000.0)
    lab_soil_inputs: dict[str, Any] = Field(default_factory=dict)
    agronomist_field_notes: str = Field("", max_length=4000)
    target_crops: list[str] = Field(default_factory=lambda: ["millet", "sorghum", "maize", "groundnut_raw"])


class AgroFieldPdfRequest(BaseModel):
    agronomist_name: str = Field("", max_length=120)
    agronomist_license: str = Field("", max_length=120)
    agronomist_address: str = Field("", max_length=200)
    agronomist_contact: str = Field("", max_length=160)
    compare_assessment_ids: list[str] = Field(default_factory=list, max_length=4)


class AgroCandidateInput(BaseModel):
    label: str = Field("", max_length=80)
    province_hub: Optional[str] = Field(None, max_length=80)
    gps_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    gps_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    area_hectares: Optional[float] = Field(None, gt=0.0, le=500000.0)
    custom_yield_kg_ha: Optional[float] = Field(None, gt=0.0, le=20000.0)
    lab_soil_inputs: dict[str, Any] = Field(default_factory=dict)
    target_crops: list[str] = Field(default_factory=lambda: ["millet", "sorghum", "maize", "groundnut_raw"])


class AgroCompareRequest(BaseModel):
    assessment_ids: list[str] = Field(default_factory=list, max_length=4)
    candidates: list[AgroCandidateInput] = Field(default_factory=list, max_length=4)
    agronomist_name: str = Field("", max_length=120)
    agronomist_license: str = Field("", max_length=120)
    agronomist_address: str = Field("", max_length=200)
    agronomist_contact: str = Field("", max_length=160)


@app.post("/api/v1/agro/field-assessment", dependencies=[Depends(_chat_rate_limit_dependency)])
def create_agro_field_assessment_endpoint(
    payload: AgroFieldAssessmentRequest,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    store: AgroIndicatorStore = Depends(get_agro_store),
    assess_store: AgroFieldAssessmentStore = Depends(get_agro_assessment_store),
    project_store: ProjectStore = Depends(get_project_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Enregistre les mesures terrain/labo de l'Agronome PRO, calcule l'audit GPS/économique et le payload du rapport."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Diagnostic de terrain Agronome PRO")
    hub = canonical_region(payload.province_hub) if payload.province_hub else None
    if hub is None and payload.gps_lat is not None and payload.gps_lon is not None:
        hub = compute_gps_logistics(payload.gps_lat, payload.gps_lon).get("closest_hub")
    if hub is None or hub == AGRO_NATIONAL:
        raise HTTPException(status_code=422, detail=f"Pôle régional invalide ou coordonnées GPS manquantes. Pôles couverts : {', '.join(AGRO_HUBS)}.")
    verified_pid = _assert_project_owned(owner_id, payload.project_id, project_store)
    regional = store.regional_rows(hub)
    if not regional:
        raise HTTPException(status_code=503, detail="Données agro-climatiques non encore disponibles pour cette zone.")
    fc_df = STATE.get("forecast_df")
    computed = evaluate_field_assessment(
        region=hub,
        regional_rows=regional,
        national_rows=store.national_rows(),
        all_regional_rows=store.rows(),
        lab_soil_inputs=payload.lab_soil_inputs,
        target_crops=payload.target_crops,
        area_hectares=payload.area_hectares,
        gps_lat=payload.gps_lat,
        gps_lon=payload.gps_lon,
        custom_yield_kg_ha=payload.custom_yield_kg_ha,
        forecast_df=fc_df,
        hist_df=STATE.get("hist_df"),
        track_record=STATE.get("track_record"),
    )
    saved = assess_store.create_assessment(
        owner_id,
        province_hub=hub,
        project_id=verified_pid,
        gps_lat=payload.gps_lat,
        gps_lon=payload.gps_lon,
        area_hectares=payload.area_hectares,
        lab_soil_inputs=payload.lab_soil_inputs,
        agronomist_field_notes=payload.agronomist_field_notes,
        target_crops=payload.target_crops,
        computed_scores=computed,
    )
    qa = validate_field_assessment_qa(saved)
    return {"assessment": saved, "qa": qa}


@app.get("/api/v1/agro/field-assessments", dependencies=[Depends(_data_rate_limit_dependency)])
def list_agro_field_assessments_endpoint(
    project_id: Optional[str] = Query(None, max_length=80),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    assess_store: AgroFieldAssessmentStore = Depends(get_agro_assessment_store),
    project_store: ProjectStore = Depends(get_project_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_pro_access(owner_id, x_premium_key, sub_store, "Historique Agronome PRO")
    verified_pid = _assert_project_owned(owner_id, project_id, project_store)
    items = assess_store.list_assessments(owner_id, project_id=verified_pid)
    return {"count": len(items), "assessments": items}


@app.post("/api/v1/agro/field-assessment/{assessment_id}/pdf", dependencies=[Depends(_chat_rate_limit_dependency)])
def agro_field_assessment_pdf_endpoint(
    assessment_id: str,
    payload: Optional[AgroFieldPdfRequest] = None,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    assess_store: AgroFieldAssessmentStore = Depends(get_agro_assessment_store),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Génère le PDF co-brandé Agronome PRO après validation admin du profil officiel et passage porte QA."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Rapport PDF Agronome PRO")
    official = profile_store.get_profile(owner_id)
    if not official or official.get("status") != "approved":
        raise HTTPException(
            status_code=403,
            detail=(
                "Profil officiel agronome non validé par l'administrateur. "
                "Soumettez vos informations officielles depuis « Mon compte » avant de générer un rapport PDF."
            ),
        )
    try:
        saved = assess_store.get_assessment(owner_id, assessment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    qa = validate_field_assessment_qa(saved)
    if not qa["can_deliver_pdf"]:
        raise HTTPException(
            status_code=422,
            detail={"message": "Porte QA échouée : mesures de sol requises pour un Diagnostic de terrain.", "qa": qa},
        )
    _consume_user_quota(owner_id, x_premium_key, "monthly_pdf", sub_store, "Quota mensuel de PDF atteint.")
    comparison_block = None
    if payload and payload.compare_assessment_ids:
        comp_items = [saved]
        for cid in payload.compare_assessment_ids[:3]:
            if cid != assessment_id:
                try:
                    comp_items.append(assess_store.get_assessment(owner_id, cid))
                except KeyError:
                    pass
        if len(comp_items) >= 2:
            comparison_block = compare_agro_assessments(comp_items)
    pdf_bytes = render_agro_assessment_pdf(
        saved,
        agronomist_name=official["firm_name"],
        agronomist_license=official["license_number"],
        agronomist_address=official.get("address") or "",
        agronomist_contact=official.get("contact") or "",
        comparison=comparison_block,
    )
    code = saved.get("report_verification_code") or assessment_id
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="freedata_agro_{code}.pdf"'},
    )


def _evaluate_compare_payload(
    payload: AgroCompareRequest,
    owner_id: str,
    store: AgroIndicatorStore,
    assess_store: AgroFieldAssessmentStore,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    if payload.assessment_ids:
        for aid in payload.assessment_ids[:4]:
            try:
                items.append(assess_store.get_assessment(owner_id, aid))
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=f"Diagnostic introuvable : {aid}") from exc
    elif payload.candidates:
        nat_rows = store.national_rows()
        fc_df = STATE.get("forecast_df")
        hist_df = STATE.get("hist_df")
        tr = STATE.get("track_record")
        for idx, cand in enumerate(payload.candidates[:4]):
            hub = canonical_region(cand.province_hub) if cand.province_hub else None
            if hub is None and cand.gps_lat is not None and cand.gps_lon is not None:
                hub = compute_gps_logistics(cand.gps_lat, cand.gps_lon).get("closest_hub")
            if hub is None or hub == AGRO_NATIONAL:
                raise HTTPException(status_code=422, detail=f"Candidat #{idx + 1} : pôle ou GPS valide requis.")
            regional = store.regional_rows(hub)
            if not regional:
                raise HTTPException(status_code=503, detail=f"Données indisponibles pour {hub}.")
            computed = evaluate_field_assessment(
                region=hub,
                regional_rows=regional,
                national_rows=nat_rows,
                all_regional_rows=store.rows(),
                lab_soil_inputs=cand.lab_soil_inputs,
                target_crops=cand.target_crops,
                area_hectares=cand.area_hectares,
                gps_lat=cand.gps_lat,
                gps_lon=cand.gps_lon,
                custom_yield_kg_ha=cand.custom_yield_kg_ha,
                forecast_df=fc_df,
                hist_df=hist_df,
                track_record=tr,
            )
            items.append({
                "label": cand.label.strip() or f"Terrain {chr(65 + idx)}",
                "province_hub": hub,
                "gps_lat": cand.gps_lat,
                "gps_lon": cand.gps_lon,
                "area_hectares": cand.area_hectares,
                "lab_soil_inputs": cand.lab_soil_inputs,
                "computed_scores": computed,
            })
    if len(items) < 2:
        raise HTTPException(status_code=422, detail="Fournissez entre 2 et 4 diagnostics ou terrains candidats à comparer.")
    return compare_agro_assessments(items), items


@app.post("/api/v1/agro/compare-assessments", dependencies=[Depends(_chat_rate_limit_dependency)])
def compare_agro_assessments_endpoint(
    payload: AgroCompareRequest,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    store: AgroIndicatorStore = Depends(get_agro_store),
    assess_store: AgroFieldAssessmentStore = Depends(get_agro_assessment_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Compare 2 à 4 terrains candidats (par IDs enregistrés ou coordonnées GPS) et les classe par score /100."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Comparaison Multi-Terrains Agronome PRO")
    comparison, _ = _evaluate_compare_payload(payload, owner_id, store, assess_store)
    return comparison


@app.post("/api/v1/agro/compare-assessments/pdf", dependencies=[Depends(_chat_rate_limit_dependency)])
def compare_agro_assessments_pdf_endpoint(
    payload: AgroCompareRequest,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    store: AgroIndicatorStore = Depends(get_agro_store),
    assess_store: AgroFieldAssessmentStore = Depends(get_agro_assessment_store),
    profile_store: AgronomistProfileStore = Depends(get_agro_profile_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Génère le dossier PDF exécutif comparatif multi-terrains (5 blocs + formules vérifiables)."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "PDF Comparatif Multi-Terrains Agronome PRO")
    official = profile_store.get_profile(owner_id)
    if not official or official.get("status") != "approved":
        raise HTTPException(
            status_code=403,
            detail=(
                "Profil officiel agronome non validé par l'administrateur. "
                "Soumettez vos informations officielles depuis « Mon compte » avant de générer un rapport PDF."
            ),
        )
    comparison, items = _evaluate_compare_payload(payload, owner_id, store, assess_store)
    _consume_user_quota(owner_id, x_premium_key, "monthly_pdf", sub_store, "Quota mensuel de PDF atteint.")
    lead = items[0]
    if "report_verification_code" not in lead:
        lead = {**lead, "report_verification_code": f"FDT-{datetime.now(timezone.utc).year}-CMP{len(items)}"}
    pdf_bytes = render_agro_assessment_pdf(
        lead,
        agronomist_name=official["firm_name"],
        agronomist_license=official["license_number"],
        agronomist_address=official.get("address") or "",
        agronomist_contact=official.get("contact") or "",
        comparison=comparison,
    )
    code = lead.get("report_verification_code") or "COMPARE"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="comparatif_agro_{code}.pdf"'},
    )


_MARKET_WATCH_STORE: Optional[MarketWatchlistStore] = None


def get_market_watch_store() -> MarketWatchlistStore:
    global _MARKET_WATCH_STORE
    if _MARKET_WATCH_STORE is None:
        _MARKET_WATCH_STORE = MarketWatchlistStore()
    return _MARKET_WATCH_STORE


class MarketWatchlistCreateRequest(BaseModel):
    crop_id: str = Field(..., min_length=2, max_length=40)
    threshold_xaf_kg: float = Field(..., gt=0.0, le=1000000.0)
    direction: Literal["above", "below"] = "above"
    province: str = Field("", max_length=80)
    market_name: str = Field("", max_length=80)
    note: str = Field("", max_length=240)


@app.get("/api/v1/agro/campaign-radar", dependencies=[Depends(_data_rate_limit_dependency)])
def agro_campaign_radar_endpoint(
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    store: AgroIndicatorStore = Depends(get_agro_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Radar National Agro-Marché (PRO) : double vulnérabilité, meilleure culture/pôle et risque crédit."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Radar National Agro-Marché")
    return build_campaign_radar(
        store.rows(),
        forecast_df=state.get("forecast_df"),
        hist_df=state.get("hist_df"),
        track_record=state.get("track_record") or {},
    )


@app.get("/api/v1/market-pro/overview", dependencies=[Depends(_data_rate_limit_dependency)])
def market_pro_overview_endpoint(
    crop_id: Optional[str] = Query(None, max_length=40),
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    watch_store: MarketWatchlistStore = Depends(get_market_watch_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Marché PRO : prévisions 4 cultures avec MAPE, arbitrage inter-provinces et watchlists évaluées."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Espace Marché PRO")
    fc_df = state.get("forecast_df")
    tr = state.get("track_record") or {}
    watches = evaluate_watchlists(watch_store.list_watches(owner_id), fc_df)
    try:
        arbitrage = compute_inter_province_arbitrage(fc_df, crop_id=crop_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "validated_forecasts": build_validated_forecasts_overview(fc_df, tr),
        "arbitrage": arbitrage,
        "watchlists": watches,
    }


@app.post("/api/v1/market-pro/watchlists", dependencies=[Depends(_data_rate_limit_dependency)])
def create_market_watchlist_endpoint(
    payload: MarketWatchlistCreateRequest,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    watch_store: MarketWatchlistStore = Depends(get_market_watch_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_pro_access(owner_id, x_premium_key, sub_store, "Watchlists Marché PRO")
    try:
        return watch_store.create_watch(
            owner_id,
            crop_id=payload.crop_id,
            threshold_xaf_kg=payload.threshold_xaf_kg,
            direction=payload.direction,
            province=payload.province,
            market_name=payload.market_name,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/v1/market-pro/watchlists/{watch_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_market_watchlist_endpoint(
    watch_id: str,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    watch_store: MarketWatchlistStore = Depends(get_market_watch_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_pro_access(owner_id, x_premium_key, sub_store, "Watchlists Marché PRO")
    if not watch_store.delete_watch(owner_id, watch_id):
        raise HTTPException(status_code=404, detail="Alerte introuvable.")
    return {"deleted": True, "watch_id": watch_id}


@app.get("/api/v1/market-pro/export.csv", dependencies=[Depends(_data_rate_limit_dependency)])
def market_pro_export_csv_endpoint(
    crop_id: Optional[str] = Query(None, max_length=40),
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Export CSV institutionnel des prévisions validées avec provenance, licence et MAPE."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Export CSV Marché PRO")
    try:
        csv_text = export_validated_forecasts_csv(
            state.get("forecast_df"),
            state.get("track_record") or {},
            crop_id=crop_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="freedata_market_pro.csv"'},
    )


@app.get("/api/v1/markets/spatial-arbitrage", dependencies=[Depends(_data_rate_limit_dependency)])
def markets_spatial_arbitrage_endpoint(
    crop_id: str = Query(..., min_length=2, max_length=40),
    transport_cost_xaf_kg: Optional[float] = Query(None, ge=0.0, le=50000.0),
    tonnage: Optional[float] = Query(None, gt=0.0, le=100000.0),
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Arbitrage spatial entre pôles provinciaux avec marge nette, ROI et MAPE hors-temps (PRO)."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Arbitrage spatial Marché PRO")
    try:
        return compute_spatial_arbitrage_detailed(
            state.get("forecast_df"),
            state.get("track_record"),
            crop_id=crop_id,
            transport_cost_xaf_kg=transport_cost_xaf_kg,
            tonnage=tonnage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AgroCreditPassportRequest(BaseModel):
    province: str = Field(..., min_length=2, max_length=80)
    crop_id: str = Field("millet", min_length=2, max_length=40)
    area_hectares: float = Field(..., gt=0.0, le=500000.0)
    loan_amount_xaf: float = Field(..., gt=0.0, le=100_000_000_000.0)


@app.post("/api/v1/markets/credit-passport/agro", dependencies=[Depends(_data_rate_limit_dependency)])
def credit_passport_agro_endpoint(
    payload: AgroCreditPassportRequest,
    state: dict = Depends(get_state),
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    agro_store: AgroIndicatorStore = Depends(get_agro_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Profil Credit Passport Agro : rendement World Bank 2020-2024, DSCR sous 3 scénarios et années sèches."""
    _require_pro_access(owner_id, x_premium_key, sub_store, "Credit Passport Agro PRO")
    hub = canonical_region(payload.province)
    if not hub or hub == AGRO_NATIONAL:
        from src.agro_indicators import HUB_PROVINCE
        hub = next((h for h, p in HUB_PROVINCE.items() if p.lower() == payload.province.strip().lower()), None)
    regional_rows = agro_store.regional_rows(hub) if hub else []
    try:
        return compute_agro_credit_passport(
            province=payload.province,
            crop_id=payload.crop_id,
            area_hectares=payload.area_hectares,
            loan_amount_xaf=payload.loan_amount_xaf,
            hist_df=state.get("hist_df"),
            forecast_df=state.get("forecast_df"),
            passport_df=state.get("passport_df"),
            regional_agro_rows=regional_rows,
            national_agro_rows=agro_store.national_rows(),
            disclaimer=CREDIT_PASSPORT_DISCLAIMER,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    x_premium_key: Optional[str] = Header(default=None),
    store: ProjectStore = Depends(get_project_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    if isinstance(sub_store, SubscriptionStore):
        sub = sub_store.get_subscription(owner_id)
        limits = sub["limits"]
        if _premium_key_ok(x_premium_key) and sub.get("plan_id") == "free" and sub.get("status") == "active":
            limits = DEFAULT_PLANS["premium"]
        max_proj = int(limits.get("max_projects", 5))
        existing_active = store.list_projects(owner_id, include_archived=False, limit=max_proj + 1, offset=0)
        if not payload.idempotency_key and len(existing_active) >= max_proj:
            raise HTTPException(
                status_code=429,
                detail=f"Plafond de projets actifs atteint ({max_proj} max pour votre plan). Archivez un projet ou passez à PRO.",
            )
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
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    conv_store: ConversationStore = Depends(get_conversation_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    try:
        store.delete_project(owner_id, project_id)
        deleted_docs = (
            doc_store.delete_project_documents(owner_id, project_id)
            if isinstance(doc_store, UserDocumentStore)
            else 0
        )
        detached_convs = (
            conv_store.detach_project(owner_id, project_id)
            if isinstance(conv_store, ConversationStore)
            else 0
        )
        return {
            "deleted": True,
            "project_id": project_id,
            "deleted_documents": deleted_docs,
            "detached_conversations": detached_convs,
        }
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
    x_premium_key: Optional[str] = Header(default=None),
    store: ProjectStore = Depends(get_project_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_pro_access(owner_id, x_premium_key, sub_store, "Génération d'études PDF dans un projet PRO")
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
    try:
        created = store.create_study_version(
            owner_id,
            project_id,
            study_id=payload.study_id,
            dossier=dossier,
            generation_params=payload.model_dump(exclude={"study_context"}),
            pdf_bytes=pdf_bytes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _consume_user_quota(owner_id, x_premium_key, "monthly_pdf", sub_store, "Quota mensuel de PDF atteint.")
    return created


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


@app.delete("/api/v1/projects/{project_id}/studies/{study_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_study_endpoint(
    project_id: str,
    study_id: str,
    confirm: bool = Query(False),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    try:
        store.delete_study(owner_id, project_id, study_id)
        return {"deleted": True, "project_id": project_id, "study_id": study_id}
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
    _require_admin_token(x_admin_token, "read_overview")
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
    _require_admin_token(x_admin_token, "manage_data_governance", detail="Jeton administrateur requis pour les décisions de gouvernance.")
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


@app.get("/api/v1/privacy/export", dependencies=[Depends(_data_rate_limit_dependency)])
def export_my_privacy_data_endpoint(
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
    conv_store: ConversationStore = Depends(get_conversation_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Export RGPD complet de l'espace utilisateur (projets, conversations cloud, documents privés, abonnement)."""
    projects = store.list_projects(owner_id, include_archived=True, limit=200, offset=0) if isinstance(store, ProjectStore) else []
    conversations = conv_store.list_conversations(owner_id, include_deleted=True) if isinstance(conv_store, ConversationStore) else []
    documents = doc_store.list_documents(owner_id) if isinstance(doc_store, UserDocumentStore) else []
    billing = sub_store.get_usage_summary(owner_id) if isinstance(sub_store, SubscriptionStore) else {}
    agro_assessments = []
    agro_official_profile = None
    market_watchlists = []
    try:
        agro_assessments = get_agro_assessment_store().list_assessments(owner_id, limit=100)
    except Exception:
        pass
    try:
        agro_official_profile = get_agro_profile_store().get_profile(owner_id)
    except Exception:
        pass
    try:
        market_watchlists = get_market_watch_store().list_watches(owner_id)
    except Exception:
        pass
    return {
        "owner_id": owner_id,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subscription": billing.get("subscription"),
        "quotas": billing.get("quotas"),
        "projects": projects,
        "conversations": conversations,
        "documents": documents,
        "agro_assessments": agro_assessments,
        "agro_official_profile": agro_official_profile,
        "market_watchlists": market_watchlists,
    }


@app.delete("/api/v1/privacy/my-data", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_my_data_endpoint(
    confirm: bool = Query(False),
    owner_id: str = Depends(_require_project_owner),
    store: ProjectStore = Depends(get_project_store),
    conv_store: ConversationStore = Depends(get_conversation_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation explicite requise (?confirm=true).")
    deleted_convs = conv_store.purge_owner(owner_id) if isinstance(conv_store, ConversationStore) else 0
    deleted_docs = doc_store.purge_owner(owner_id) if isinstance(doc_store, UserDocumentStore) else 0
    out = PrivacyController.delete_user_data(store, owner_id)
    out["deleted_conversations"] = deleted_convs
    out["deleted_documents"] = deleted_docs
    try:
        out["deleted_agro_assessments"] = get_agro_assessment_store().purge_owner(owner_id)
    except Exception:
        out["deleted_agro_assessments"] = 0
    try:
        out["deleted_agro_official_profiles"] = get_agro_profile_store().purge_owner(owner_id)
    except Exception:
        out["deleted_agro_official_profiles"] = 0
    try:
        out["deleted_market_watchlists"] = get_market_watch_store().purge_owner(owner_id)
    except Exception:
        out["deleted_market_watchlists"] = 0
    return out


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
    anom_df = state.get("anomalies")
    if anom_df is None or (isinstance(anom_df, pd.DataFrame) and anom_df.empty):
        anom_df = state.get("anomalies_df", pd.DataFrame())
    return svc.get_anomalies(
        anom_df,
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
_MODEL_REGISTRY.seed_builtin_models(data_ready=False)
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
    anom_df = state.get("anomalies")
    if anom_df is None or (isinstance(anom_df, pd.DataFrame) and anom_df.empty):
        anom_df = state.get("anomalies_df", pd.DataFrame())
    return orch.handle(
        payload.query,
        forecast_df=state["forecast_df"],
        hist_df=state.get("hist_df", pd.DataFrame()),
        passport_df=state.get("passport_df", pd.DataFrame()),
        anomalies_df=anom_df,
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
    _require_admin_token(x_admin_token, "manage_system", detail="Jeton administrateur requis.")
    return km.issue_key(payload.owner_id, label=payload.label, daily_quota=payload.daily_quota)


@app.post("/api/v1/developer/keys/{key_id}/revoke", dependencies=[Depends(_admin_rate_limit_dependency)])
def revoke_developer_key_endpoint(
    key_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
):
    _require_admin_token(x_admin_token, "manage_system", detail="Jeton administrateur requis.")
    try:
        return km.revoke_key(key_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/developer/keys", dependencies=[Depends(_admin_rate_limit_dependency)])
def list_developer_keys_endpoint(
    x_admin_token: Optional[str] = Header(default=None),
    km: ApiKeyManager = Depends(get_api_key_manager),
):
    _require_admin_token(x_admin_token, "manage_system", detail="Jeton administrateur requis.")
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
    authorization: Optional[str] = Header(default=None),
    ent: EntitlementManager = Depends(get_entitlement_manager),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    eff_tier = "premium" if _has_pro_access(owner_id, x_premium_key, sub_store) else "free"
    uid = (owner_id or x_user_id or "anonymous").strip()[:80]
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
    authorization: Optional[str] = Header(default=None),
    rag: HybridRAGEngine = Depends(get_hybrid_rag),
    svc: AnalyticsService = Depends(get_analytics_service),
    ent: EntitlementManager = Depends(get_entitlement_manager),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    owner_id = _resolve_owner_id_optional(x_user_id=x_user_id, x_premium_key=x_premium_key, authorization=authorization)
    verified_project_id = _assert_project_owned(owner_id, payload.project_id, project_store)
    eff_tier = "premium" if (payload.tier == "premium" and _has_pro_access(owner_id, x_premium_key, sub_store)) else "free"
    _consume_user_quota(owner_id, x_premium_key, "daily_chat", sub_store, "Quota journalier de messages atteint.")
    uid = (owner_id or x_user_id or "anonymous").strip()[:80]
    try:
        quota_info = ent.consume_chat_quota(eff_tier, uid)
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    private_chunks: list[dict] = []
    if owner_id and isinstance(doc_store, UserDocumentStore):
        try:
            private_chunks = doc_store.retrieve_for_owner(
                owner_id,
                payload.message,
                project_id=verified_project_id,
                top_k=5,
            )
        except Exception:
            private_chunks = []

    domain_mod = DomainRegistry.classify_domain(payload.message, explicit_domain=payload.domain)
    if not DomainRegistry.is_domain_active(domain_mod.domain_id):
        raise HTTPException(
            status_code=503,
            detail=f"Le domaine '{domain_mod.label_fr}' est actuellement désactivé par l'administrateur.",
        )
    if domain_mod.required_tier == "premium" and eff_tier != "premium":
        raise HTTPException(
            status_code=403,
            detail=f"Le domaine '{domain_mod.label_fr}' nécessite un abonnement Partenaire PRO.",
        )
    DomainRegistry.record_usage(domain_mod.domain_id)
    agent: FreeDataAIAgent = state["agent"]

    if domain_mod.execution_pipeline == "chad_agent":
        if domain_mod.domain_id == "agriculture":
            return _handle_agriculture_chat(
                payload=payload,
                agent=agent,
                eff_tier=eff_tier,
                private_chunks=private_chunks,
                quota_info=quota_info,
                domain_mod=domain_mod,
                rag=rag,
                owner_id=owner_id,
            )
        res = agent.answer(
            payload.message,
            history=payload.history,
            tier=eff_tier,
            study_context=payload.study_context,
            private_chunks=private_chunks,
        )
        return {**res, "domain": domain_mod.domain_id, "domain_label": domain_mod.label_fr, "quota": quota_info}

    if domain_mod.execution_pipeline == "ml_orchestrator":
        orch = IntelligenceOrchestrator(analytics=svc, rag=rag)
        anom_df = state.get("anomalies")
        if anom_df is None or (isinstance(anom_df, pd.DataFrame) and anom_df.empty):
            anom_df = state.get("anomalies_df", pd.DataFrame())
        out = orch.handle(
            payload.message,
            forecast_df=state["forecast_df"],
            hist_df=state.get("hist_df", pd.DataFrame()),
            passport_df=state.get("passport_df", pd.DataFrame()),
            anomalies_df=anom_df,
        )
        return {
            "reply": f"**[{domain_mod.label_fr}]** Outil exécuté : `{out['tool_used']}` (portée : {out['geographic_scope']}, méthodologie : {out['methodology']}).",
            "intent": out["tool_used"],
            "entities": {},
            "sources": [{"title": str(s)} for s in out.get("sources", [])] + [
                {"title": c["title"], "source": c["source"], "score": c["similarity"]} for c in private_chunks
            ],
            "summary": out["result"],
            "domain": domain_mod.domain_id,
            "domain_label": domain_mod.label_fr,
            "quota": quota_info,
        }

    # General AI, Education, Academic Research, Tech & Programming, Productivity
    rag_hits = list(private_chunks) + rag.search(payload.message, top_k=3)
    sources = [
        {"title": h["title"], "source": h["source"], "score": h.get("score") or h.get("similarity")}
        for h in rag_hits
    ]
    if private_chunks and settings.llm_api_key:
        doc_facts = "**Contexte documentaire privé (indexation Jina) :**\n" + "\n".join(
            f"- **{c.get('titre')}** (segment {c.get('page', 1)}) : {c.get('content', '')}"
            for c in private_chunks
        )
        reply = agent._synthesize_with_llm(
            payload.message,
            doc_facts,
            private_chunks,
            history=payload.history,
        )
    elif eff_tier == "premium" and settings.llm_api_key:
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


def _match_agro_hub_in_query(query: str) -> Optional[str]:
    """Détecte si la question mentionne l'un des 12 pôles agro-climatiques couverts."""
    q_low = (query or "").lower().replace("’", "'")
    for hub in AGRO_HUBS:
        if hub.lower() in q_low:
            return hub
        cand = canonical_region(hub)
        if cand and cand.lower() in q_low:
            return cand
    # Support des variantes sans accent (ex: Abeche -> Abéché, N'Djamena -> Ndjamena)
    import unicodedata
    q_ascii = "".join(
        ch for ch in unicodedata.normalize("NFKD", q_low) if not unicodedata.combining(ch)
    )
    for hub in AGRO_HUBS:
        h_ascii = "".join(
            ch for ch in unicodedata.normalize("NFKD", hub.lower()) if not unicodedata.combining(ch)
        )
        if h_ascii in q_ascii or h_ascii.replace("'", "") in q_ascii.replace("'", ""):
            return hub
    return None


def _handle_agriculture_chat(
    *,
    payload: PlatformChatRequest,
    agent: FreeDataAIAgent,
    eff_tier: Literal["free", "premium"],
    private_chunks: list[dict],
    quota_info: dict,
    domain_mod: Any,
    rag: Optional[HybridRAGEngine] = None,
    owner_id: Optional[str] = None,
) -> dict[str, Any]:
    """Ancre les réponses Chat + RAG/LLM du domaine `agriculture` sur NASA POWER, World Bank, WFP/FEWS NET et les bulletins privés."""
    try:
        agro_store = get_agro_store()
        all_rows = agro_store.rows()
    except Exception as exc:
        logger.warning("AgroIndicatorStore indisponible dans le chat (%s) — repli agent standard", exc)
        all_rows = []

    if not all_rows:
        res = agent.answer(
            payload.message,
            history=payload.history,
            tier=eff_tier,
            study_context=payload.study_context,
            private_chunks=private_chunks,
        )
        return {**res, "domain": domain_mod.domain_id, "domain_label": domain_mod.label_fr, "quota": quota_info}

    matched_hub = _match_agro_hub_in_query(payload.message)
    national_rows = [r for r in all_rows if r.get("region") == AGRO_NATIONAL]
    sources: list[dict[str, Any]] = [
        {"title": "NASA POWER Agro (12 pôles Tchad, 2020–2026)", "source": "NASA POWER Agro · Public Domain"},
        {"title": "World Bank — Indicateurs agricoles nationaux Tchad (2000–2025)", "source": "World Bank · CC BY 4.0"},
    ] + [
        {"title": c.get("titre") or c.get("title", "Document privé"), "source": c.get("source", "Document privé"), "score": c.get("similarity")}
        for c in private_chunks
    ]

    if matched_hub:
        regional = [r for r in all_rows if r.get("region") == matched_hub]
        profile = build_zone_profile(matched_hub, regional, national_rows)
        series = profile.get("series") or {}
        rz_pts = series.get("root_zone_wetness") or []
        sf_pts = series.get("surface_wetness") or []
        rz_last = rz_pts[-1] if rz_pts else {}
        sf_last = sf_pts[-1] if sf_pts else {}
        alerts = profile.get("alerts") or []
        _lvl_fr = {"moderate": "modérée", "severe": "sévère"}
        alert_text = (
            ", ".join(
                f"{a.get('label') or a.get('indicator_label') or a.get('indicator_key') or 'Déficit hydrique'} "
                f"({_lvl_fr.get(str(a.get('level') or '').lower(), a.get('level') or 'alerte')})"
                for a in alerts
            )
            if alerts
            else "normale"
        )
        risks = profile.get("hydric_risk_signals") or {}
        prov = profile.get("provenance") or {}
        sp_res = prov.get("spatial_resolution", "regional_city_hub")
        if isinstance(sp_res, (list, tuple)):
            sp_res = ", ".join(str(x) for x in sp_res) or "regional_city_hub"
        conf_lvl = prov.get("confidence_level", "Satellite_Modeled_Regional")
        if isinstance(conf_lvl, (list, tuple)):
            conf_lvl = ", ".join(str(x) for x in conf_lvl) or "Satellite_Modeled_Regional"
        lines = [
            f"### Pré-diagnostic agro-climatique de zone — {matched_hub}",
            f"- **Résolution géographique** : Pôle régional (`{sp_res}`, niveau `{conf_lvl}`). Ce n'est pas une analyse de parcelle.",
        ]
        if rz_last:
            lines.append(
                f"- **Humidité zone racinaire** ({rz_last.get('reference_date', '—')}) : `{rz_last.get('value', '—')}` "
                f"(écart vs normale 2020–2023 : `{rz_last.get('anomaly_pct', '—')} %`, alerte : `{alert_text}`)."
            )
        if sf_last:
            lines.append(
                f"- **Humidité de surface** ({sf_last.get('reference_date', '—')}) : `{sf_last.get('value', '—')}` "
                f"(écart vs normale 2020–2023 : `{sf_last.get('anomaly_pct', '—')} %`)."
            )
        if risks:
            lines.append(
                f"- **Signaux hydriques** : faux démarrage de semis = `{'OUI — alerte' if risks.get('false_sowing_start') else 'Non'}`, "
                f"années critiques (< 0,45 en juil.–août) = `{risks.get('critical_july_aug_years', 0)}`, "
                f"rendement céréalier moyen national (World Bank 2020–2024) = `{risks.get('cereal_yield_mean_2020_2024_kg_ha', '—')} kg/ha`."
            )
        lines.append(
            "- **Limites strictes** : aucune donnée de température, de précipitations ou de pH automatique n'est présente dans ce jeu de données."
        )
        agro_facts = "\n".join(lines)
    else:
        overview = build_zones_overview(all_rows)
        zones_list = overview.get("zones") or []
        latest_dates = [z.get("last_reference_date") for z in zones_list if z.get("last_reference_date")]
        latest_period = max(latest_dates) if latest_dates else "—"
        lines = [
            "### Synthèse agro-climatique du Tchad (12 pôles NASA POWER Agro + World Bank)",
            f"- **Pôles couverts ({len(zones_list)})** : {', '.join(z.get('region', '') for z in zones_list)}.",
            f"- **Dernière période observée** : `{latest_period}`.",
            "- **Limites strictes** : données modélisées au niveau pôle régional (`NASA POWER Agro`) et macro national (`World Bank CC BY 4.0`). Aucune température ni pluviométrie disponible.",
        ]
        agro_facts = "\n".join(lines)

    # 1. Couplage prix ML validés (toutes les cultures agricoles et produits disponibles dans forecast_df)
    fc_df = STATE.get("forecast_df")
    if fc_df is not None and not getattr(fc_df, "empty", True):
        try:
            fc_overview = build_validated_forecasts_overview(fc_df, STATE.get("track_record") or {})
            seen_comms = {f.get("commodity_std") for f in fc_overview if f.get("commodity_std")}
            extra_lines: list[str] = []
            if "commodity_std" in fc_df.columns and "predicted_price" in fc_df.columns:
                tr = STATE.get("track_record") or {}
                for comm, grp in fc_df.groupby("commodity_std"):
                    if comm in seen_comms:
                        continue
                    pred_mean = grp["predicted_price"].dropna().mean()
                    if pd.notna(pred_mean):
                        mape = (tr.get(comm) or {}).get("mape_pct")
                        mape_txt = f"{round(float(mape), 2)} %" if isinstance(mape, (int, float)) else "N/D"
                        extra_lines.append(f"- **{comm}** : `{round(float(pred_mean), 1)} XAF/kg` (MAPE : `{mape_txt}`)")
            if fc_overview or extra_lines:
                agro_facts += "\n\n**Prévisions de prix disponibles sur la plateforme (WFP/FEWS NET · Delta-Ridge ML) :**\n" + "\n".join(
                    [
                        f"- **{f['label_fr']}** : `{f.get('predicted_xaf_kg', '—')} XAF/kg` (MAPE historique : `{f.get('historical_mape_pct', 'N/D')} %`)"
                        for f in fc_overview
                    ] + extra_lines
                )
        except Exception:
            pass

    # 2. Bulletin d'audit parcellaire privé de l'utilisateur (si référence FDT-... ou diagnostic existant)
    if owner_id:
        try:
            user_assessments = get_agro_assessment_store().list_assessments(owner_id, limit=5)
            matched_assess = None
            q_upper = (payload.message or "").upper()
            for a in user_assessments:
                code = str(a.get("report_verification_code") or "").upper()
                if code and code in q_upper:
                    matched_assess = a
                    break
            if matched_assess is None and user_assessments and any(
                kw in (payload.message or "").lower() for kw in ("bulletin", "parcelle", "diagnostic", "score", "fdt-")
            ):
                matched_assess = user_assessments[0]
            if matched_assess:
                cs = matched_assess.get("computed_scores") or {}
                ws = cs.get("weighted_score") or {}
                bd = ws.get("breakdown") or {}
                gps = cs.get("gps_logistics") or {}
                econ = cs.get("verified_economics") or {}
                bulletin = cs.get("bulletin") or {}
                lab_params = bulletin.get("lab_parameters") or []
                crops = cs.get("crop_assessments") or []
                rx = bulletin.get("prescriptions") or []
                idw_hubs = [
                    f"{h.get('hub')} ({h.get('road_distance_km', '—')} km, {h.get('weight_pct', 0)}%)"
                    for h in (gps.get("idw_hubs") or [])
                    if (h.get("weight_pct") or 0) > 0
                ]
                gps_txt = (
                    f"{gps.get('gps_lat')}, {gps.get('gps_lon')}"
                    if gps.get("gps_provided")
                    else "Non fournies"
                )

                b_lines = [
                    f"### Analyse détaillée du bulletin {matched_assess.get('report_verification_code')}",
                    f"**1. Identification & Logistique IDW :** Pôle `{matched_assess.get('province_hub')}`, "
                    f"Surface `{matched_assess.get('area_hectares') or '1.0'} ha`, GPS `{gps_txt}`, "
                    f"Distance pôle `{gps.get('distance_hub_km', '—')} km`, Distance N'Djamena `{gps.get('distance_ndjamena_km', '—')} km`, "
                    f"Décote bord-champ `-{gps.get('farmgate_discount_pct', 8)}%`.",
                    f"- **Score global** : `{ws.get('total_score', '—')}/100` ({ws.get('verdict', '—')}) — "
                    f"Eau `{bd.get('hydric_security', {}).get('score', '—')}/50` + "
                    f"Sol `{bd.get('soil_quality', {}).get('score', '—')}/30` + "
                    f"Marché `{bd.get('market_logistics', {}).get('score', '—')}/20` · Confiance : `{cs.get('confidence_level', '—')}`.",
                ]
                if idw_hubs:
                    b_lines.append(f"- **Interpolation IDW (k=3)** : {' · '.join(idw_hubs)}.")

                if lab_params:
                    b_lines.append("\n**2. Paramètres Pédologiques & Agro-Climatiques :**")
                    for p in lab_params:
                        b_lines.append(
                            f"- **{p.get('parameter')}** : `{p.get('value')}` (norme `{p.get('optimal')}`, statut : `{p.get('status')}`, source : {p.get('source')})"
                        )

                if crops:
                    b_lines.append("\n**3. Matrice des 4 cultures & Rentabilité :**")
                    for c in crops:
                        ce = c.get("verified_economics") or {}
                        b_lines.append(
                            f"- **{c.get('label_fr')}** : `{c.get('suitability_score')}/100` ({c.get('suitability_label')}) "
                            f"[Eau `{c.get('water_score', '—')}/50` + Sol `{c.get('soil_score', '—')}/30` + Marché `{c.get('market_score', '—')}/20`] · "
                            f"Prix bord-champ `{ce.get('farmgate_price_central_xaf_kg', 'N/A')} FCFA/kg` · "
                            f"CA brut estimé `{c.get('indicative_gross_revenue_xaf', '—')} FCFA`"
                        )
                if econ.get("formula_text"):
                    b_lines.append(
                        f"- **Formule vérifiable** : `{econ['formula_text']}` "
                        f"(Plancher stress 2024–2026 : `{econ.get('ca_stress_xaf', '—')} FCFA`, incertitude `±{econ.get('mape_pct', '—')}%`)."
                    )
                if econ.get("arbitrage_bonus"):
                    ab = econ["arbitrage_bonus"]
                    b_lines.append(
                        f"- **Opportunité d'expédition directe** : `{ab.get('target_province')}` à `{ab.get('target_price_xaf_kg')} FCFA/kg` "
                        f"(+{ab.get('spread_xaf_kg')} FCFA/kg, soit +{ab.get('potential_gross_gain_xaf')} FCFA brut)."
                    )

                if rx or matched_assess.get("agronomist_field_notes"):
                    b_lines.append("\n**4. Prescriptions Techniques & Aide à la Décision :**")
                    for r in rx:
                        b_lines.append(f"- {r}")
                    if matched_assess.get("agronomist_field_notes"):
                        b_lines.append(f"- *Observations terrain* : {matched_assess['agronomist_field_notes']}")

                agro_facts += "\n\n" + "\n".join(b_lines)
        except Exception:
            pass

    # 3. Recherche RAG hybride (base méthodologique + documents privés)
    rag_hits: list[dict] = []
    if rag is not None:
        try:
            rag_hits = rag.search(payload.message, top_k=3)
            for h in rag_hits:
                sources.append({
                    "title": h.get("title", "Base de connaissances"),
                    "source": h.get("source", "RAG FreeData.td"),
                    "score": h.get("score"),
                })
        except Exception:
            rag_hits = []

    if private_chunks:
        agro_facts += "\n\n**Extraits des documents privés :**\n" + "\n".join(
            f"- **{c.get('titre') or c.get('title', 'Document')}** : {c.get('content', '')[:320]}"
            for c in private_chunks[:3]
        )
    if rag_hits:
        agro_facts += "\n\n**Références méthodologiques (RAG) :**\n" + "\n".join(
            f"- *{h.get('source', 'RAG')}* : {h.get('compressed_excerpt', '')[:240]}"
            for h in rag_hits[:2]
        )

    reply = agro_facts
    if eff_tier == "premium" and settings.llm_api_key:
        llm_reply = agent._synthesize_with_llm(
            payload.message,
            agro_facts,
            list(private_chunks) + rag_hits,
            history=payload.history,
        )
        if llm_reply and llm_reply.strip():
            reply = llm_reply

    return {
        "reply": reply,
        "intent": "agro_zone_prediagnostic",
        "entities": {"region": matched_hub} if matched_hub else {},
        "sources": sources,
        "domain": domain_mod.domain_id,
        "domain_label": domain_mod.label_fr,
        "quota": quota_info,
    }


def _fallback_domain_reply(domain_mod, query: str, rag_hits: list[dict]) -> str:
    status_note = (
        "\n\n*Statut des données Tchad : ce domaine est actuellement en préparation. "
        "Vous pouvez joindre vos propres documents (PDF, CSV, TXT) pour une analyse ciblée.*"
        if getattr(domain_mod, "data_status", "") == "in_preparation"
        else ""
    )
    base = f"**[{domain_mod.label_fr}]** {domain_mod.instructions}{status_note}"
    if rag_hits:
        excerpts = "\n".join(f"- *{h['source']}* : {h['compressed_excerpt']}" for h in rag_hits[:2])
        return f"{base}\n\n**Références trouvées dans la base de connaissances :**\n{excerpts}"
    return f"{base}\n\nVotre demande (« {query[:120]} ») est prête à être approfondie ; précisez le contexte ou les contraintes souhaitées."


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Phase 12 — User Accounts (JWT Bearer), Subscriptions, Payments & Quotas
# ---------------------------------------------------------------------------
class AuthRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=160)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field("", max_length=80)


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=160)
    password: str = Field(..., min_length=1, max_length=128)


@app.post("/api/v1/auth/register", dependencies=[Depends(_chat_rate_limit_dependency)])
def auth_register_endpoint(
    payload: AuthRegisterRequest,
    auth_store: AuthStore = Depends(get_auth_store),
):
    try:
        secret = get_auth_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        user = auth_store.register(payload.email, payload.password, display_name=payload.display_name)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session = auth_store.issue_session(user, secret=secret, ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS)
    owner_id = f"user:{user['user_id']}"
    session["owner_id"] = owner_id
    session["is_pro"] = False
    try:
        sub_store = get_subscription_store()
        session["subscription"] = sub_store.get_subscription(owner_id)
        session["is_pro"] = _has_pro_access(owner_id, None, sub_store)
    except Exception:
        pass
    return session


@app.post("/api/v1/auth/login", dependencies=[Depends(_chat_rate_limit_dependency)])
def auth_login_endpoint(
    payload: AuthLoginRequest,
    auth_store: AuthStore = Depends(get_auth_store),
):
    try:
        secret = get_auth_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        user = auth_store.authenticate(payload.email, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    session = auth_store.issue_session(user, secret=secret, ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS)
    owner_id = f"user:{user['user_id']}"
    session["owner_id"] = owner_id
    session["is_pro"] = False
    try:
        sub_store = get_subscription_store()
        session["subscription"] = sub_store.get_subscription(owner_id)
        session["is_pro"] = _has_pro_access(owner_id, None, sub_store)
    except Exception:
        pass
    return session


@app.get("/api/v1/auth/me", dependencies=[Depends(_data_rate_limit_dependency)])
def auth_me_endpoint(
    authorization: Optional[str] = Header(default=None),
    x_premium_key: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    sub_id, _ = _require_bearer_user_id(authorization, auth_store)
    user = auth_store.get_user(sub_id)
    if not user:
        raise HTTPException(status_code=401, detail="Compte introuvable.")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Compte suspendu par l'administrateur. Contactez le support.")
    owner_id = f"user:{user['user_id']}"
    _assert_not_suspended(owner_id, skip_auth_store_check=True)
    sub = sub_store.get_subscription(owner_id)
    is_pro = _has_pro_access(owner_id, x_premium_key, sub_store)
    return {"user": user, "owner_id": owner_id, "subscription": sub, "is_pro": is_pro}


@app.post("/api/v1/auth/logout", dependencies=[Depends(_data_rate_limit_dependency)])
def auth_logout_endpoint(
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
):
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentification Bearer requise.")
    tok = authorization.split(" ", 1)[1].strip()
    auth_secret = os.getenv("AUTH_SECRET", "").strip()
    # Ne persister en base que des jetons réellement signés (évite le remplissage de revoked_tokens par des chaînes arbitraires).
    if auth_secret and verify_signed_user_token(tok, auth_secret):
        auth_store.revoke_token(tok)
    return {"logged_out": True}


@app.post("/api/v1/auth/refresh", dependencies=[Depends(_chat_rate_limit_dependency)])
def auth_refresh_endpoint(
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
):
    sub_id, old_tok = _require_bearer_user_id(authorization, auth_store)
    user = auth_store.get_user(sub_id)
    if not user:
        raise HTTPException(status_code=401, detail="Compte introuvable.")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Compte suspendu par l'administrateur. Contactez le support.")
    _assert_not_suspended(f"user:{sub_id}", skip_auth_store_check=True)
    if auth_store.session_age_seconds(old_tok) > MAX_SESSION_LIFETIME_SECONDS:
        raise HTTPException(status_code=401, detail="Session trop ancienne : reconnectez-vous avec votre mot de passe.")
    from src.security import token_claims as _claims
    try:
        new_session = auth_store.issue_session(user, original_iat=int(_claims(old_tok).get("oiat") or 0) or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    auth_store.revoke_token(old_tok)
    return new_session


class AuthProfileUpdateRequest(BaseModel):
    display_name: str = Field(..., max_length=80)


class AuthChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class AuthDeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


def _require_bearer_user_id(authorization: Optional[str], auth_store: AuthStore) -> tuple[str, str]:
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentification Bearer requise.")
    tok = authorization.split(" ", 1)[1].strip()
    sub_id = auth_store.verify_session_token(tok)
    if not sub_id:
        raise HTTPException(status_code=401, detail="Session invalide, révoquée ou expirée.")
    if _ACCOUNT_ID_RE.fullmatch(sub_id) and auth_store.is_token_stale(tok, sub_id):
        raise HTTPException(status_code=401, detail="Session expirée (mot de passe modifié). Veuillez vous reconnecter.")
    return sub_id, tok


@app.patch("/api/v1/auth/profile", dependencies=[Depends(_data_rate_limit_dependency)])
def auth_update_profile_endpoint(
    payload: AuthProfileUpdateRequest,
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
):
    sub_id, _ = _require_bearer_user_id(authorization, auth_store)
    try:
        user = auth_store.update_profile(sub_id, display_name=payload.display_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user": user}


@app.post("/api/v1/auth/change-password", dependencies=[Depends(_chat_rate_limit_dependency)])
def auth_change_password_endpoint(
    payload: AuthChangePasswordRequest,
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
):
    sub_id, _ = _require_bearer_user_id(authorization, auth_store)
    try:
        user = auth_store.change_password(
            sub_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Les anciens jetons sont invalidés : on renvoie une session neuve pour l'appareil courant.
    secret = get_auth_secret()
    return {"updated": True, "user": user, "session": auth_store.issue_session(user, secret=secret)}


@app.post("/api/v1/auth/delete-account", dependencies=[Depends(_chat_rate_limit_dependency)])
def auth_delete_account_endpoint(
    payload: AuthDeleteAccountRequest,
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
    conv_store: ConversationStore = Depends(get_conversation_store),
    project_store: ProjectStore = Depends(get_project_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    sub_id, tok = _require_bearer_user_id(authorization, auth_store)
    try:
        auth_store.delete_account(sub_id, password=payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    owner_id = f"user:{sub_id}"
    if isinstance(conv_store, ConversationStore):
        conv_store.purge_owner(owner_id)
    if isinstance(doc_store, UserDocumentStore):
        doc_store.purge_owner(owner_id)
    # Effacement complet (RGPD) : abonnement, usages, demandes de paiement, tickets, avis, diagnostics agro et watchlists.
    for purge in (
        lambda: sub_store.purge_user(owner_id),
        lambda: get_support_store().purge_owner(owner_id),
        lambda: get_agro_assessment_store().purge_owner(owner_id),
        lambda: get_agro_profile_store().purge_owner(owner_id),
        lambda: get_market_watch_store().purge_owner(owner_id),
    ):
        try:
            purge()
        except Exception as exc:
            logger.warning("Purge partielle lors de la suppression de compte : %s", exc)
    if isinstance(project_store, ProjectStore):
        for p in project_store.list_projects(owner_id, include_archived=True):
            try:
                project_store.delete_project(owner_id, p["project_id"])
            except Exception:
                pass
    auth_store.revoke_token(tok)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Cloud Conversation Sync (multi-appareils pour comptes connectés)
# ---------------------------------------------------------------------------
class CloudConversationPayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field("Nouvelle conversation", max_length=140)
    isSavedInLibrary: bool = False
    isDeleted: bool = False
    projectId: Optional[str] = Field(None, max_length=80)
    projectName: Optional[str] = Field(None, max_length=140)
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    messages: list[dict] = Field(default_factory=list)


class CloudConversationSyncRequest(BaseModel):
    conversations: list[dict] = Field(default_factory=list)


@app.get("/api/v1/conversations", dependencies=[Depends(_data_rate_limit_dependency)])
def list_cloud_conversations_endpoint(
    include_deleted: bool = Query(True),
    owner_id: str = Depends(_require_project_owner),
    conv_store: ConversationStore = Depends(get_conversation_store),
):
    items = conv_store.list_conversations(owner_id, include_deleted=include_deleted)
    return {"count": len(items), "conversations": items}


@app.put("/api/v1/conversations/{conversation_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def upsert_cloud_conversation_endpoint(
    conversation_id: str,
    payload: CloudConversationPayload,
    owner_id: str = Depends(_require_project_owner),
    conv_store: ConversationStore = Depends(get_conversation_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    verified_pid = _assert_project_owned(owner_id, payload.projectId, project_store)
    data = payload.model_dump()
    data["id"] = conversation_id
    data["projectId"] = verified_pid
    if verified_pid is None:
        data["projectName"] = None
    try:
        saved = conv_store.upsert_conversation(owner_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return saved


@app.post("/api/v1/conversations/sync", dependencies=[Depends(_data_rate_limit_dependency)])
def sync_cloud_conversations_endpoint(
    payload: CloudConversationSyncRequest,
    owner_id: str = Depends(_require_project_owner),
    conv_store: ConversationStore = Depends(get_conversation_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    owned_pids: set[str] = set()
    if isinstance(project_store, ProjectStore):
        owned_pids = {
            str(p["project_id"])
            for p in project_store.list_projects(owner_id, include_archived=True, limit=200, offset=0)
        }
    sanitized_incoming: list[dict] = []
    for item in payload.conversations or []:
        if not isinstance(item, dict):
            continue
        clean_item = dict(item)
        raw_pid = clean_item.get("projectId") or clean_item.get("project_id")
        if raw_pid and str(raw_pid).strip() not in owned_pids:
            # Detach deleted or unauthorized project IDs instead of allowing cross-tenant association
            clean_item["projectId"] = None
            clean_item["projectName"] = None
        sanitized_incoming.append(clean_item)
    merged = conv_store.sync_conversations(owner_id, sanitized_incoming)
    return {"count": len(merged), "conversations": merged}


@app.delete("/api/v1/conversations/{conversation_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_cloud_conversation_endpoint(
    conversation_id: str,
    owner_id: str = Depends(_require_project_owner),
    conv_store: ConversationStore = Depends(get_conversation_store),
):
    deleted = conv_store.delete_conversation(owner_id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return {"deleted": True, "conversation_id": conversation_id}


@app.get("/api/v1/billing/plans", dependencies=[Depends(_data_rate_limit_dependency)])
def list_billing_plans_endpoint():
    return {
        "plans": get_configured_plans(),
        "payment_provider_status": "mobile_money_and_stripe_ready",
        "note": "Aucun plan n'est illimité ; les quotas journaliers/mensuels sont appliqués côté serveur.",
    }


@app.get("/api/v1/billing/payment-methods", dependencies=[Depends(_data_rate_limit_dependency)])
def list_payment_methods_endpoint():
    return get_payment_methods()


class PaymentRequestCreate(BaseModel):
    provider: Literal["airtel_money", "moov_money", "bank_transfer", "mobile_money", "stripe"] = "airtel_money"
    plan_id: Literal["trial", "premium"] = "premium"
    phone_or_ref: str = Field(..., min_length=3, max_length=80)
    transaction_ref: str = Field(..., min_length=3, max_length=120)
    amount_xaf: int = Field(0, ge=0, le=50_000_000)
    note: str = Field("", max_length=400)


class PaymentRequestReview(BaseModel):
    decision: Literal["approved", "rejected"]
    period_days: int = Field(30, ge=1, le=365)
    note: str = Field("", max_length=400)


@app.post("/api/v1/billing/payment-requests", dependencies=[Depends(_chat_rate_limit_dependency)])
def create_payment_request_endpoint(
    payload: PaymentRequestCreate,
    owner_id: str = Depends(_require_project_owner),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    try:
        return sub_store.create_payment_request(
            owner_id,
            provider=payload.provider,
            plan_id=payload.plan_id,
            phone_or_ref=payload.phone_or_ref,
            transaction_ref=payload.transaction_ref,
            amount_xaf=payload.amount_xaf,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/billing/payment-requests/me", dependencies=[Depends(_data_rate_limit_dependency)])
def list_my_payment_requests_endpoint(
    owner_id: str = Depends(_require_project_owner),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    items = sub_store.list_payment_requests(user_id=owner_id, limit=50)
    return {"count": len(items), "requests": items}


@app.get("/api/v1/admin/billing/payment-requests", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_payment_requests_endpoint(
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(50, ge=1, le=200),
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    items = sub_store.list_payment_requests(status=status, limit=limit)
    return {"count": len(items), "requests": items}


@app.post("/api/v1/admin/billing/payment-requests/{request_id}/review", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_review_payment_request_endpoint(
    request_id: str,
    payload: PaymentRequestReview,
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    actor, _ = _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    try:
        return sub_store.review_payment_request(
            request_id,
            actor=actor,
            decision=payload.decision,
            period_days=payload.period_days,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class AdminCreateProKeyRequest(BaseModel):
    plan_id: Literal["trial", "premium"] = "premium"
    duration_days: int = Field(30, ge=1, le=365)
    note: str = Field("", max_length=240)


class RedeemProKeyRequest(BaseModel):
    activation_key: str = Field(..., min_length=8, max_length=64)


@app.post("/api/v1/admin/billing/keys", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_create_pro_key_endpoint(
    payload: AdminCreateProKeyRequest,
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Génère une clé d'activation PRO unique (1 clé = 1 compte connecté, affichée une seule fois)."""
    actor, _ = _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    try:
        return sub_store.create_activation_key(
            actor=actor,
            plan_id=payload.plan_id,
            duration_days=payload.duration_days,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/admin/billing/keys", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_pro_keys_endpoint(
    status: Optional[str] = Query(None, pattern="^(unused|redeemed|revoked)$"),
    limit: int = Query(100, ge=1, le=200),
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    items = sub_store.list_activation_keys(status=status, limit=limit)
    return {"count": len(items), "keys": items}


@app.post("/api/v1/admin/billing/keys/{key_id}/revoke", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_revoke_pro_key_endpoint(
    key_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    actor, _ = _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    try:
        return sub_store.revoke_activation_key(key_id, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/billing/redeem-key", dependencies=[Depends(_chat_rate_limit_dependency)])
def redeem_pro_key_endpoint(
    payload: RedeemProKeyRequest,
    authorization: Optional[str] = Header(default=None),
    auth_store: AuthStore = Depends(get_auth_store),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    """Active une clé PRO unique pour le compte connecté (Bearer obligatoire, usage unique atomique)."""
    sub_id, _ = _require_bearer_user_id(authorization, auth_store)
    user = auth_store.get_user(sub_id)
    if not user:
        raise HTTPException(status_code=401, detail="Compte introuvable.")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Compte suspendu par l'administrateur. Contactez le support.")
    owner_id = f"user:{user['user_id']}"
    _assert_not_suspended(owner_id, skip_auth_store_check=True)
    try:
        return sub_store.redeem_activation_key(owner_id, payload.activation_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/billing/me", dependencies=[Depends(_data_rate_limit_dependency)])
def get_my_billing_endpoint(
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    summary = sub_store.get_usage_summary(owner_id)
    sub = summary["subscription"]
    # Lecture seule (aucun effet de bord en base) : une clé partenaire ne réactive jamais un compte suspendu/résilié.
    if _premium_key_ok(x_premium_key) and sub.get("plan_id") == "free" and sub.get("status") == "active":
        prem = DEFAULT_PLANS["premium"]
        sub = {**sub, "effective_plan_id": "premium", "provider": "key", "limits": prem}
        quotas = {}
        for metric, q in summary.get("quotas", {}).items():
            lim_key = f"{metric}_limit"
            limit_val = int(prem.get(lim_key, q.get("limit", 0)))
            used_val = int(q.get("used", 0))
            quotas[metric] = {**q, "limit": limit_val, "remaining": max(0, limit_val - used_val)}
        return {**summary, "subscription": sub, "quotas": quotas, "is_pro": True}
    is_pro = sub.get("effective_plan_id") in ("trial", "premium")
    return {**summary, "is_pro": is_pro}


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
    actor, _ = _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
    return sub_store.admin_update_subscription(
        actor=actor,
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
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
):
    is_stripe = provider.strip().lower() == "stripe"
    if is_stripe:
        secret = (os.getenv("STRIPE_WEBHOOK_SECRET", "") or os.getenv("PAYMENT_WEBHOOK_SECRET", "")).strip()
        sig = stripe_signature or x_webhook_signature or ""
        adapter: Any = StripeWebhookAdapter()
    else:
        secret = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
        sig = x_webhook_signature or ""
        adapter = HmacJsonWebhookAdapter(provider_name=provider)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Webhook paiement non configuré (STRIPE_WEBHOOK_SECRET / PAYMENT_WEBHOOK_SECRET manquant).",
        )
    raw_body = await request.body()
    try:
        return sub_store.process_webhook_idempotent(adapter, raw_body, sig, secret)
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
    _require_admin_token(x_admin_token, "manage_subscriptions", detail="Jeton administrateur requis.")
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
    _require_admin_token(x_admin_token, "read_overview")
    return _AI_MONITOR.snapshot(_ML_CACHE, _RAG_CACHE)


class DocumentValidateRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=180)
    content_base64: str = Field(..., min_length=1)
    mime_type: Optional[str] = Field(None, max_length=100)
    project_id: Optional[str] = Field(None, max_length=80)
    chunk_offset: int = Field(0, ge=0, le=5000)


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


@app.post("/api/v1/documents/upload", dependencies=[Depends(_chat_rate_limit_dependency)])
def upload_user_document_endpoint(
    payload: DocumentValidateRequest,
    owner_id: str = Depends(_require_project_owner),
    x_premium_key: Optional[str] = Header(default=None),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    """Téléverse, valide, indexe via Jina Embeddings v3 (ou hybride local) et isole un document privé sous `owner_id`."""
    import base64

    verified_project_id = _assert_project_owned(owner_id, payload.project_id, project_store)

    sub = sub_store.get_subscription(owner_id)
    limits = sub["limits"]
    if _premium_key_ok(x_premium_key) and sub.get("plan_id") == "free" and sub.get("status") == "active":
        limits = DEFAULT_PLANS["premium"]
    max_mb = int(limits.get("max_file_mb", 2))
    max_bytes = max_mb * 1024 * 1024
    max_docs = 50 if _has_pro_access(owner_id, x_premium_key, sub_store) else 5

    try:
        raw_bytes = base64.b64decode(payload.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Encodage base64 invalide.") from exc

    # Pré-validation gratuite (nom, type, taille, contenu) : un fichier refusé ne doit pas consommer le quota RAG.
    try:
        validate_uploaded_document(
            payload.filename, raw_bytes, mime_type=payload.mime_type, max_bytes=max_bytes
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _consume_user_quota(owner_id, x_premium_key, "daily_rag", sub_store, "Quota journalier d'indexation documentaire RAG atteint.")

    try:
        return doc_store.ingest_document(
            owner_id,
            filename=payload.filename,
            content_bytes=raw_bytes,
            mime_type=payload.mime_type,
            project_id=verified_project_id,
            max_bytes=max_bytes,
            max_docs=max_docs,
            chunk_offset=payload.chunk_offset,
        )
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/documents", dependencies=[Depends(_data_rate_limit_dependency)])
def list_user_documents_endpoint(
    project_id: Optional[str] = Query(None, max_length=80),
    owner_id: str = Depends(_require_project_owner),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    verified_project_id = _assert_project_owned(owner_id, project_id, project_store)
    docs = doc_store.list_documents(owner_id, project_id=verified_project_id)
    return {"count": len(docs), "documents": docs}


@app.delete("/api/v1/documents/{doc_id}", dependencies=[Depends(_data_rate_limit_dependency)])
def delete_user_document_endpoint(
    doc_id: str,
    owner_id: str = Depends(_require_project_owner),
    doc_store: UserDocumentStore = Depends(get_user_document_store),
):
    deleted = doc_store.delete_document(owner_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    return {"deleted": True, "doc_id": doc_id}


# ---------------------------------------------------------------------------
# Phase 14 — Centralized Admin Dashboard, RBAC & System Operations
# ---------------------------------------------------------------------------
_ADMIN_SERVICE: Optional[AdminService] = None


def get_admin_service() -> AdminService:
    global _ADMIN_SERVICE
    if _ADMIN_SERVICE is None:
        _ADMIN_SERVICE = AdminService()
    return _ADMIN_SERVICE


_ADMIN_TOKEN_MIN_LEN = 16
_ADMIN_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,60}$")


def _admin_credentials() -> list[tuple[str, str, str]]:
    """Identifiants admin valides : (acteur, rôle, jeton). ADMIN_TOKENS puis ADMIN_TOKEN (super_admin, hérité)."""
    creds: list[tuple[str, str, str]] = []
    for raw in re.split(r"[;\n]", settings.admin_tokens or ""):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(":", 2)
        if len(parts) != 3:
            continue
        actor, role, token = (x.strip() for x in parts)
        if role in ROLE_PERMISSIONS and _ADMIN_ACTOR_RE.match(actor) and len(token) >= _ADMIN_TOKEN_MIN_LEN:
            creds.append((actor, role, token))
    if settings.admin_token:
        creds.append(("root_admin", "super_admin", settings.admin_token))
    return creds


def _resolve_admin(token: Optional[str]) -> Optional[tuple[str, str]]:
    """Retrouve (acteur, rôle) à partir du jeton, en temps constant (tous les jetons sont comparés)."""
    if not isinstance(token, str) or not token:
        return None
    found: Optional[tuple[str, str]] = None
    cand = token.encode()
    for actor, role, secret in _admin_credentials():
        if hmac.compare_digest(cand, secret.encode()) and found is None:
            found = (actor, role)
    if found is None:
        return None
    # Les rôles attribués en console sont effectifs : ils peuvent restreindre ou révoquer un jeton.
    try:
        eff = get_admin_service().effective_role(found[0], found[1])
    except Exception as exc:  # base admin indisponible : on garde le rôle du jeton
        logger.warning("Rôle effectif admin indisponible (%s) : rôle du jeton conservé.", exc)
        return found
    if eff == "user":
        raise HTTPException(status_code=403, detail="Accès administrateur révoqué pour ce jeton.")
    return (found[0], eff)


def _require_admin_token(token: Optional[str], permission: str, detail: str = "Jeton administrateur invalide.") -> tuple[str, str]:
    if not _admin_credentials():
        raise HTTPException(status_code=503, detail="Administration désactivée : ADMIN_TOKEN / ADMIN_TOKENS non configuré.")
    ident = _resolve_admin(token)
    if ident is None:
        raise HTTPException(status_code=403, detail=detail)
    if permission not in ROLE_PERMISSIONS.get(ident[1], set()):
        raise HTTPException(status_code=403, detail=f"Rôle '{ident[1]}' non autorisé pour '{permission}'.")
    return ident



def _require_admin_actor(
    x_admin_token: Optional[str] = Header(default=None),
) -> tuple[str, str]:
    # Acteur et rôle viennent du jeton ; X-Admin-Actor / X-Admin-Role sont ignorés (anti-falsification).
    if not _admin_credentials():
        raise HTTPException(status_code=503, detail="Administration désactivée : ADMIN_TOKEN / ADMIN_TOKENS non configuré.")
    ident = _resolve_admin(x_admin_token)
    if ident is None:
        raise HTTPException(status_code=403, detail="Jeton administrateur invalide.")
    return ident


@app.get("/api/v1/admin/me", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_me_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
):
    actor, role = actor_info
    return {
        "actor": actor,
        "role": role,
        "permissions": sorted(ROLE_PERMISSIONS.get(role, set())),
    }


def _probe_providers_health(state: dict, *, live_probe: bool = False) -> dict:
    """Rapporte l'état réel des services externes et moteurs internes avec catégories explicites :
    `Connected`, `Configured`, `Degraded`, `Unavailable`, `Not configured`.
    Ne retourne jamais de clés API ni de corps d'erreur sensibles.
    """
    groq_key = (settings.llm_api_key or "").strip()
    jina_key = (settings.embed_api_key or os.getenv("EMBED_API_KEY", "")).strip()
    pg_url = (os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or "").strip()

    groq_status = "Configured" if groq_key else "Not configured"
    jina_status = "Configured" if jina_key else "Not configured"
    supabase_status = "Configured" if pg_url else "Not configured"

    if live_probe:
        if pg_url:
            try:
                from src import db as _db
                with _db.pg_connect(pg_url, _db.DEFAULT_SCHEMA) as conn:
                    conn.execute("SELECT 1").fetchone()
                supabase_status = "Connected"
            except Exception as exc:
                logger.warning("Admin probe: Supabase PG unavailable (%s)", type(exc).__name__)
                supabase_status = "Unavailable"
        if groq_key:
            try:
                models_url = f"{settings.llm_base_url.rstrip('/')}/models"
                r = requests.get(
                    models_url,
                    headers={"Authorization": f"Bearer {groq_key}"},
                    timeout=2.5,
                )
                groq_status = (
                    "Connected"
                    if r.status_code == 200
                    else (
                        "Degraded"
                        if r.status_code == 429
                        else ("Error" if 400 <= r.status_code < 500 else "Unavailable")
                    )
                )
            except Exception as exc:
                logger.warning("Admin probe: Groq LLM unreachable (%s)", type(exc).__name__)
                groq_status = "Unavailable"
        if jina_key:
            try:
                r = requests.post(
                    (settings.embed_base_url or "https://api.jina.ai/v1/embeddings").strip(),
                    headers={"Authorization": f"Bearer {jina_key}", "Content-Type": "application/json"},
                    json={"model": (settings.embed_model or "jina-embeddings-v3").strip(), "input": ["ping"]},
                    timeout=2.5,
                )
                if r.status_code != 200:
                    logger.warning("Admin probe: Jina Embeddings returned HTTP %s", r.status_code)
                jina_status = (
                    "Connected"
                    if r.status_code == 200
                    else (
                        "Degraded"
                        if r.status_code == 429
                        else ("Error" if 400 <= r.status_code < 500 else "Unavailable")
                    )
                )
            except Exception as exc:
                logger.warning("Admin probe: Jina Embeddings unreachable (%s)", type(exc).__name__)
                jina_status = "Unavailable"

    fc_df = state.get("forecast_df")
    ml_status = "Connected" if (fc_df is not None and not getattr(fc_df, "empty", True)) else "Unavailable"
    rag_status = "Connected" if "agent" in state else "Degraded"
    doc_indexing_status = "Connected" if jina_status in ("Connected", "Configured") else "Degraded"
    bg_status = "Connected" if _REPORT_JOB_MANAGER is not None else "Unavailable"

    def _norm_enum(s: str) -> str:
        return s.strip().upper().replace(" ", "_")

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "checked_at_utc": checked_at,
        "live_probe_executed": bool(live_probe),
        "supabase_status": supabase_status,
        "groq_status": groq_status,
        "jina_status": jina_status,
        "ml_engine_status": ml_status,
        "rag_engine_status": rag_status,
        "document_indexing_status": doc_indexing_status,
        "background_jobs_status": bg_status,
        "services": {
            "supabase": _norm_enum(supabase_status),
            "groq": _norm_enum(groq_status),
            "jina": _norm_enum(jina_status),
            "ml_engine": _norm_enum(ml_status),
            "rag_engine": _norm_enum(rag_status),
            "document_indexing": _norm_enum(doc_indexing_status),
            "background_jobs": _norm_enum(bg_status),
        },
        "groq_llm_configured": bool(groq_key),
        "groq_model": settings.llm_chat_model,
        "jina_embed_configured": bool(jina_key),
        "jina_model": settings.embed_model,
        "supabase_pg_active": bool(pg_url),
        "require_signed_user_auth": os.getenv("REQUIRE_SIGNED_USER_AUTH", "0").strip().lower() in ("1", "true", "yes"),
    }


def _build_operational_warnings(
    providers_health: dict,
    api_metrics: dict,
    freshness: dict,
) -> list[dict[str, str]]:
    """Computes lightweight, zero-cost operational warnings from real counters and probe results."""
    warnings: list[dict[str, str]] = []
    services = providers_health.get("services") or {}
    for svc_name, status in services.items():
        if status in ("UNAVAILABLE", "ERROR"):
            warnings.append({"severity": "high", "code": f"{svc_name.upper()}_UNAVAILABLE", "message": f"Service {svc_name} indisponible ({status})."})
        elif status == "DEGRADED":
            warnings.append({"severity": "medium", "code": f"{svc_name.upper()}_DEGRADED", "message": f"Service {svc_name} dégradé ({status})."})

    total_req = max(1, int(api_metrics.get("total_requests", 0)))
    err_5xx = int(api_metrics.get("error_5xx", 0))
    if total_req >= 10 and (err_5xx / total_req) > 0.05:
        warnings.append({
            "severity": "high",
            "code": "HIGH_5XX_RATE",
            "message": f"Taux d'erreurs serveur 5xx élevé ({err_5xx}/{total_req}).",
        })
    if float(api_metrics.get("avg_latency_ms", 0.0)) > 3000.0:
        warnings.append({
            "severity": "medium",
            "code": "HIGH_LATENCY",
            "message": f"Latence moyenne API élevée ({api_metrics.get('avg_latency_ms')} ms).",
        })
    if freshness.get("freshness_status") in ("stale", "unavailable"):
        warnings.append({
            "severity": "medium",
            "code": "STALE_MARKET_DATA",
            "message": f"Données marché non fraîches (statut : {freshness.get('freshness_status')}).",
        })
    if os.getenv("RENDER") and not providers_health.get("require_signed_user_auth"):
        warnings.append({
            "severity": "high",
            "code": "UNSIGNED_AUTH_ENABLED",
            "message": "REQUIRE_SIGNED_USER_AUTH=1 n'est pas activé sur Render.",
        })
    return warnings


_APP_STARTED_AT_UTC = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_dir_size_bytes(path) -> int:
    from pathlib import Path as _Path

    root = _Path(path)
    if not root.is_dir():
        return 0
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        return total
    return total


@app.get("/api/v1/admin/overview", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_overview_endpoint(
    live_probe: bool = Query(False),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    state: dict = Depends(get_state),
    admin: AdminService = Depends(get_admin_service),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    auth_store: AuthStore = Depends(get_auth_store),
    registry: LicensingRegistry = Depends(get_licensing_registry),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    with _METRICS_LOCK:
        api_metrics = dict(_METRICS)
        api_metrics["error_categories"] = dict(_METRICS.get("error_categories", {}))
        api_metrics["recent_errors"] = list(_METRICS.get("recent_errors", []))
    api_metrics["avg_latency_ms"] = round(api_metrics.pop("total_latency_ms", 0.0) / max(1, api_metrics.get("total_requests", 1)), 2)

    users = admin.list_users(sub_store, auth_store=auth_store, limit=500, offset=0)
    plan_counts = {"free": 0, "trial": 0, "premium": 0}
    for u in users:
        p = u["plan_id"]
        plan_counts[p] = plan_counts.get(p, 0) + 1

    fc_fresh = (state.get("freshness") or {}).get("forecasts") or {}
    providers_health = _probe_providers_health(state, live_probe=live_probe)
    freshness_summary = {
        "latest_observation_month": fc_fresh.get("latest_observation_month"),
        "data_age_months": fc_fresh.get("data_age_months"),
        "freshness_status": fc_fresh.get("freshness_status", "unavailable"),
    }
    svc_map = providers_health.get("services") or {}
    ai_infrastructure = {
        "ml_engine": svc_map.get("ml_engine", "UNAVAILABLE"),
        "rag_engine": svc_map.get("rag_engine", "DEGRADED"),
        "llm_provider": svc_map.get("groq", "NOT_CONFIGURED"),
        "embedding_provider": svc_map.get("jina", "NOT_CONFIGURED"),
        "analytics_engine": "CONNECTED" if "forecast_df" in state else "UNAVAILABLE",
        "tool_orchestrator": "CONNECTED" if "agent" in state else "DEGRADED",
        "background_jobs": svc_map.get("background_jobs", "UNAVAILABLE"),
        "model_registry": "CONNECTED" if _MODEL_REGISTRY is not None else "UNAVAILABLE",
    }
    from pathlib import Path as _Path

    data_root = _Path("data")
    storage_summary = {
        "data_dir_bytes": _safe_dir_size_bytes(data_root),
        "models_dir_bytes": _safe_dir_size_bytes(data_root / "models"),
        "persistence_backend": "supabase_postgresql" if providers_health.get("supabase_pg_active") else "local_sqlite",
    }
    deployment_info = {
        "environment": os.getenv("FREEDATA_ENV") or ("production" if os.getenv("RENDER") else "development"),
        "version": app.version,
        "git_commit": (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GITHUB_SHA") or "")[:12] or None,
        "started_at_utc": _APP_STARTED_AT_UTC,
    }
    return {
        "api_health": {"status": "ok" if "agent" in state else "degraded", "version": app.version, "engine_mode": state.get("mode", "unknown")},
        "deployment_info": deployment_info,
        "api_metrics": api_metrics,
        "ai_infra": _AI_MONITOR.snapshot(_ML_CACHE, _RAG_CACHE),
        "ai_infrastructure": ai_infrastructure,
        "providers_health": providers_health,
        "background_jobs_summary": _REPORT_JOB_MANAGER.summary() if _REPORT_JOB_MANAGER is not None else {"total_tracked_jobs": 0},
        "storage_summary": storage_summary,
        "operational_warnings": _build_operational_warnings(providers_health, api_metrics, freshness_summary),
        "data_freshness": freshness_summary,
        "domains_summary": DomainRegistry.admin_summary(),
        "ml_registry_summary": _MODEL_REGISTRY.summary(),
        "model_flags": admin.list_model_flags(),
        "ml_models": _MODEL_REGISTRY.list_models(),
        "users_summary": {"total_known_users": len(users), "by_plan": plan_counts},
        "datasets": registry.list_entries(),
        "recent_audit_logs": admin.list_audit_logs(limit=20),
    }


@app.get("/api/v1/admin/users", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_list_users_endpoint(
    q: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    status: Optional[Literal["active", "suspended"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    sub_store: SubscriptionStore = Depends(get_subscription_store),
    auth_store: AuthStore = Depends(get_auth_store),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    query_str = (q if q is not None else search)
    return {"users": admin.list_users(sub_store, auth_store=auth_store, q=query_str, status=status, limit=limit, offset=offset)}


class AdminUserStatusRequest(BaseModel):
    status: Literal["active", "suspended"]
    reason: str = Field("", max_length=300)


@app.post("/api/v1/admin/users/{target_user_id}/status", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_set_user_status_endpoint(
    target_user_id: str,
    payload: AdminUserStatusRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
    auth_store: AuthStore = Depends(get_auth_store),
):
    actor, role = actor_info
    try:
        res = admin.set_user_status(actor=actor, actor_role=role, target_user_id=target_user_id, status=payload.status, reason=payload.reason)
        if isinstance(auth_store, AuthStore):
            auth_store.set_account_status(target_user_id, payload.status)
        return res
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


class AdminDomainStatusRequest(BaseModel):
    active: bool
    reason: str = Field("", max_length=300)


class AdminMLModelStatusRequest(BaseModel):
    version: int = Field(1, ge=1)
    lifecycle_status: Literal[
        "REGISTERED",
        "TRAINING",
        "TRAINED",
        "EVALUATION",
        "APPROVED",
        "DEPLOYED",
        "DEPRECATED",
        "ARCHIVED",
        "FAILED",
    ]
    set_active: bool = False
    enabled: Optional[bool] = None
    reason: str = Field("", max_length=300)
    # Contourne le garde-fou de mise en production (journalisé) : exige une justification d'au moins 20 caractères.
    force: bool = False


@app.get("/api/v1/admin/ai/domains", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_domains_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DomainRegistry.admin_summary()


@app.post("/api/v1/admin/ai/domains/{domain_id}/status", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_set_domain_status_endpoint(
    domain_id: str,
    payload: AdminDomainStatusRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_models")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        res = DomainRegistry.set_domain_active(domain_id, payload.active)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    admin.log_action(
        actor=actor,
        actor_role=role,
        action="set_domain_active",
        resource_type="ai_domain",
        resource_id=domain_id,
        details=f"active={payload.active} reason={payload.reason}",
    )
    return res


@app.get("/api/v1/admin/ai/models", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_models_endpoint(
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "summary": _MODEL_REGISTRY.summary(),
        "models": _MODEL_REGISTRY.list_models(),
    }


@app.post("/api/v1/admin/ai/models/{model_id}/status", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_transition_model_endpoint(
    model_id: str,
    payload: AdminMLModelStatusRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_models")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    forced = False
    if payload.lifecycle_status == "DEPLOYED" and payload.set_active:
        try:
            blockers = promotion_blockers(_MODEL_REGISTRY, model_id, payload.version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if blockers:
            if not (payload.force and len(payload.reason.strip()) >= 20):
                raise HTTPException(
                    status_code=409,
                    detail="Mise en production refusée : " + " ".join(blockers)
                    + " (force=true avec une justification de 20 caractères minimum pour contourner, journalisé.)",
                )
            forced = True
    try:
        updated = _MODEL_REGISTRY.transition_status(
            model_id,
            payload.version,
            payload.lifecycle_status,
            set_active=payload.set_active,
            enabled=payload.enabled,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    admin.log_action(
        actor=actor,
        actor_role=role,
        action="transition_ml_model_status",
        resource_type="ml_model",
        resource_id=f"{model_id}:v{payload.version}",
        details=f"status={payload.lifecycle_status} active={payload.set_active} enabled={payload.enabled} forced_guard={forced} reason={payload.reason}",
    )
    return updated


class AdminMLRollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1)
    reason: str = Field("", max_length=300)


@app.post("/api/v1/admin/ai/models/{model_id}/rollback", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_rollback_model_endpoint(
    model_id: str,
    payload: AdminMLRollbackRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_models")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        rolled = _MODEL_REGISTRY.rollback_model(model_id, payload.target_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    admin.log_action(
        actor=actor,
        actor_role=role,
        action="rollback_ml_model",
        resource_type="ml_model",
        resource_id=f"{model_id}:v{payload.target_version}",
        details=f"rollback_to=v{payload.target_version} reason={payload.reason}",
    )
    return rolled


_BENCHMARK_JOB_MANAGER = BenchmarkJobManager(max_concurrent=1, timeout_seconds=60.0)


class AdminBenchmarkRequest(BaseModel):
    domain: str = Field(..., min_length=2, max_length=64)
    task_type: Literal["forecasting", "regression", "classification", "clustering"]
    feature_columns: list[str] = Field(default_factory=list, max_length=64)
    target_column: Optional[str] = Field(None, max_length=120)
    time_column: Optional[str] = Field(None, max_length=120)
    dataset_name: str = Field("benchmark.csv", min_length=1, max_length=160)
    dataset_scope: str = Field("platform_public", max_length=40)
    dataset_provenance: dict = Field(default_factory=dict)
    csv_base64: Optional[str] = None
    csv_text: Optional[str] = None


@app.post("/api/v1/admin/ai/benchmark", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_launch_benchmark_endpoint(
    payload: AdminBenchmarkRequest,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    actor, role = actor_info
    try:
        admin.check_permission(role, "manage_models")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # Decode CSV bytes safely (never log raw CSV contents)
    if payload.csv_base64:
        import base64 as _b64

        try:
            csv_bytes = _b64.b64decode(payload.csv_base64.encode("ascii"), validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Encodage base64 CSV invalide.") from exc
    elif payload.csv_text:
        csv_bytes = payload.csv_text.encode("utf-8")
    else:
        raise HTTPException(status_code=400, detail="Fournissez 'csv_base64' ou 'csv_text'.")

    if len(csv_bytes) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="Fichier CSV trop volumineux (limite maximale : 5 Mo).")

    # Provenance obligatoire : sans source ni licence, un jeu de données ne doit pas entraîner de modèle.
    prov_in = dict(payload.dataset_provenance or {})
    if len(str(prov_in.get("source") or "").strip()) < 3 or len(str(prov_in.get("license") or "").strip()) < 2:
        raise HTTPException(
            status_code=422,
            detail="Provenance obligatoire : renseignez dataset_provenance.source (origine) et dataset_provenance.license (licence).",
        )
    prov_in["submitted_by"] = actor

    # Sanitize dataset_name (prevent path traversal)
    from pathlib import Path as _Path
    safe_name = _Path(payload.dataset_name).name or "benchmark.csv"
    spec = DatasetSpec(
        domain=payload.domain.strip(),
        task_type=payload.task_type,
        feature_columns=[c.strip() for c in payload.feature_columns if c.strip()],
        target_column=payload.target_column.strip() if payload.target_column else None,
        time_column=payload.time_column.strip() if payload.time_column else None,
        dataset_name=safe_name,
        dataset_provenance=prov_in,
        dataset_scope=payload.dataset_scope.strip(),
    )
    try:
        job = _BENCHMARK_JOB_MANAGER.submit(
            actor=actor,
            csv_bytes=csv_bytes,
            spec=spec,
            registry=_MODEL_REGISTRY,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    admin.log_action(
        actor=actor,
        actor_role=role,
        action="launch_ml_benchmark",
        resource_type="ml_benchmark",
        resource_id=job["job_id"],
        details=f"domain={spec.domain} task={spec.task_type} dataset={safe_name} hash={job['dataset_hash'][:12]}",
    )
    return job


@app.get("/api/v1/admin/ai/benchmark/{job_id}", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_get_benchmark_endpoint(
    job_id: str,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        return _BENCHMARK_JOB_MANAGER.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/admin/ai/benchmarks", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_list_benchmarks_endpoint(
    limit: int = Query(20, ge=1, le=50),
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"jobs": _BENCHMARK_JOB_MANAGER.list_jobs(limit=limit)}


@app.get(
    "/api/v1/admin/ai/models/{model_id}/versions/{version}/promotion-check",
    dependencies=[Depends(_admin_rate_limit_dependency)],
)
def admin_ai_promotion_check_endpoint(
    model_id: str,
    version: int,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        blockers = promotion_blockers(_MODEL_REGISTRY, model_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"model_id": model_id, "version": version, "eligible": not blockers, "blockers": blockers}


@app.get("/api/v1/admin/ai/models/{model_id}/compare", dependencies=[Depends(_admin_rate_limit_dependency)])
def admin_ai_compare_model_versions_endpoint(
    model_id: str,
    actor_info: tuple[str, str] = Depends(_require_admin_actor),
    admin: AdminService = Depends(get_admin_service),
):
    _, role = actor_info
    try:
        admin.check_permission(role, "read_overview")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        return {"model_id": model_id, "versions": _MODEL_REGISTRY.compare_versions(model_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
