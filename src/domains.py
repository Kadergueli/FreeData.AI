"""Modular Multi-Domain Architecture and Unified Tool Routing for FreeData.AI."""
from __future__ import annotations

import re
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
    instructions: str
    allowed_tools: tuple[str, ...]
    knowledge_sources: tuple[str, ...]
    supported_workflows: tuple[str, ...]
    output_formats: tuple[str, ...]
    required_tier: str = "free"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DomainRegistry:
    """Registry of specialized domains sharing FreeData.AI's core LLM, RAG, ML, and Analytics engines."""

    MODULES: dict[str, DomainModule] = {
        "general_ai": DomainModule(
            domain_id="general_ai",
            label_fr="IA Générale",
            instructions="Réponds clairement en français, de manière structurée et factuelle, sans inventer de statistiques.",
            allowed_tools=("llm_reasoning", "rag_hybrid"),
            knowledge_sources=("corpus_general", "documentation"),
            supported_workflows=("qa", "brainstorming", "summarization"),
            output_formats=("markdown",),
        ),
        "education": DomainModule(
            domain_id="education",
            label_fr="Éducation & Révisions",
            instructions="Explique pas à pas avec pédagogie, exemples concrets et exercices vérifiables.",
            allowed_tools=("llm_reasoning", "rag_hybrid"),
            knowledge_sources=("METHODOLOGY.md", "USER_GUIDE.md"),
            supported_workflows=("tutoring", "concept_explanation", "quiz"),
            output_formats=("markdown",),
        ),
        "academic_research": DomainModule(
            domain_id="academic_research",
            label_fr="Recherche Académique",
            instructions="Cite explicitement les sources, distingue faits observés et hypothèses, et précise les limites méthodologiques.",
            allowed_tools=("rag_hybrid", "analytics_query", "llm_reasoning"),
            knowledge_sources=("METHODOLOGY.md", "DATA_CATALOG.md", "DATA_GOVERNANCE_POLICY.md"),
            supported_workflows=("literature_synthesis", "methodology_review"),
            output_formats=("markdown", "pdf"),
        ),
        "business_entrepreneurship": DomainModule(
            domain_id="business_entrepreneurship",
            label_fr="Business & Entrepreneuriat",
            instructions="Utilise le moteur déterministe 80/8/12 (ou 88/0/12), ne force jamais la rentabilité et préserve StudyContext.",
            allowed_tools=("business_engine", "study_builder", "qa_validator", "rag_hybrid"),
            knowledge_sources=("table_ml_forecasts", "table_ml_credit_passport"),
            supported_workflows=("feasibility_study", "business_plan", "swot_pestel"),
            output_formats=("markdown", "pdf"),
        ),
        "finance": DomainModule(
            domain_id="finance",
            label_fr="Finance & Risque",
            instructions="Distingue bénéfice comptable et trésorerie, affiche point mort et sensibilité sans jamais simuler au-dessus du marché.",
            allowed_tools=("business_engine", "analytics_query", "credit_passport"),
            knowledge_sources=("table_ml_credit_passport", "METHODOLOGY.md"),
            supported_workflows=("break_even", "cashflow_projection", "risk_scoring"),
            output_formats=("markdown", "pdf"),
        ),
        "data_science": DomainModule(
            domain_id="data_science",
            label_fr="Data Science & ML",
            instructions="Privilégie les outils ML/statistiques réels (Ridge, K-Means, backtest chronologique) et rapporte MAE/RMSE/MAPE.",
            allowed_tools=("ml_forecast", "ml_cluster", "ml_anomaly", "analytics_query"),
            knowledge_sources=("table_ml_forecasts", "METHODOLOGY.md"),
            supported_workflows=("benchmarking", "clustering", "anomaly_detection"),
            output_formats=("markdown", "json"),
        ),
        "agriculture": DomainModule(
            domain_id="agriculture",
            label_fr="Agriculture & Marchés",
            instructions="Ancre chaque prix en XAF/kg sur les marchés suivis au Tchad avec période et intervalle de confiance 80 %.",
            allowed_tools=("chad_market_agent", "analytics_query", "ml_forecast"),
            knowledge_sources=("table_ml_forecasts", "table_ml_seasonality_studies"),
            supported_workflows=("price_forecast", "arbitrage", "seasonality"),
            output_formats=("markdown", "pdf"),
        ),
        "tech_programming": DomainModule(
            domain_id="tech_programming",
            label_fr="Tech & Programmation",
            instructions="Fournis du code propre, testable et sécurisé (Python, Dart/Flutter, SQL) sans exposer de secrets.",
            allowed_tools=("llm_reasoning", "rag_hybrid"),
            knowledge_sources=("DEVELOPER_GUIDE.md", "API.md", "ARCHITECTURE.md"),
            supported_workflows=("code_help", "debugging", "api_integration"),
            output_formats=("markdown",),
        ),
        "productivity": DomainModule(
            domain_id="productivity",
            label_fr="Productivité & Gestion",
            instructions="Structure des plans d'action concrets, checklists et synthèses exploitables.",
            allowed_tools=("llm_reasoning", "project_store"),
            knowledge_sources=("USER_GUIDE.md",),
            supported_workflows=("action_plan", "checklist", "meeting_summary"),
            output_formats=("markdown",),
        ),
        "chad_intelligence": DomainModule(
            domain_id="chad_intelligence",
            label_fr="Intelligence Tchad",
            instructions="Valorise les données locales du Tchad (provinces, marchés, XAF/kg, contexte socio-économique) en français clair.",
            allowed_tools=("chad_market_agent", "analytics_query", "rag_hybrid", "study_builder"),
            knowledge_sources=("table_ml_forecasts", "table_ml_credit_passport", "DATA_CATALOG.md"),
            supported_workflows=("regional_comparison", "market_study", "risk_analysis"),
            output_formats=("markdown", "pdf"),
        ),
    }

    _DOMAIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("tech_programming", re.compile(r"\b(?:python|flutter|dart|sql|fastapi|code|bug|api|script|regex|git|docker)\b")),
        ("data_science", re.compile(r"\b(?:machine\s+learning|regression|ridge|k[-\s]?means|clustering|backtest|rmse|mae|mape|modele\s+ml)\b")),
        ("education", re.compile(r"\b(?:cours|explique|reviser|exercice|etudiant|apprendre|definition|theoreme)\b")),
        ("academic_research", re.compile(r"\b(?:these|memoire|article\s+scientifique|bibliographie|methodologie\s+de\s+recherche|revue\s+de\s+litterature)\b")),
        ("productivity", re.compile(r"\b(?:planning|checklist|organiser|resume\s+de\s+reunion|tache|roadmap|productivite)\b")),
        ("finance", re.compile(r"\b(?:tresorerie|bfr|capex|point\s+mort|roi|rentabilite|cashflow|credit\s+passport)\b")),
        ("business_entrepreneurship", re.compile(r"\b(?:business\s*plan|etude\s+de\s+(?:prefaisabilite|marche)|entreprise|negoce|swot|pestel)\b")),
        ("agriculture", re.compile(r"\b(?:mil|sorgho|mais|riz|arachide|niebe|recolte|agricole|marche|prix\s+du)\b")),
        ("chad_intelligence", re.compile(r"\b(?:tchad|n'djamena|ndjamena|lac|batha|ouaddai|kanem|moundou|sarh|abeche|xaf|fcfa)\b")),
    ]

    @classmethod
    def list_domains(cls) -> list[dict[str, Any]]:
        return [m.to_dict() for m in cls.MODULES.values()]

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
            if pat.search(q_norm):
                return cls.MODULES[dom_id]
        return cls.MODULES["general_ai"]

