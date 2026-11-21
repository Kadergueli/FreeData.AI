"""Modular Multi-Domain Architecture (Chad Data Domains) and Unified Tool Routing for FreeData.AI.

Single source of truth shared by ExploreScreen (/api/v1/metadata), ChatScreen, SettingsScreen,
Admin AI Control Center, and the ML Benchmark Studio.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Optional


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


@dataclass(frozen=True)
class DomainModule:
    domain_id: str
    label_fr: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    knowledge_sources: tuple[str, ...]
    supported_workflows: tuple[str, ...]
    output_formats: tuple[str, ...]
    data_status: str = "in_preparation"  # "operational" | "in_preparation"
    required_tier: str = "free"
    ml_models: tuple[str, ...] = ()
    rag_collections: tuple[str, ...] = ()
    analytical_operations: tuple[str, ...] = ()
    execution_pipeline: str = "rag_llm"  # "chad_agent" | "ml_orchestrator" | "rag_llm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "slug": self.domain_id,
            "label": self.label_fr,
            "status": self.data_status,
            "description": self.description,
        }


class DomainRegistry:
    """Extensible registry of Chad data domains sharing FreeData.AI's core LLM, RAG, ML, and Analytics engines."""

    _lock = threading.Lock()
    _active_overrides: dict[str, bool] = {}
    _usage_counts: dict[str, int] = {}

    MODULES: dict[str, DomainModule] = {
        "markets_and_prices": DomainModule(
            domain_id="markets_and_prices",
            label_fr="Marchés et prix des produits",
            description="Catalogue en cours d'exploitation : marchés, produits, provinces et sources de données au Tchad.",
            instructions=(
                "Ancre chaque analyse sur les données vérifiées des marchés du Tchad (XAF/kg, provinces, "
                "prévisions t+1, intervalle de confiance 80 %, alertes, saisonnalité et passeport crédit) sans inventer de chiffre."
            ),
            allowed_tools=("chad_market_agent", "business_engine", "analytics_query", "ml_forecast", "study_builder", "rag_hybrid"),
            knowledge_sources=("table_ml_forecasts", "table_ml_credit_passport", "table_ml_seasonality_studies", "DATA_CATALOG.md"),
            supported_workflows=("price_forecast", "arbitrage", "seasonality", "feasibility_study", "risk_scoring"),
            output_formats=("markdown", "pdf"),
            data_status="operational",
            ml_models=("ridge_price_regressor", "kmeans_market_clusterer", "risk_grade_classifier"),
            rag_collections=("chad_market_docs", "methodology_docs", "user_private_docs"),
            analytical_operations=("price_forecast", "spatial_arbitrage", "seasonality_profile", "anomaly_detection", "unit_economics"),
            execution_pipeline="chad_agent",
        ),
        "agriculture": DomainModule(
            domain_id="agriculture",
            label_fr="Agriculture",
            description="Pré-diagnostic agro-climatique de zone (12 pôles : humidité des sols, rayonnement) et indicateurs agricoles nationaux du Tchad.",
            instructions=(
                "Reste strictement dans le contexte agricole du Tchad. Appuie-toi UNIQUEMENT sur les indicateurs disponibles : humidité de la zone "
                "racinaire, humidité de surface et rayonnement photosynthétique (NASA POWER Agro, 12 pôles, mensuel 2020–2026), et les indicateurs "
                "nationaux World Bank (rendement et production céréalière, indices de production, terres, engrais). Cite toujours la source, la période "
                "et le niveau de confiance. Ces données sont régionales (pôle urbain/provincial), jamais une analyse de parcelle. "
                "Tu ne disposes d'AUCUNE donnée de température ni de précipitations : ne les évoque pas et n'invente aucune statistique de production."
            ),
            allowed_tools=("chad_market_agent", "analytics_query", "ml_forecast", "rag_hybrid"),
            knowledge_sources=("table_agro_indicators", "table_ml_forecasts", "table_ml_seasonality_studies", "METHODOLOGY.md"),
            supported_workflows=("zone_prediagnostic", "water_deficit_watch", "price_forecast", "seasonality", "crop_analysis"),
            output_formats=("markdown", "pdf"),
            data_status="operational",
            ml_models=("ridge_price_regressor",),
            rag_collections=("chad_market_docs", "user_private_docs"),
            analytical_operations=("zone_prediagnostic", "soil_wetness_anomaly", "seasonality_profile", "price_forecast"),
            execution_pipeline="chad_agent",
        ),
        "economy": DomainModule(
            domain_id="economy",
            label_fr="Économie",
            description="Indicateurs et tendances économiques du Tchad.",
            instructions=(
                "Analyse dans le contexte économique du Tchad (XAF/FCFA, inflation alimentaire, risque crédit, rentabilité). "
                "Ne cite aucun indicateur macroéconomique non sourcé ; appuie-toi sur les données disponibles et documents fournis."
            ),
            allowed_tools=("chad_market_agent", "business_engine", "analytics_query", "credit_passport", "rag_hybrid"),
            knowledge_sources=("table_ml_credit_passport", "table_ml_forecasts", "DATA_CATALOG.md"),
            supported_workflows=("risk_scoring", "cashflow_projection", "inflation_trends"),
            output_formats=("markdown", "pdf"),
            data_status="in_preparation",
            ml_models=("risk_grade_classifier",),
            rag_collections=("financial_methodology", "user_private_docs"),
            analytical_operations=("risk_grading", "break_even", "regional_comparison"),
            execution_pipeline="chad_agent",
        ),
        "health": DomainModule(
            domain_id="health",
            label_fr="Santé",
            description="Données de santé et de vulnérabilité au Tchad.",
            instructions=(
                "Reste dans le contexte sanitaire et de vulnérabilité du Tchad. Les données structurées Santé sont en préparation : "
                "analyse prioritairement les documents fournis par l'utilisateur et n'invente aucune statistique sanitaire."
            ),
            allowed_tools=("rag_hybrid", "llm_reasoning"),
            knowledge_sources=("DATA_CATALOG.md", "METHODOLOGY.md"),
            supported_workflows=("document_analysis", "vulnerability_synthesis"),
            output_formats=("markdown",),
            data_status="in_preparation",
            rag_collections=("platform_docs", "user_private_docs"),
            analytical_operations=("document_synthesis",),
            execution_pipeline="rag_llm",
        ),
        "population": DomainModule(
            domain_id="population",
            label_fr="Population",
            description="Données démographiques et sociales du Tchad.",
            instructions=(
                "Reste dans le contexte démographique et social du Tchad (provinces, démographie, accès aux services). "
                "Les données structurées Population sont en préparation : n'invente aucun chiffre démographique non sourcé."
            ),
            allowed_tools=("rag_hybrid", "llm_reasoning"),
            knowledge_sources=("DATA_CATALOG.md", "METHODOLOGY.md"),
            supported_workflows=("document_analysis", "demographic_synthesis"),
            output_formats=("markdown",),
            data_status="in_preparation",
            rag_collections=("platform_docs", "user_private_docs"),
            analytical_operations=("document_synthesis",),
            execution_pipeline="rag_llm",
        ),
        "environment": DomainModule(
            domain_id="environment",
            label_fr="Environnement",
            description="Conditions environnementales et risques au Tchad.",
            instructions=(
                "Reste dans le contexte environnemental et climatique du Tchad (sécheresse, pluviométrie, bassin du Lac Tchad, risques). "
                "Les données structurées Environnement sont en préparation : appuie-toi sur les documents fournis sans inventer de mesures."
            ),
            allowed_tools=("rag_hybrid", "llm_reasoning"),
            knowledge_sources=("DATA_CATALOG.md", "METHODOLOGY.md"),
            supported_workflows=("document_analysis", "environmental_risk_synthesis"),
            output_formats=("markdown",),
            data_status="in_preparation",
            rag_collections=("platform_docs", "user_private_docs"),
            analytical_operations=("document_synthesis",),
            execution_pipeline="rag_llm",
        ),
        "infrastructure": DomainModule(
            domain_id="infrastructure",
            label_fr="Infrastructures",
            description="Transport, routes et services essentiels au Tchad.",
            instructions=(
                "Reste dans le contexte des infrastructures au Tchad (routes, énergie, eau, télécoms, services essentiels). "
                "Les données structurées Infrastructures sont en préparation : analyse les documents fournis sans inventer de statistiques."
            ),
            allowed_tools=("rag_hybrid", "llm_reasoning"),
            knowledge_sources=("DATA_CATALOG.md", "METHODOLOGY.md"),
            supported_workflows=("document_analysis", "infrastructure_synthesis"),
            output_formats=("markdown",),
            data_status="in_preparation",
            rag_collections=("platform_docs", "user_private_docs"),
            analytical_operations=("document_synthesis",),
            execution_pipeline="rag_llm",
        ),
        "transport": DomainModule(
            domain_id="transport",
            label_fr="Transport",
            description="Flux et mobilité des biens et des personnes au Tchad.",
            instructions=(
                "Reste dans le contexte logistique et transport au Tchad (corridors, coûts de fret inter-provinces, mobilité). "
                "Les données structurées Transport sont en préparation : utilise les paramètres de transport fournis sans inventer de tarifs."
            ),
            allowed_tools=("rag_hybrid", "llm_reasoning"),
            knowledge_sources=("DATA_CATALOG.md", "METHODOLOGY.md"),
            supported_workflows=("document_analysis", "logistics_synthesis"),
            output_formats=("markdown",),
            data_status="in_preparation",
            rag_collections=("platform_docs", "user_private_docs"),
            analytical_operations=("document_synthesis",),
            execution_pipeline="rag_llm",
        ),
    }

    _DOMAIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("health", re.compile(r"\b(?:sante|hopital|maladie|epidemie|vaccination|nutrition|malnutrition|vulnerabilite\s+sanitaire|paludisme)\b")),
        ("population", re.compile(r"\b(?:population|demograph\w*|recensement|natalite|mortalite|menages|urbanisation|jeunesse)\b")),
        ("environment", re.compile(r"\b(?:environnement|climat|secheresse|inondation|pluviometrie|desertification|lac\s+tchad|ecologie)\b")),
        ("infrastructure", re.compile(r"\b(?:infrastructure|electricite|eau\s+potable|forage|reseau\s+routier|pont|energie|service\s+essentiel)\b")),
        ("transport", re.compile(r"\b(?:transport|fret|corridor|camion|mobilite|logistique|route\s+commerciale|acheminement)\b")),
        ("economy", re.compile(r"\b(?:economie|economique|inflation|pib|tresorerie|bfr|capex|point\s+mort|roi|rentabilite|credit\s+passport|financement|banque|microfinance)\b")),
        ("agriculture", re.compile(r"\b(?:agriculture|agricole|recolte|semence|rendement|campagne\s+agricole|cultivateur|eleveur|elevage|pluie)\b")),
        ("markets_and_prices", re.compile(r"\b(?:marche|prix|mil|sorgho|mais|riz|arachide|niebe|sesame|xaf|fcfa|prevision|arbitrage|negoce|tchad|n'djamena|ndjamena|moundou|sarh|abeche|salamat|batha|ouaddai|kanem)\b")),
    ]

    @classmethod
    def register_domain(
        cls,
        module: DomainModule,
        *,
        pattern: Optional[str] = None,
        active: bool = True,
    ) -> DomainModule:
        """Dynamically registers a new Chad data domain without modifying the Chat Engine."""
        with cls._lock:
            cls.MODULES[module.domain_id] = module
            cls._active_overrides[module.domain_id] = bool(active)
            if pattern:
                compiled = re.compile(pattern)
                cls._DOMAIN_PATTERNS = [
                    (d, p) for d, p in cls._DOMAIN_PATTERNS if d != module.domain_id
                ] + [(module.domain_id, compiled)]
        return module

    @classmethod
    def unregister_domain(cls, domain_id: str) -> None:
        with cls._lock:
            cls.MODULES.pop(domain_id, None)
            cls._active_overrides.pop(domain_id, None)
            cls._usage_counts.pop(domain_id, None)
            cls._DOMAIN_PATTERNS = [(d, p) for d, p in cls._DOMAIN_PATTERNS if d != domain_id]

    @classmethod
    def is_domain_active(cls, domain_id: str) -> bool:
        if domain_id not in cls.MODULES:
            return False
        with cls._lock:
            return cls._active_overrides.get(domain_id, True)

    @classmethod
    def set_domain_active(cls, domain_id: str, active: bool) -> dict[str, Any]:
        if domain_id not in cls.MODULES:
            raise KeyError(f"Domaine inconnu : {domain_id}")
        with cls._lock:
            cls._active_overrides[domain_id] = bool(active)
        return {"domain_id": domain_id, "active": bool(active)}

    @classmethod
    def record_usage(cls, domain_id: str) -> None:
        with cls._lock:
            cls._usage_counts[domain_id] = cls._usage_counts.get(domain_id, 0) + 1

    @classmethod
    def get_usage_counts(cls) -> dict[str, int]:
        with cls._lock:
            return dict(cls._usage_counts)

    @classmethod
    def list_domains(cls, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with cls._lock:
            for dom_id, m in cls.MODULES.items():
                is_active = cls._active_overrides.get(dom_id, True)
                if not include_inactive and not is_active:
                    continue
                d = m.to_dict()
                d["active"] = is_active
                d["usage_count"] = cls._usage_counts.get(dom_id, 0)
                out.append(d)
        return out

    @classmethod
    def metadata_domains(cls) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Returns (active_domain, all_domains) in the exact schema expected by /api/v1/metadata & ExploreScreen."""
        all_meta = [m.to_metadata_dict() for m in cls.MODULES.values()]
        active = next((d for d in all_meta if d["status"] == "operational"), all_meta[0])
        return active, all_meta

    @classmethod
    def admin_summary(cls) -> dict[str, Any]:
        all_domains = cls.list_domains(include_inactive=True)
        active_count = sum(1 for d in all_domains if d["active"])
        return {
            "total_domains": len(all_domains),
            "active_domains": active_count,
            "inactive_domains": len(all_domains) - active_count,
            "domains": all_domains,
        }

    @classmethod
    def get_domain(cls, domain_id: str) -> DomainModule:
        if domain_id not in cls.MODULES:
            raise KeyError(f"Domaine inconnu : {domain_id}")
        return cls.MODULES[domain_id]

    @classmethod
    def classify_domain(cls, query: str, explicit_domain: Optional[str] = None) -> DomainModule:
        if explicit_domain and explicit_domain in cls.MODULES:
            return cls.MODULES[explicit_domain]
        q_norm = _norm(query)
        for dom_id, pat in cls._DOMAIN_PATTERNS:
            if dom_id in cls.MODULES and cls.is_domain_active(dom_id) and pat.search(q_norm):
                return cls.MODULES[dom_id]
        return cls.MODULES["markets_and_prices"]
