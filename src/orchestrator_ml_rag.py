"""ML + RAG + Analytical Orchestration Layer for FreeData.AI."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import pandas as pd

from src.analytics import AnalyticsService
from src.ml_engine import KMeansMarketClusterer, evaluate_ridge_chronological
from src.rag_engine import HybridRAGEngine


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


class IntelligenceOrchestrator:
    """Routes user questions to the appropriate analytical, ML, or RAG tool with full provenance."""

    def __init__(
        self,
        analytics: Optional[AnalyticsService] = None,
        rag: Optional[HybridRAGEngine] = None,
    ) -> None:
        self.analytics = analytics or AnalyticsService()
        self.rag = rag or HybridRAGEngine()

    @staticmethod
    def select_tool(query: str) -> str:
        q = _norm(query)
        if any(k in q for k in ("anomal", "suspect", "fige", "saut")):
            return "ml_anomaly"
        if any(k in q for k in ("cluster", "segment", "regroup")):
            return "ml_cluster"
        if any(k in q for k in ("prevision", "predi", "forecast", "modele", "ridge", "backtest")):
            return "ml_forecast"
        if any(k in q for k in ("rapport", "methodologie", "gouvernance", "licence", "source", "document")):
            return "rag_hybrid"
        return "analytics_query"

    def handle(
        self,
        query: str,
        *,
        forecast_df: pd.DataFrame,
        hist_df: pd.DataFrame,
        passport_df: pd.DataFrame,
        anomalies_df: pd.DataFrame,
        commodity: Optional[str] = None,
        province: Optional[str] = None,
    ) -> dict[str, Any]:
        tool = self.select_tool(query)
        prof = self.analytics.get_profile(forecast_df, hist_df)
        period = prof.get("latest_observed_month") or "période suivie"
        sources = prof.get("sources") or ["FreeData.AI"]

        if tool == "ml_anomaly":
            res = self.analytics.get_anomalies(anomalies_df, province=province, commodity=commodity)
            return {
                "tool_used": "ml_anomaly",
                "period": period,
                "geographic_scope": province or "provinces suivies",
                "units": "XAF/kg",
                "methodology": "Détection robuste médiane/MAD et écart aux pairs (sans suppression automatique).",
                "limitations": ["Les anomalies sont des signaux à vérifier, pas des verdicts d'erreur."],
                "sources": sources,
                "result": res,
            }

        if tool == "ml_cluster":
            if passport_df is None or passport_df.empty or not {"cv_pct", "credit_score"}.issubset(passport_df.columns):
                return {
                    "tool_used": "ml_cluster",
                    "period": period,
                    "geographic_scope": "provinces suivies",
                    "units": "score / %",
                    "methodology": "K-Means (k=3)",
                    "limitations": ["Données Credit Passport insuffisantes pour le clustering."],
                    "sources": sources,
                    "result": {"status": "insufficient_data"},
                }
            res = KMeansMarketClusterer(k=min(3, len(passport_df))).fit_predict(passport_df, ["cv_pct", "credit_score"])
            return {
                "tool_used": "ml_cluster",
                "period": period,
                "geographic_scope": "provinces suivies",
                "units": "score / CV %",
                "methodology": "Segmentation K-Means standardisée sur volatilité (CV %) et score de stabilité.",
                "limitations": ["La segmentation reflète uniquement les séries historiques disponibles."],
                "sources": sources,
                "result": res,
            }

        if tool == "ml_forecast":
            comm = commodity or "Millet"
            prov = province or "Lac"
            bench = self.analytics.get_forecast_benchmark(hist_df, commodity=comm, province=prov)
            sub = hist_df[
                (hist_df.get("commodity_std", pd.Series(dtype=str)).astype(str).str.lower() == comm.lower())
                & (hist_df.get("province", pd.Series(dtype=str)).astype(str).str.lower() == prov.lower())
            ] if (hist_df is not None and not hist_df.empty) else pd.DataFrame()
            ridge_res = {"status": "insufficient_history"}
            price_col = "price" if (not sub.empty and "price" in sub.columns) else ("value" if (not sub.empty and "value" in sub.columns) else None)
            if price_col is not None:
                prices = pd.to_numeric(sub[price_col], errors="coerce").dropna().to_numpy(dtype=float)
                ridge_res = evaluate_ridge_chronological(prices)
                ridge_res.pop("model", None)
            return {
                "tool_used": "ml_forecast",
                "period": period,
                "geographic_scope": f"{prov} ({comm})",
                "units": "XAF/kg",
                "methodology": "Backtest chronologique (Naïve, Moyenne mobile 3m, Lissage exponentiel, Ridge L2).",
                "limitations": ["Aucune prévision publiée si historique < 6 mois (8 mois pour Ridge)."],
                "sources": sources,
                "result": {"statistical_benchmark": bench, "ridge_regression": ridge_res},
            }

        if tool == "rag_hybrid":
            hits = self.rag.search(query, top_k=4, filters={"province": province, "commodity": commodity} if (province or commodity) else None)
            return {
                "tool_used": "rag_hybrid",
                "period": "corpus documentaire indexé",
                "geographic_scope": province or "Tchad / corpus",
                "units": "score hybride BM25+cosinus",
                "methodology": "Réécriture de requête + BM25 + similarité cosinus hachée + reranking.",
                "limitations": ["Les extraits RAG ne sont pas automatiquement des faits chiffrés vérifiés."],
                "sources": [h["source"] for h in hits] or sources,
                "result": {"hits": hits},
            }

        # Default: analytics_query
        if any(k in _norm(query) for k in ("12 mois", "evolu", "tendance")):
            res = self.analytics.get_trends(hist_df, commodity=commodity, province=province)
        elif any(k in _norm(query) for k in ("volatil", "resume", "stat")):
            res = self.analytics.get_summary(forecast_df, passport_df, commodity=commodity, province=province)
        else:
            res = self.analytics.get_regional_comparison(forecast_df, commodity=commodity)
        return {
            "tool_used": "analytics_query",
            "period": period,
            "geographic_scope": province or "provinces suivies",
            "units": "XAF/kg",
            "methodology": "Agrégation statistique déterministe sur les données de marché vérifiées.",
            "limitations": ["Portée limitée aux marchés suivis ; ne constitue pas un indice national."],
            "sources": sources,
            "result": res,
        }

