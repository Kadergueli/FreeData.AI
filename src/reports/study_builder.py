"""Assembleur d'étude de marché PRO 100 % ancré sur MarketDataProvider et business_engine (zéro hallucination)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from src.ai_agent import MarketDataProvider, _clean_float
from src.business_engine import build_professional_business_plan
from src.disclaimers import CREDIT_PASSPORT_DISCLAIMER


def build_market_study_dossier(
    provider: MarketDataProvider,
    commodity: str,
    origin_province: str,
    dest_province: Optional[str] = None,
    capital_xaf: float = 1_000_000.0,
    transport_cost_per_kg: float = 25.0,
    loss_rate_pct: float = 5.0,
    monthly_fixed_costs_xaf: float = 35_000.0,
    transport_is_user_provided: bool = False,
    capital_is_user_provided: bool = True,
    promoter_name: Optional[str] = None,
    user_instructions: Optional[list[str]] = None,
) -> dict:
    """Construit le dossier structuré complet à partir des seules données vérifiées disponibles."""
    resolved_comm = provider.resolve_commodity(commodity) or commodity
    comm_fr = provider.fr_commodity(resolved_comm)
    orig = provider.prov_lookup.get(origin_province.strip().lower(), origin_province) if hasattr(provider, "prov_lookup") else origin_province
    dest = (
        provider.prov_lookup.get(dest_province.strip().lower(), dest_province)
        if (dest_province and hasattr(provider, "prov_lookup"))
        else dest_province
    )

    study_id = f"FD-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    generated_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 1. Données de prix & prévisions (origine & destination)
    fc_orig = provider.get_forecasts(province=orig, commodity=resolved_comm)
    fc_dest = provider.get_forecasts(province=dest, commodity=resolved_comm) if dest else {}
    buy_price = provider._median_province_commodity_price(orig, resolved_comm)
    sell_price = provider._median_province_commodity_price(dest, resolved_comm) if dest else None

    if buy_price is None:
        raise ValueError(f"Aucune donnée de prix vérifiée pour {comm_fr} à {orig}.")

    # 2. Indice de stabilité marché (Market Risk & Stability Index)
    cp_info = provider.get_credit_passport(province=orig, commodity=resolved_comm, loan_amount=int(capital_xaf))
    cp_rec = (cp_info.get("records") or [{}])[0]
    vol_cv = _clean_float(cp_rec.get("cv_pct"))
    c_score = _clean_float(cp_rec.get("credit_score"))

    # 3. Anomalies & Saisonnalité réelles
    anoms_info = provider.get_anomalies(province=orig, commodity=resolved_comm)
    anomalies_list = (anoms_info.get("anomalies") or [])[:5]
    study_book = getattr(provider, "studies", None)
    season_study = study_book.get(resolved_comm, orig) if study_book is not None else None

    # 4. Sources documentaires RAG réelles (aucune source inventée)
    rag_query = f"{comm_fr} {orig} {dest or ''}".strip()
    rag_chunks = provider.retrieve_rag_chunks(rag_query, match_count=3)
    sources = [
        {
            "titre": c.get("titre"),
            "editeur": c.get("editeur"),
            "page": c.get("page"),
            "url_source": c.get("url_source"),
        }
        for c in rag_chunks
    ]

    # 5. Modèle financier déterministe Central + 3 Scénarios (Prudent / Central / Favorable)
    central_bp = build_professional_business_plan(
        commodity=resolved_comm,
        commodity_fr=comm_fr,
        origin_province=orig,
        dest_province=dest,
        buy_price_per_kg=buy_price,
        sell_price_per_kg=sell_price,
        volatility_cv_pct=vol_cv,
        credit_score=c_score,
        capital_xaf=capital_xaf,
        transport_cost_per_kg=transport_cost_per_kg,
        loss_rate_pct=loss_rate_pct,
        monthly_fixed_costs_xaf=monthly_fixed_costs_xaf,
        user_instructions=user_instructions,
    )

    eff_sell = sell_price if sell_price is not None else central_bp["unit_economics"]["target_sell_price_per_kg"]
    prudent_bp = build_professional_business_plan(
        commodity=resolved_comm,
        commodity_fr=comm_fr,
        origin_province=orig,
        dest_province=dest,
        buy_price_per_kg=round(buy_price * 1.10, 1),
        sell_price_per_kg=round(eff_sell * 0.90, 1),
        volatility_cv_pct=vol_cv,
        credit_score=c_score,
        capital_xaf=capital_xaf,
        transport_cost_per_kg=round(transport_cost_per_kg * 1.25, 1),
        loss_rate_pct=min(50.0, round(loss_rate_pct * 1.5, 1)),
        monthly_fixed_costs_xaf=monthly_fixed_costs_xaf,
        user_instructions=user_instructions,
    )
    favorable_bp = build_professional_business_plan(
        commodity=resolved_comm,
        commodity_fr=comm_fr,
        origin_province=orig,
        dest_province=dest,
        buy_price_per_kg=round(buy_price * 0.95, 1),
        sell_price_per_kg=round(eff_sell * 1.05, 1),
        volatility_cv_pct=vol_cv,
        credit_score=c_score,
        capital_xaf=capital_xaf,
        transport_cost_per_kg=transport_cost_per_kg,
        loss_rate_pct=max(1.0, round(loss_rate_pct * 0.7, 1)),
        monthly_fixed_costs_xaf=monthly_fixed_costs_xaf,
        user_instructions=user_instructions,
    )

    scenarios = [
        {
            "name": "Prudent",
            "buy_price_per_kg": prudent_bp["unit_economics"]["buy_price_per_kg"],
            "sell_price_per_kg": prudent_bp["unit_economics"]["sell_price_per_kg"],
            "transport_cost_per_kg": prudent_bp["unit_economics"]["transport_cost_per_kg"],
            "loss_rate_pct": prudent_bp["unit_economics"]["loss_rate_pct"],
            "net_profit_cycle1_xaf": prudent_bp["unit_economics"]["net_profit_cycle1_xaf"],
            "roi_cycle1_pct": prudent_bp["unit_economics"]["roi_cycle1_pct"],
        },
        {
            "name": "Central",
            "buy_price_per_kg": central_bp["unit_economics"]["buy_price_per_kg"],
            "sell_price_per_kg": eff_sell,
            "transport_cost_per_kg": central_bp["unit_economics"]["transport_cost_per_kg"],
            "loss_rate_pct": central_bp["unit_economics"]["loss_rate_pct"],
            "net_profit_cycle1_xaf": central_bp["unit_economics"]["net_profit_cycle1_xaf"],
            "roi_cycle1_pct": central_bp["unit_economics"]["roi_cycle1_pct"],
        },
        {
            "name": "Favorable",
            "buy_price_per_kg": favorable_bp["unit_economics"]["buy_price_per_kg"],
            "sell_price_per_kg": favorable_bp["unit_economics"]["sell_price_per_kg"],
            "transport_cost_per_kg": favorable_bp["unit_economics"]["transport_cost_per_kg"],
            "loss_rate_pct": favorable_bp["unit_economics"]["loss_rate_pct"],
            "net_profit_cycle1_xaf": favorable_bp["unit_economics"]["net_profit_cycle1_xaf"],
            "roi_cycle1_pct": favorable_bp["unit_economics"]["roi_cycle1_pct"],
        },
    ]

    # 6. Données manquantes & réserves explicites (zéro hallucination)
    data_gaps = [
        "Les données FreeData.AI couvrent les prix de marché : les volumes de demande des ménages et les parts de marché des concurrents ne sont pas mesurés.",
        "Frais non inclus automatiquement dans les charges fixes standards : taxes communales, assurance, intérêts de financement et gardiennage spécifique.",
    ]
    if sell_price is None:
        data_gaps.append(
            f"Prix de vente à destination ({dest or 'non précisée'}) absent des séries suivies : le scénario Central utilise une cible simulée (+15 % au-dessus du point mort)."
        )
    if not transport_is_user_provided:
        data_gaps.append(
            f"Coût de transport basé sur l'hypothèse indicative de {transport_cost_per_kg:g} XAF/kg (à confirmer par devis transporteur)."
        )
    if not season_study:
        data_gaps.append("Étude saisonnière 12 mois indisponible pour cette combinaison province/produit.")

    provenance = {
        "buy_price_per_kg": "retrieved_from_dataset",
        "sell_price_per_kg": "retrieved_from_dataset" if sell_price is not None else "simulated_target_break_even_plus_15pct",
        "capital_xaf": "user_provided" if capital_is_user_provided else "default_assumption",
        "transport_cost_per_kg": "user_provided" if transport_is_user_provided else "default_assumption",
        "market_stability_index": "retrieved_from_dataset" if c_score is not None else "unavailable",
        "financial_scenarios": "calculated_deterministic",
    }

    return {
        "study_id": study_id,
        "generated_at_utc": generated_at_utc,
        "tier": "premium",
        "promoter_name": promoter_name or "Non précisé",
        "commodity": resolved_comm,
        "commodity_fr": comm_fr,
        "origin_province": orig,
        "dest_province": dest,
        "market_data": {
            "origin_forecasts": fc_orig.get("records", [])[:5],
            "destination_forecasts": fc_dest.get("records", [])[:5] if fc_dest else [],
            "market_stability": cp_rec,
            "market_stability_disclaimer": CREDIT_PASSPORT_DISCLAIMER,
            "recent_anomalies": anomalies_list,
            "seasonality": season_study,
        },
        "business_plan": central_bp,
        "scenarios": scenarios,
        "sources": sources,
        "user_instructions": list(user_instructions or []),
        "data_gaps": data_gaps,
        "provenance": provenance,
    }

