"""Dynamic report-type detection and section generation for FreeData.AI reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportSection:
    section_id: str
    title: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    is_available: bool = True
    provenance_tag: str = "verified_and_deterministic"


def detect_report_type(dossier: dict, study_context: dict) -> str:
    """Selects report template type: 'market_study', 'feasibility_study', or 'financial_analysis'."""
    explicit = dossier.get("report_type") or study_context.get("report_type")
    if explicit in ("market_study", "feasibility_study", "financial_analysis"):
        return str(explicit)

    req = set(study_context.get("required_sections") or [])
    objs = " ".join(study_context.get("objectives") or []).lower()
    if "analyse financiere" in objs or (req and req.issubset({"six_month_projection", "stress_tests", "business_plan"})):
        return "financial_analysis"
    if "market_study" in req and "business_plan" not in req and not dossier.get("dest_province"):
        return "market_study"
    return "feasibility_study"


def select_sections(report_type: str, dossier: dict, study_context: dict) -> list[str]:
    """Dynamically chooses ordered sections based on report type, user requests, exclusions, and data."""
    req = list(study_context.get("required_sections") or [])
    excl = set(study_context.get("excluded_sections") or [])
    if "stress_tests" in excl:
        excl.add("risk_and_sensitivity")

    if report_type == "market_study":
        base = [
            "market_prices",
            "market_stability",
            "capital_and_scenarios",
            "commercial_and_validation",
            "sources_and_limitations",
        ]
    elif report_type == "financial_analysis":
        base = [
            "capital_and_scenarios",
            "six_month_projection",
            "risk_and_sensitivity",
            "sources_and_limitations",
        ]
    else:  # feasibility_study (default)
        base = [
            "market_prices",
            "market_stability",
            "capital_and_scenarios",
            "six_month_projection",
            "risk_and_sensitivity",
            "commercial_and_validation",
            "sources_and_limitations",
        ]

    # Insert optional requested sections before sources_and_limitations
    dynamic_extras = [s for s in req if s in ("SWOT", "PESTEL", "competitor_analysis", "operational_recommendations", "supply_demand")]
    ordered: list[str] = []
    for sec in base:
        if sec == "sources_and_limitations":
            for extra in dynamic_extras:
                if extra not in ordered:
                    ordered.append(extra)
        if sec not in ordered:
            ordered.append(sec)

    # If user explicitly asked for six_month_projection or stress_tests in market_study, include them
    if "six_month_projection" in req and "six_month_projection" not in ordered:
        idx = ordered.index("sources_and_limitations")
        ordered.insert(idx, "six_month_projection")
    if "stress_tests" in req and "risk_and_sensitivity" not in ordered:
        idx = ordered.index("sources_and_limitations")
        ordered.insert(idx, "risk_and_sensitivity")

    return [s for s in ordered if s not in excl]


class SectionGenerator:
    """Builds structured content blocks for each selected report section."""

    def generate(
        self,
        section_id: str,
        *,
        dossier: dict,
        market: dict[str, Any],
        financial: dict[str, Any],
        risk: dict[str, Any],
        rec: dict[str, Any],
        provenance: dict[str, Any],
        study_context: dict[str, Any],
    ) -> ReportSection:
        if section_id == "market_prices":
            rows = [["Marche", "Province", "Observe (XAF/kg)", "Prevu t+1 (XAF/kg)", "Intervalle 80 %"]]
            for r in market["forecasts"]:
                rows.append([
                    str(r.get("market_name", "-")),
                    str(r.get("province", "-")),
                    _fmt_num(r.get("last_observed_price")),
                    _fmt_num(r.get("forecast_t1")),
                    f"{_fmt_num(r.get('ci_low_80'))} - {_fmt_num(r.get('ci_high_80'))}",
                ])
            blocks: list[dict[str, Any]] = []
            if len(rows) > 1:
                blocks.append({"type": "table", "rows": rows, "col_widths_cm": [4.2, 3.5, 3.0, 3.0, 3.3]})
                if market.get("price_spread_xaf_kg") is not None:
                    blocks.append({
                        "type": "paragraph",
                        "text": f"<b>Ecart observe / retenu :</b> {_fmt_num(market['price_spread_xaf_kg'], ' XAF/kg')} | "
                                f"<b>Tendance t+1 :</b> {market['trend_direction']}.",
                    })
            else:
                blocks.append({"type": "paragraph", "text": "Aucune serie detaillee disponible pour ce filtre."})
            return ReportSection("market_prices", "Analyse des prix observes et previsions t+1", blocks, is_available=len(rows) > 1)

        if section_id == "market_stability":
            stab = risk["market_stability"]
            blocks = []
            if stab:
                blocks.append({
                    "type": "paragraph",
                    "text": (
                        f"Score stabilite : <b>{_fmt_num(stab.get('credit_score'), '/100')}</b> (Classe {stab.get('grade', '-')}) | "
                        f"Volatilite CV : {_fmt_num(stab.get('cv_pct'), ' %')} | "
                        f"LTV indicatif : {_fmt_num(float(stab.get('ltv_ratio', 0)) * 100, ' %')}"
                    ),
                })
            else:
                blocks.append({"type": "paragraph", "text": "Indice de stabilite non disponible pour ce couple province/produit."})
            if risk.get("stability_disclaimer"):
                blocks.append({"type": "small", "text": f"<i>{risk['stability_disclaimer']}</i>"})
            return ReportSection("market_stability", "Indice de Stabilite Marche", blocks, is_available=bool(stab))

        if section_id == "capital_and_scenarios":
            ca = financial["capital_allocation"]
            wc_pct = f"{ca.get('working_capital_share_pct', 80.0):.0f} %"
            capex_pct = f"{ca.get('capex_share_pct', 8.0):.0f} %"
            res_pct = f"{ca.get('safety_share_pct', 12.0):.0f} %"
            alloc_rows = [
                ["Poste", "Montant", "Part", "Usage & Statut"],
                ["BFR operationnel", _fmt_xaf(ca.get("working_capital_xaf")), wc_pct, "Achat stock + transport + sacherie (calcule)"],
                ["CAPEX equipement", _fmt_xaf(ca.get("capex_equipment_xaf")), capex_pct, "Balance, baches, palettes (0 % si sans equipement)"],
                ["Reserve d'urgence", _fmt_xaf(ca.get("safety_cash_reserve_xaf")), res_pct, "Liquidites de securite (non engagees en stock)"],
            ]
            scen_rows = [["Scenario", "Achat (XAF/kg)", "Vente (XAF/kg)", "Fret (XAF/kg)", "Pertes (%)", "Resultat Cycle 1 & ROI"]]
            for sc in financial["scenarios"]:
                scen_rows.append([
                    sc["name"],
                    _fmt_num(sc["buy_price_per_kg"]),
                    _fmt_num(sc["sell_price_per_kg"]),
                    _fmt_num(sc["transport_cost_per_kg"]),
                    _fmt_num(sc["loss_rate_pct"], " %"),
                    f"{_fmt_xaf(sc['net_profit_cycle1_xaf'])} ({_fmt_num(sc['roi_cycle1_pct'], ' %')})",
                ])
            blocks = [
                {"type": "table", "rows": alloc_rows, "col_widths_cm": [3.6, 3.3, 1.7, 8.4]},
                {"type": "spacer", "cm": 0.25},
                {"type": "table", "rows": scen_rows, "col_widths_cm": [2.2, 2.5, 2.5, 2.4, 2.0, 5.4]},
            ]
            return ReportSection(
                "capital_and_scenarios",
                f"Allocation du capital ({wc_pct}/{capex_pct}/{res_pct}) & Scenarios financiers",
                blocks,
            )

        if section_id == "six_month_projection":
            reinv_mode = (
                f"Reinvestissement {financial['reinvest_rate_pct']:.0f} % du resultat net dans le BFR"
                if financial["reinvest_enabled"]
                else "BFR constant M1-M6 (sans reinvestissement)"
            )
            proj_rows = [["Mois", "BFR", "Chiffre d'affaires", "Couts totaux", "Resultat net", "Tresorerie cumulee"]]
            for p in financial["projection_6_months"]:
                proj_rows.append([
                    f"M{p['month']}",
                    _fmt_xaf(p["working_capital"]),
                    _fmt_xaf(p["revenue"]),
                    _fmt_xaf(p["total_costs"]),
                    _fmt_xaf(p["net_profit"]),
                    _fmt_xaf(p["cumulative_cash"]),
                ])
            blocks = [
                {"type": "table", "rows": proj_rows, "col_widths_cm": [1.4, 3.1, 3.3, 3.1, 3.0, 3.1]},
                {"type": "spacer", "cm": 0.2},
                {"type": "chart_cashflow", "projection": financial["projection_6_months"]},
            ]
            return ReportSection(
                "six_month_projection",
                f"Compte d'exploitation previsionnel sur 6 mois ({reinv_mode})",
                blocks,
            )

        if section_id == "risk_and_sensitivity":
            st_rows = [["Scenario de resistance (Cycle 1)", "Hypothese", "Resultat net (XAF)", "ROI"]]
            for st in risk["stress_tests"]:
                st_rows.append([
                    st["scenario"],
                    st["assumption"],
                    _fmt_xaf(st["net_profit_xaf"]),
                    _fmt_num(st["roi_pct"], " %"),
                ])
            blocks = [{"type": "table", "rows": st_rows, "col_widths_cm": [5.2, 5.5, 3.8, 2.5]}]
            return ReportSection("risk_and_sensitivity", "Analyse des risques & Tests de sensibilite", blocks)

        if section_id == "SWOT":
            stab = risk["market_stability"]
            obs_count = (dossier.get("data_traceability") or {}).get("observation_count", 0)
            ue = financial["unit_economics"]
            swot_rows = [
                ["Forces (donnees verifiees)", "Faiblesses & limites"],
                [
                    f"Corridor suivi ({obs_count} obs.). "
                    + (f"Marge Cycle 1 positive ({_fmt_xaf(ue.get('net_profit_cycle1_xaf'))})." if not financial["is_non_rentable"] else "Echelle actuelle non rentable."),
                    f"Point mort a {_fmt_num(ue.get('break_even_price_per_kg'), ' XAF/kg')}. Demande locale et taxes communales non mesurees.",
                ],
                ["Opportunites (tendance t+1)", "Menaces & risques"],
                [
                    rec["flow_strategy"] or "Arbitrage selon ecart de prix observe.",
                    f"Volatilite CV : {_fmt_num(stab.get('cv_pct'), ' %') if stab else 'non mesuree'} | "
                    f"Stabilite : {_fmt_num(stab.get('credit_score'), '/100') if stab else 'indisponible'}.",
                ],
            ]
            return ReportSection("SWOT", "Analyse SWOT (ancree sur les indicateurs FreeData.AI)", [{"type": "table", "rows": swot_rows, "col_widths_cm": [8.5, 8.5]}])

        if section_id == "PESTEL":
            ca = financial["capital_allocation"]
            ue = financial["unit_economics"]
            pestel_rows = [
                ["Dimension", "Elements verifies / Points a valider sur le terrain"],
                ["Politique & Legal", "Taxes communales, tickets de place et reglementation de transport non mesures en base (a verifier en 24h-48h)."],
                ["Economique", f"Capital engage {_fmt_xaf(ca.get('total_capital_xaf'))}, fret indicatif {_fmt_num(ue.get('transport_cost_per_kg'), ' XAF/kg')}, pertes {_fmt_num(ue.get('loss_rate_pct'), ' %')}."],
                ["Socioculturel", f"Clientele cible : {', '.join(market.get('target_customers') or ['acteurs locaux a confirmer'])}. Volumes de consommation non mesures."],
                ["Technologique & Logistique", "Suivi des prix FreeData.AI ; conservation depend des baches, palettes et magasinage local."],
                ["Environnemental", "Risque de pertes post-recolte (5 % par defaut) et saisonnalite agricole tchadienne."],
            ]
            return ReportSection("PESTEL", "Analyse PESTEL (perimetre factuel & lacunes)", [{"type": "table", "rows": pestel_rows, "col_widths_cm": [4.2, 12.8]}])

        if section_id == "competitor_analysis":
            return ReportSection(
                "competitor_analysis",
                "Analyse Concurrentielle (Statut des donnees)",
                [{"type": "paragraph", "text": market["competitors_note"]}],
                is_available=False,
                provenance_tag="unavailable",
            )

        if section_id == "supply_demand":
            return ReportSection(
                "supply_demand",
                "Analyse Offre & Demande (Statut des donnees)",
                [{"type": "paragraph", "text": market["supply_demand_note"]}],
                is_available=False,
                provenance_tag="unavailable",
            )

        if section_id == "operational_recommendations":
            items = [
                f"- <b>Discipline de prix :</b> Prix plafond d'achat terrain pour ~20 % de marge brute : {_fmt_num(rec.get('max_buy_price_20pct_per_kg'), ' XAF/kg')}.",
                f"- <b>Canal prioritaire :</b> {rec.get('distribution_channel') or 'Valider les debouches locaux avant decaissement.'}",
                "- <b>Validation pre-decaissement :</b> Completer les 5 parametres de la checklist terrain avant tout achat ferme.",
            ]
            return ReportSection(
                "operational_recommendations",
                "Recommandations Operationnelles & Plan d'Action",
                [{"type": "paragraph", "text": txt} for txt in items],
            )

        if section_id == "commercial_and_validation":
            blocks = []
            if rec.get("flow_strategy"):
                blocks.append({"type": "paragraph", "text": f"<b>Ecoulement recommande (tendance t+1) :</b> {rec['flow_strategy']}"})
            if rec.get("distribution_channel"):
                blocks.append({"type": "paragraph", "text": f"<b>Canal de distribution adapte au capital :</b> {rec['distribution_channel']}"})
            if rec.get("long_distance_freight_warning"):
                blocks.append({"type": "paragraph", "text": "<b>Alerte fret longue distance :</b> Le tarif par defaut de 25 XAF/kg doit etre reevalue selon un devis transporteur reel."})
            checklist_rows = [["Parametre terrain (24h-48h)", "Objectif de verification", "Valeur verifiee (a remplir)"]]
            for param, obj, blank in rec["checklist"]:
                checklist_rows.append([param, obj, blank])
            blocks.append({"type": "spacer", "cm": 0.15})
            blocks.append({"type": "table", "rows": checklist_rows, "col_widths_cm": [4.4, 7.8, 4.8]})
            return ReportSection("commercial_and_validation", "Strategie Commerciale & Plan de Validation Terrain", blocks)

        # Default: sources_and_limitations
        prov_rows = [["Composant", "Source", "Periode", "Couverture", "Obs.", "Statut"]]
        for it in provenance["items"]:
            prov_rows.append([
                it["component"],
                it["source_name"],
                it["data_period"],
                it["geographic_coverage"],
                it["observation_count"],
                it["evidence_status"],
            ])
        blocks = [{"type": "table", "rows": prov_rows, "col_widths_cm": [3.2, 3.8, 2.0, 3.0, 1.2, 3.8]}]
        blocks.append({"type": "spacer", "cm": 0.15})
        blocks.append({"type": "paragraph", "text": "<b>Limites methodologiques verifiees :</b>"})
        for gap in provenance["data_gaps"]:
            blocks.append({"type": "small", "text": f"- {gap}"})
        if provenance["rag_sources"]:
            blocks.append({"type": "spacer", "cm": 0.1})
            blocks.append({"type": "paragraph", "text": "<b>Sources documentaires RAG associees :</b>"})
            for src in provenance["rag_sources"]:
                blocks.append({"type": "small", "text": f"- {src.get('editeur', 'Source')} - {src.get('titre', 'Document')} (p.{src.get('page', '?')})"})
        return ReportSection("sources_and_limitations", "Tracabilite des Sources, Methodologie & Limites", blocks)


def _fmt_num(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        txt = f"{f:.1f}" if not f.is_integer() else f"{int(f)}"
        return f"{txt}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_xaf(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"{round(float(val)):,} XAF".replace(",", " ")
    except (TypeError, ValueError):
        return str(val)
