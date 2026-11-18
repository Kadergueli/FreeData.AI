"""Modular analytical and provenance engines for FreeData.AI professional reports."""
from __future__ import annotations

from typing import Any


class DataProvenanceManager:
    """Tracks source, period, geography, observation count, and evidence status for every claim."""

    def build(self, dossier: dict) -> dict[str, Any]:
        trace = dossier.get("data_traceability") or {}
        prov = dossier.get("provenance") or {}
        orig = dossier.get("origin_province") or "—"
        dest = dossier.get("dest_province")
        geo = f"{orig} -> {dest}" if dest else f"{orig} (marche local)"

        items = [
            {
                "component": "Prix observes (marches suivis)",
                "source_name": trace.get("observed_sources") or "Source primaire non renseignee",
                "data_period": trace.get("latest_observed_date") or "Non renseignee",
                "geographic_coverage": geo,
                "observation_count": str(trace.get("observation_count", 0)),
                "evidence_status": "observe",
                "methodology": "Mediane provinciale des derniers releves verifies en base.",
            },
            {
                "component": "Previsions t+1 & Intervalle 80 %",
                "source_name": f"Moteur statistique FreeData.AI ({trace.get('dataset_id', '-')})",
                "data_period": trace.get("latest_observed_date") or "Horizon t+1",
                "geographic_coverage": geo,
                "observation_count": str(trace.get("observation_count", 0)),
                "evidence_status": "simule (modele statistique)",
                "methodology": "Prevision deterministe a 1 mois avec intervalle de confiance a 80 %.",
            },
            {
                "component": "Indice de Stabilite Marche",
                "source_name": "FreeData.AI Credit Passport" if prov.get("market_stability_index") == "retrieved_from_dataset" else "Indisponible",
                "data_period": trace.get("latest_observed_date") or "—",
                "geographic_coverage": orig,
                "observation_count": "1" if prov.get("market_stability_index") == "retrieved_from_dataset" else "0",
                "evidence_status": "observe" if prov.get("market_stability_index") == "retrieved_from_dataset" else "indisponible",
                "methodology": "Score composite /100 base sur volatilite (CV %) et drawdown historique.",
            },
            {
                "component": "Capital & Parametres logistiques",
                "source_name": trace.get("logistics_source") or "Hypotheses standards FreeData.AI",
                "data_period": "Cycle 1 - M1 a M6",
                "geographic_coverage": geo,
                "observation_count": "—",
                "evidence_status": "fourni par le promoteur" if prov.get("transport_cost_per_kg") == "user_provided" else "hypothese standard",
                "methodology": "Calcul deterministe (BFR/CAPEX/Reserve, sacherie 5 XAF/kg, charges fixes).",
            },
        ]
        return {
            "items": items,
            "data_gaps": list(dossier.get("data_gaps") or []),
            "rag_sources": list(dossier.get("sources") or []),
        }


class MarketAnalysisEngine:
    """Extracts verified market prices, spread, trend t+1, and explicit coverage gaps."""

    def analyze(self, dossier: dict, study_context: dict) -> dict[str, Any]:
        md = dossier.get("market_data") or {}
        orig_fc = md.get("origin_forecasts") or []
        dest_fc = md.get("destination_forecasts") or []
        all_fc = orig_fc + dest_fc

        bp = dossier.get("business_plan") or {}
        cmm = bp.get("certified_market_metrics") or {}
        buy_p = cmm.get("buy_price_per_kg")
        sell_p = cmm.get("sell_price_per_kg")
        t1_sell = cmm.get("predicted_t1_sell_price_per_kg")

        spread = round(float(sell_p) - float(buy_p), 1) if (buy_p is not None and sell_p is not None) else None
        trend_direction = "neutre"
        if sell_p is not None and t1_sell is not None:
            if t1_sell < sell_p:
                trend_direction = "baissiere"
            elif t1_sell > sell_p:
                trend_direction = "haussiere"

        return {
            "forecasts": all_fc,
            "buy_price_per_kg": buy_p,
            "sell_price_per_kg": sell_p,
            "predicted_t1_sell_price_per_kg": t1_sell,
            "price_spread_xaf_kg": spread,
            "trend_direction": trend_direction,
            "seasonality": md.get("seasonality"),
            "target_customers": list(study_context.get("target_customers") or []),
            "supply_demand_available": False,
            "competitors_available": False,
            "supply_demand_note": (
                "Non mesure quantitativement : les jeux de donnees FreeData.AI suivent les prix de marche "
                "mais ne mesurent pas les volumes d'offre/demande des menages."
            ),
            "competitors_note": (
                "Non mesure quantitativement : aucune donnee sur les parts de marche ou prix individuels des concurrents. "
                "Verification terrain requise aupres de 5 acheteurs/grossistes locaux."
            ),
        }


class FinancialAnalysisEngine:
    """Structures investment, unit economics, cash flow, scenarios, and sensitivity analysis."""

    def analyze(self, dossier: dict) -> dict[str, Any]:
        bp = dossier.get("business_plan") or {}
        ca = bp.get("capital_allocation") or {}
        ue = bp.get("unit_economics") or {}
        return {
            "capital_allocation": ca,
            "unit_economics": ue,
            "projection_6_months": list(bp.get("projection_6_months") or []),
            "scenarios": list(dossier.get("scenarios") or []),
            "stress_tests": list(bp.get("stress_tests") or []),
            "is_non_rentable": ue.get("profitability_status") == "NON RENTABLE À CETTE ÉCHELLE",
            "reinvest_enabled": bool(ue.get("reinvest_enabled", True)),
            "reinvest_rate_pct": ue.get("reinvest_rate_pct", 75.0),
        }


class RiskAnalysisEngine:
    """Synthesizes market stability, anomalies, and stress-test sensitivities."""

    def analyze(self, dossier: dict) -> dict[str, Any]:
        md = dossier.get("market_data") or {}
        bp = dossier.get("business_plan") or {}
        return {
            "market_stability": md.get("market_stability") or {},
            "stability_disclaimer": md.get("market_stability_disclaimer") or "",
            "recent_anomalies": list(md.get("recent_anomalies") or []),
            "stress_tests": list(bp.get("stress_tests") or []),
        }


class RecommendationEngine:
    """Builds context-aligned operational recommendations and 24h-48h field validation."""

    def analyze(self, dossier: dict, study_context: dict) -> dict[str, Any]:
        bp = dossier.get("business_plan") or {}
        cs = bp.get("commercial_strategy") or {}
        ue = bp.get("unit_economics") or {}
        return {
            "flow_strategy": cs.get("flow_strategy") or "",
            "distribution_channel": cs.get("distribution_channel") or "",
            "long_distance_freight_warning": bool(cs.get("long_distance_freight_warning")),
            "max_buy_price_20pct_per_kg": ue.get("max_buy_price_20pct_per_kg"),
            "objectives": list(study_context.get("objectives") or []),
            "operational_constraints": list(study_context.get("operational_constraints") or []),
            "checklist": [
                ("1. Fret reel", "Devis transporteur bord-champ -> destination (XAF/kg)", "________\u00a0XAF/kg"),
                ("2. Taxes communales", "Ticket de place / droits de marche hebdomadaires", "________\u00a0XAF"),
                ("3. Vitesse d'ecoulement", "Capacite d'absorption en sacs/semaine (5 acheteurs)", "________\u00a0sacs/sem"),
                ("4. Gardiennage / magasinage", "Loyer depot ou gardiennage nocturne", "________\u00a0XAF/mois"),
                ("5. Prix d'achat ferme", "Prix negocie bord-champ ou demi-gros", "________\u00a0XAF/kg"),
            ],
        }

