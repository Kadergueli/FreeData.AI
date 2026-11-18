"""ReportOrchestrator: coordinates analytical engines, section selection, and provenance."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.reports.engines import (
    DataProvenanceManager,
    FinancialAnalysisEngine,
    MarketAnalysisEngine,
    RecommendationEngine,
    RiskAnalysisEngine,
)
from src.reports.sections import ReportSection, SectionGenerator, detect_report_type, select_sections


@dataclass
class ReportDocument:
    title: str
    subtitle: str
    report_type: str
    study_id: str
    generated_at_utc: str
    promoter_name: str
    route: str
    verdict: dict[str, Any]
    metadata_rows: list[list[str]]
    study_context: dict[str, Any]
    user_instructions: list[str]
    sections: list[ReportSection] = field(default_factory=list)


class ReportOrchestrator:
    """Assembles a complete, evidence-backed ReportDocument from a market-study dossier."""

    def __init__(self) -> None:
        self.provenance_mgr = DataProvenanceManager()
        self.market_engine = MarketAnalysisEngine()
        self.financial_engine = FinancialAnalysisEngine()
        self.risk_engine = RiskAnalysisEngine()
        self.recommendation_engine = RecommendationEngine()
        self.section_gen = SectionGenerator()

    def build_document(self, dossier: dict) -> ReportDocument:
        study_context = dict(dossier.get("study_context") or {})
        report_type = detect_report_type(dossier, study_context)

        provenance = self.provenance_mgr.build(dossier)
        market = self.market_engine.analyze(dossier, study_context)
        financial = self.financial_engine.analyze(dossier)
        risk = self.risk_engine.analyze(dossier)
        rec = self.recommendation_engine.analyze(dossier, study_context)

        orig = dossier.get("origin_province") or "-"
        dest = dossier.get("dest_province")
        route = f"{orig} -> {dest}" if dest else f"{orig} (marche local)"

        ca = financial["capital_allocation"]
        ue = financial["unit_economics"]
        is_non_rentable = financial["is_non_rentable"]
        if is_non_rentable:
            min_cap = ue.get("min_theoretical_capital_xaf")
            cap_msg = (
                f"Capital minimum theorique requis pour absorber les couts fixes : {_xaf_str(min_cap)}."
                if min_cap is not None and min_cap > 0
                else "Marge unitaire <= 0 a ces prix : corridor structurellement non rentable sans baisse du prix d'achat ou hausse du prix de vente."
            )
            verdict = {
                "is_non_rentable": True,
                "title": "STATUT : NON RENTABLE A CETTE ECHELLE",
                "text": (
                    f"Perte nette reelle Cycle 1 : {_xaf_str(ue.get('net_profit_cycle1_xaf'))} "
                    f"(ROI {_num_str(ue.get('roi_cycle1_pct'), ' %')}). {cap_msg}"
                ),
            }
        else:
            verdict = {
                "is_non_rentable": False,
                "title": "STATUT : VIABLE / RENTABLE A CETTE ECHELLE",
                "text": (
                    f"Resultat net Cycle 1 : {_xaf_str(ue.get('net_profit_cycle1_xaf'))} "
                    f"(ROI {_num_str(ue.get('roi_cycle1_pct'), ' %')}). "
                    f"Point mort : {_num_str(ue.get('break_even_price_per_kg'), ' XAF/kg')}."
                ),
            }

        type_labels = {
            "market_study": "Etude de Marche PRO",
            "feasibility_study": "Etude de Prefaisabilite & Business Plan",
            "financial_analysis": "Analyse Financiere PRO",
        }
        metadata_rows = [
            ["Reference etude", str(dossier.get("study_id", "-"))],
            ["Type de rapport", type_labels.get(report_type, "Etude PRO")],
            ["Date de generation (UTC)", str(dossier.get("generated_at_utc", "-"))],
            ["Promoteur", str(dossier.get("promoter_name", "Non precise"))],
            ["Produit / Corridor", f"{dossier.get('commodity_fr', '')} - {route}"],
            ["Capital engage", _xaf_str(ca.get("total_capital_xaf"))],
            ["Point mort (seuil minimal)", f"{_num_str(ue.get('break_even_price_per_kg'), ' XAF/kg')} ({_xaf_str(ue.get('break_even_bag_100kg_xaf'))} / sac 100 kg)"],
            ["Resultat net Cycle 1 (Central)", f"{_xaf_str(ue.get('net_profit_cycle1_xaf'))} (ROI {_num_str(ue.get('roi_cycle1_pct'), ' %')})"],
        ]

        section_ids = select_sections(report_type, dossier, study_context)
        sections = [
            self.section_gen.generate(
                sec_id,
                dossier=dossier,
                market=market,
                financial=financial,
                risk=risk,
                rec=rec,
                provenance=provenance,
                study_context=study_context,
            )
            for sec_id in section_ids
        ]

        return ReportDocument(
            title="FreeData.AI Market Intelligence - Dossier PRO",
            subtitle=f"{type_labels.get(report_type, 'Etude')} : {dossier.get('commodity_fr', '')} ({route})",
            report_type=report_type,
            study_id=str(dossier.get("study_id", "-")),
            generated_at_utc=str(dossier.get("generated_at_utc", "-")),
            promoter_name=str(dossier.get("promoter_name", "Non precise")),
            route=route,
            verdict=verdict,
            metadata_rows=metadata_rows,
            study_context=study_context,
            user_instructions=list(dossier.get("user_instructions") or []),
            sections=sections,
        )


def _xaf_str(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"{round(float(val)):,} XAF".replace(",", " ")
    except (TypeError, ValueError):
        return str(val)


def _num_str(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        txt = f"{f:.1f}" if not f.is_integer() else f"{int(f)}"
        return f"{txt}{suffix}"
    except (TypeError, ValueError):
        return str(val)

