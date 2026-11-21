"""Moteur déterministe de Business Plan professionnel (CAPEX, BFR, 6 mois, Point mort, Stress-tests)."""
from __future__ import annotations

import math
import unicodedata
from typing import Optional

# Source unique de vérité pour l'allocation du capital (spécification officielle 80 / 8 / 12)
WORKING_CAPITAL_SHARE = 0.80
CAPEX_SHARE = 0.08
RESERVE_SHARE = 0.12
REINVEST_RATE = 0.75


def _finite(name: str, value: Optional[float], *, optional: bool = False) -> Optional[float]:
    """Refuse NaN / infini : un business plan ne doit jamais être calculé sur une entrée invalide."""
    if value is None:
        if optional:
            return None
        raise ValueError(f"Paramètre manquant : {name}.")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Paramètre invalide : {name}.") from exc
    if not math.isfinite(v):
        raise ValueError(f"Paramètre invalide (non fini) : {name}.")
    return v


DEFAULT_PRICE_BASIS = {
    "buy": "dernier prix constaté sur les marchés de l'origine (médiane)",
    "sell": "prévision du mois suivant (t+1) sur les marchés de destination (médiane)",
}


def _norm_instruction(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _parse_instruction_overrides(user_instructions: Optional[list[str]]) -> tuple[Optional[bool], Optional[bool]]:
    """Détecte les surcharges explicites (sans réinvestissement / BFR constant, sans équipement / CAPEX = 0)."""
    reinvest_override: Optional[bool] = None
    zero_capex_override: Optional[bool] = None
    for raw in user_instructions or []:
        norm = _norm_instruction(raw)
        if "sans reinvestissement" in norm or "bfr constant" in norm or "sans reinjection" in norm:
            reinvest_override = False
        if (
            "sans equipement" in norm
            or "pas d'equipement" in norm
            or "capex = 0" in norm
            or "capex=0" in norm
            or "capex 0" in norm
            or "sans capex" in norm
        ):
            zero_capex_override = True
    return reinvest_override, zero_capex_override


def allocate_capital(total_capital: float, zero_capex: bool = False) -> dict:
    """
    Ventile le capital selon la règle officielle 80 / 8 / 12 (ou 88 / 0 / 12 si sans équipement) :
    - 80 % (ou 88 %) BFR opérationnel (achat de stock + transport + sacherie)
    - 8 % (ou 0 %) CAPEX équipement (balance, bâches, palettes ; reste disponible s'il n'est pas requis)
    - 12 % Réserve de liquidités d'urgence (jamais incluse dans le budget d'achat de stock)
    """
    total = float(total_capital)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("Le capital total doit être strictement positif.")
    total_r = round(total, 2)
    eff_capex_share = 0.0 if zero_capex else CAPEX_SHARE
    eff_wc_share = (WORKING_CAPITAL_SHARE + CAPEX_SHARE) if zero_capex else WORKING_CAPITAL_SHARE
    capex_budget = 0.0 if zero_capex else round(total_r * eff_capex_share, 2)
    reserve_budget = round(total_r * RESERVE_SHARE, 2)
    working_capital = round(total_r - capex_budget - reserve_budget, 2)
    if total_r.is_integer() and capex_budget.is_integer() and reserve_budget.is_integer() and working_capital.is_integer():
        total_r = int(total_r)
        capex_budget = int(capex_budget)
        reserve_budget = int(reserve_budget)
        working_capital = int(working_capital)
    return {
        "total_capital_xaf": total_r,
        "working_capital_xaf": working_capital,
        "inventory_purchasing_budget_xaf": working_capital,
        "working_capital_share_pct": round(eff_wc_share * 100.0, 1),
        "capex_equipment_xaf": capex_budget,
        "capex_share_pct": round(eff_capex_share * 100.0, 1),
        "safety_cash_reserve_xaf": reserve_budget,
        "safety_share_pct": round(RESERVE_SHARE * 100.0, 1),
        "remaining_liquidity_xaf": reserve_budget,
        "zero_capex": zero_capex,
        "capex_note": (
            "Sans équipement (CAPEX = 0 %) : la part équipement (8 %) est basculée dans le BFR opérationnel (88/0/12)."
            if zero_capex
            else "Budget équipement alloué (8 %) : balance, bâches, palettes ; peut rester inutilisé si non requis."
        ),
        "reserve_note": "Réserve de liquidités d'urgence (12 %) : non engagée dans l'achat de stock.",
    }


def _cycle_metrics(
    working_capital: float,
    buy_price_per_kg: float,
    sell_price_per_kg: float,
    transport_cost_per_kg: float,
    packaging_cost_per_kg: float,
    loss_rate_pct: float,
    monthly_fixed_costs_xaf: float,
    cycles_per_month: float,
) -> dict:
    unit_landed_cost = round(buy_price_per_kg + transport_cost_per_kg + packaging_cost_per_kg, 1)
    eff_landed = max(unit_landed_cost, 1.0)
    volume_bought_kg = int(max(working_capital, 0.0) // eff_landed)
    volume_sellable_kg = round(volume_bought_kg * max(0.0, 1.0 - loss_rate_pct / 100.0), 1)
    variable_cost = round(volume_bought_kg * unit_landed_cost)
    fixed_cost_month = round(monthly_fixed_costs_xaf)
    cycles = max(float(cycles_per_month), 0.25)
    revenue = round(volume_sellable_kg * sell_price_per_kg * cycles)
    total_variable = round(variable_cost * cycles)
    gross_margin = round(revenue - total_variable)
    net_profit = round(gross_margin - fixed_cost_month)
    return {
        "unit_landed_cost": unit_landed_cost,
        "volume_bought_kg": volume_bought_kg,
        "volume_sellable_kg": volume_sellable_kg,
        "revenue": revenue,
        "total_variable_cost": total_variable,
        "total_costs": round(total_variable + fixed_cost_month),
        "gross_margin": gross_margin,
        "net_profit": net_profit,
    }


def build_professional_business_plan(
    commodity: str,
    commodity_fr: str,
    origin_province: str,
    dest_province: Optional[str],
    buy_price_per_kg: float,
    sell_price_per_kg: Optional[float],
    volatility_cv_pct: Optional[float],
    credit_score: Optional[float],
    capital_xaf: float = 1000000.0,
    transport_cost_per_kg: float = 25.0,
    loss_rate_pct: float = 5.0,
    monthly_fixed_costs_xaf: float = 35000.0,
    cycles_per_month: float = 1.0,
    user_instructions: Optional[list[str]] = None,
    reinvest: Optional[bool] = None,
    zero_capex: Optional[bool] = None,
    predicted_t1_sell_price_per_kg: Optional[float] = None,
    max_observed_dest_price_per_kg: Optional[float] = None,
    price_basis: Optional[dict] = None,
    observed_sell_price_per_kg: Optional[float] = None,
) -> dict:
    """Construit un modèle financier complet et déterministe pour un business plan bancable."""
    cap = max(_finite("capital_xaf", capital_xaf), 1.0)
    buy_p = max(_finite("buy_price_per_kg", buy_price_per_kg), 1.0)
    transport_p = max(_finite("transport_cost_per_kg", transport_cost_per_kg), 0.0)
    loss_pct = min(max(_finite("loss_rate_pct", loss_rate_pct), 0.0), 50.0)
    fixed_xaf = max(_finite("monthly_fixed_costs_xaf", monthly_fixed_costs_xaf), 0.0)
    cycles = max(_finite("cycles_per_month", cycles_per_month), 0.25)
    _finite("sell_price_per_kg", sell_price_per_kg, optional=True)
    _finite("predicted_t1_sell_price_per_kg", predicted_t1_sell_price_per_kg, optional=True)
    _finite("max_observed_dest_price_per_kg", max_observed_dest_price_per_kg, optional=True)
    _finite("observed_sell_price_per_kg", observed_sell_price_per_kg, optional=True)
    basis = {**DEFAULT_PRICE_BASIS, **(price_basis or {})}

    inst_reinvest, inst_zero_capex = _parse_instruction_overrides(user_instructions)
    eff_reinvest = True if reinvest is None and inst_reinvest is None else (reinvest if reinvest is not None else bool(inst_reinvest))
    eff_zero_capex = False if zero_capex is None and inst_zero_capex is None else (zero_capex if zero_capex is not None else bool(inst_zero_capex))

    # 1. Allocation du capital initial (80 / 8 / 12 ou 88 / 0 / 12 si sans équipement)
    capital_allocation = allocate_capital(cap, zero_capex=eff_zero_capex)
    capex_equipment_xaf = capital_allocation["capex_equipment_xaf"]
    safety_cash_reserve_xaf = capital_allocation["safety_cash_reserve_xaf"]
    working_capital_xaf = capital_allocation["working_capital_xaf"]

    # 2. Économie unitaire & Cycle 1
    packaging_cost_per_kg = 5.0
    unit_landed_cost = round(buy_p + transport_p + packaging_cost_per_kg, 1)
    volume_bought_kg = int(working_capital_xaf // max(unit_landed_cost, 1.0))
    volume_bought_bags_100kg = round(volume_bought_kg / 100.0, 2)
    volume_sellable_kg = round(volume_bought_kg * (1.0 - loss_pct / 100.0), 1)

    break_even_price_per_kg = round(
        ((volume_bought_kg * unit_landed_cost) + fixed_xaf) / max(volume_sellable_kg, 1.0),
        1,
    )
    break_even_bag_100kg_xaf = round(break_even_price_per_kg * 100.0)

    is_simulated_sell_price = sell_price_per_kg is None and predicted_t1_sell_price_per_kg is None
    if sell_price_per_kg is not None:
        eff_sell_price = round(float(sell_price_per_kg), 1)
    elif predicted_t1_sell_price_per_kg is not None:
        eff_sell_price = round(float(predicted_t1_sell_price_per_kg), 1)
    else:
        eff_sell_price = round(break_even_price_per_kg * 1.15, 1)
    requested_sell_price = eff_sell_price
    sell_price_capped = False
    if max_observed_dest_price_per_kg is not None and eff_sell_price > float(max_observed_dest_price_per_kg):
        eff_sell_price = round(float(max_observed_dest_price_per_kg), 1)
        sell_price_capped = True  # plafonné au plus haut prix réellement constaté à destination (prudence)

    gross_revenue_xaf = round(volume_sellable_kg * eff_sell_price)
    total_variable_cost_xaf = round(volume_bought_kg * unit_landed_cost)
    gross_margin_xaf = round(gross_revenue_xaf - total_variable_cost_xaf)
    net_profit_cycle1_xaf = round(gross_margin_xaf - fixed_xaf)
    roi_cycle1_pct = round((net_profit_cycle1_xaf / cap) * 100.0, 1)
    # Prix plafond d'achat sur le terrain pour conserver ~20 % de marge brute après fret, sacherie et pertes
    max_buy_price_20pct_per_kg = round(
        max(0.0, (eff_sell_price * (1.0 - loss_pct / 100.0) / 1.20) - transport_p - packaging_cost_per_kg),
        1,
    )

    is_non_rentable = (break_even_price_per_kg >= eff_sell_price) or (net_profit_cycle1_xaf <= 0)
    profitability_status = "NON RENTABLE À CETTE ÉCHELLE" if is_non_rentable else "RENTABLE"
    unit_margin_per_bought_kg = eff_sell_price * (1.0 - loss_pct / 100.0) - unit_landed_cost
    wc_share = (WORKING_CAPITAL_SHARE + CAPEX_SHARE) if eff_zero_capex else WORKING_CAPITAL_SHARE
    if unit_margin_per_bought_kg > 0 and fixed_xaf > 0:
        req_wc = (fixed_xaf / unit_margin_per_bought_kg) * unit_landed_cost
        min_theoretical_capital_xaf: Optional[int] = round(req_wc / wc_share)
    elif unit_margin_per_bought_kg > 0:
        min_theoretical_capital_xaf = 0
    else:
        min_theoretical_capital_xaf = None

    unit_economics = {
        "buy_price_per_kg": round(buy_p, 1),
        "transport_cost_per_kg": round(transport_p, 1),
        "packaging_cost_per_kg": packaging_cost_per_kg,
        "packaging_note": "Sacherie 500 XAF par sac de 100 kg (hypothèse explicite).",
        "loss_rate_pct": loss_pct,
        "monthly_fixed_costs_xaf": round(fixed_xaf),
        "unit_landed_cost": unit_landed_cost,
        "volume_bought_kg": volume_bought_kg,
        "volume_bought_bags_100kg": volume_bought_bags_100kg,
        "volume_sellable_kg": volume_sellable_kg,
        "break_even_price_per_kg": break_even_price_per_kg,
        "break_even_bag_100kg_xaf": break_even_bag_100kg_xaf,
        "max_buy_price_20pct_per_kg": max_buy_price_20pct_per_kg,
        "max_buy_price_20pct_bag_100kg_xaf": round(max_buy_price_20pct_per_kg * 100.0),
        "sell_price_per_kg": eff_sell_price if not is_simulated_sell_price else None,
        "target_sell_price_per_kg": eff_sell_price if is_simulated_sell_price else None,
        "is_simulated_sell_price": is_simulated_sell_price,
        "gross_revenue_xaf": gross_revenue_xaf,
        "total_variable_cost_xaf": total_variable_cost_xaf,
        "gross_margin_xaf": gross_margin_xaf,
        "net_profit_cycle1_xaf": net_profit_cycle1_xaf,
        "roi_cycle1_pct": roi_cycle1_pct,
        "profitability_status": profitability_status,
        "min_theoretical_capital_xaf": min_theoretical_capital_xaf,
        "reinvest_enabled": eff_reinvest,
        "reinvest_rate_pct": round(REINVEST_RATE * 100.0, 1) if eff_reinvest else 0.0,
        "unit_margin_per_bought_kg": round(unit_margin_per_bought_kg, 1),
        "safety_margin_pct": round((eff_sell_price - break_even_price_per_kg) / eff_sell_price * 100.0, 1)
        if eff_sell_price > 0
        else None,
        "sell_price_capped": sell_price_capped,
        "requested_sell_price_per_kg": requested_sell_price if sell_price_capped else None,
    }

    # 3. Projection financière sur 6 mois (75 % du bénéfice réinvesti dans le BFR par défaut, ou BFR constant si reinvest=False)
    max_working_capital = cap * 3.0
    wc = float(working_capital_xaf)
    cum_cash = float(safety_cash_reserve_xaf)
    projection_6_months: list[dict] = []
    for month in range(1, 7):
        m = _cycle_metrics(
            working_capital=wc,
            buy_price_per_kg=buy_p,
            sell_price_per_kg=eff_sell_price,
            transport_cost_per_kg=transport_p,
            packaging_cost_per_kg=packaging_cost_per_kg,
            loss_rate_pct=loss_pct,
            monthly_fixed_costs_xaf=fixed_xaf,
            cycles_per_month=cycles,
        )
        net = m["net_profit"]
        if eff_reinvest and net > 0:
            reinvested = min(net * REINVEST_RATE, max(0.0, max_working_capital - wc))
            wc = round(wc + reinvested)
            cum_cash = round(cum_cash + (net - reinvested))
        else:
            cum_cash = round(cum_cash + net)
        projection_6_months.append({
            "month": month,
            "working_capital": round(wc),
            "revenue": m["revenue"],
            "total_costs": m["total_costs"],
            "net_profit": net,
            "cumulative_cash": round(cum_cash),
        })

    # 4. Analyse de sensibilité / Stress-tests (Cycle 1)
    stress_specs = [
        ("Baisse prix de vente (-10 %)", f"Prix de vente à {round(eff_sell_price * 0.90, 1)} XAF/kg", eff_sell_price * 0.90, transport_p, loss_pct),
        ("Hausse coût transport (+25 %)", f"Fret à {round(transport_p * 1.25, 1)} XAF/kg", eff_sell_price, transport_p * 1.25, loss_pct),
        ("Doublement pertes techniques", f"Pertes à {round(loss_pct * 2.0, 1)} %", eff_sell_price, transport_p, min(loss_pct * 2.0, 50.0)),
    ]
    stress_tests: list[dict] = []
    for label, assumption, s_price, s_tr, s_loss in stress_specs:
        sm = _cycle_metrics(
            working_capital=working_capital_xaf,
            buy_price_per_kg=buy_p,
            sell_price_per_kg=s_price,
            transport_cost_per_kg=s_tr,
            packaging_cost_per_kg=packaging_cost_per_kg,
            loss_rate_pct=s_loss,
            monthly_fixed_costs_xaf=fixed_xaf,
            cycles_per_month=1.0,
        )
        stress_tests.append({
            "scenario": label,
            "assumption": assumption,
            "net_profit_xaf": sm["net_profit"],
            "roi_pct": round((sm["net_profit"] / cap) * 100.0, 1),
            "viable": sm["net_profit"] > 0,
        })

    cumulative_profit = 0.0
    payback_month: Optional[int] = None
    for row in projection_6_months:
        cumulative_profit += row["net_profit"]
        if payback_month is None and cumulative_profit >= cap:
            payback_month = row["month"]
    unit_economics["payback_month"] = payback_month
    unit_economics["cumulative_net_profit_6m_xaf"] = round(cumulative_profit)

    viable_stress = sum(1 for st in stress_tests if st["viable"])
    safety = unit_economics["safety_margin_pct"]
    if is_non_rentable:
        verdict = {
            "level": "red",
            "label": "NON RENTABLE À CETTE ÉCHELLE",
            "summary": "Le prix de vente prévu ne couvre pas le point mort : ne pas engager le capital en l'état.",
        }
    elif viable_stress == len(stress_tests):
        verdict = {
            "level": "green",
            "label": "RENTABLE ET RÉSISTANT AUX CHOCS",
            "summary": f"Le résultat reste positif dans les {len(stress_tests)} scénarios de stress testés.",
        }
    elif viable_stress >= 1:
        verdict = {
            "level": "amber",
            "label": "RENTABLE MAIS FRAGILE",
            "summary": f"Le résultat devient négatif dans {len(stress_tests) - viable_stress} scénario(s) de stress sur {len(stress_tests)}.",
        }
    else:
        verdict = {
            "level": "amber",
            "label": "RENTABLE MAIS TRÈS SENSIBLE AUX CHOCS",
            "summary": "Le moindre choc (prix, fret ou pertes) rend l'opération déficitaire : marge de sécurité insuffisante.",
        }
    verdict["safety_margin_pct"] = safety

    long_distance_freight_warning = bool(
        dest_province
        and origin_province
        and dest_province.strip().lower() != origin_province.strip().lower()
        and abs(transport_p - 25.0) < 1e-6
    )
    # Tendance = prévision t+1 comparée au dernier prix constaté à destination (à défaut, au prix de vente retenu).
    trend_ref = observed_sell_price_per_kg if observed_sell_price_per_kg is not None else sell_price_per_kg
    if predicted_t1_sell_price_per_kg is not None and trend_ref is not None and predicted_t1_sell_price_per_kg < trend_ref:
        flow_strategy = (
            "Tendance baissière (Prix prévu t+1 < Prix observé) : rotation rapide impérative "
            "(flux tendu < 15 jours) sans stockage spéculatif."
        )
    elif predicted_t1_sell_price_per_kg is not None and trend_ref is not None and predicted_t1_sell_price_per_kg > trend_ref:
        flow_strategy = (
            "Tendance haussière (Prix prévu t+1 > Prix observé) : stockage court terme envisageable "
            "sous réserve de maîtriser les pertes techniques (5 % par défaut) et le coût de magasinage."
        )
    else:
        flow_strategy = (
            "Rotation maîtrisée (flux tendu recommandé si la tendance t+1 est neutre ou incertaine) "
            "pour limiter les pertes de stockage."
        )

    distribution_channel = (
        "Vente directe aux détaillants de quartier et transformateurs locaux "
        "(économie des frais de loyer d'un box sur grand marché)."
        if cap < 250_000.0
        else "Négociation demi-gros avec restaurateurs, cantines et grossistes."
    )
    commercial_strategy = {
        "flow_strategy": flow_strategy,
        "distribution_channel": distribution_channel,
        "long_distance_freight_warning": long_distance_freight_warning,
        "field_validation_checklist": [
            "Devis fret réel (surtout sur corridor inter-provinces longue distance)",
            "Taxes communales / ticket de place",
            "Vitesse d'écoulement en sacs/semaine auprès de 5 acheteurs",
            "Coût de gardiennage / magasinage",
            "Prix d'achat ferme bord-champ ou gros",
        ],
    }

    return {
        "commodity": commodity,
        "commodity_fr": commodity_fr,
        "origin_province": origin_province,
        "dest_province": dest_province,
        "cycles_per_month": cycles,
        "certified_market_metrics": {
            "buy_price_per_kg": round(buy_p, 1),
            "sell_price_per_kg": eff_sell_price if not is_simulated_sell_price else None,
            "predicted_t1_sell_price_per_kg": round(float(predicted_t1_sell_price_per_kg), 1)
            if predicted_t1_sell_price_per_kg is not None
            else None,
            "volatility_cv_pct": round(float(volatility_cv_pct), 1) if volatility_cv_pct is not None else None,
            "credit_score": round(float(credit_score), 1) if credit_score is not None else None,
        },
        "capital_allocation": capital_allocation,
        "unit_economics": unit_economics,
        "projection_6_months": projection_6_months,
        "stress_tests": stress_tests,
        "verdict": verdict,
        "price_basis": basis,
        "commercial_strategy": commercial_strategy,
        "user_instructions": list(user_instructions or []),
    }


def _xaf(value: float | int) -> str:
    """Montant entier avec espace comme séparateur de milliers (format français)."""
    return f"{int(round(value)):,}".replace(",", " ")


def _signed_xaf(value: float | int) -> str:
    return f"{int(round(value)):+,}".replace(",", " ")


def _volatility_label(cv: Optional[float]) -> str:
    if cv is None:
        return "non disponible"
    if cv < 10.0:
        return f"{cv:.1f} % — faible"
    if cv < 20.0:
        return f"{cv:.1f} % — modérée"
    return f"{cv:.1f} % — élevée"


_VERDICT_ICON = {"green": "🟢", "amber": "🟠", "red": "🔴"}


def format_business_plan_markdown(bp: dict) -> str:
    """Rendu Markdown professionnel du modèle financier (synthèse, hypothèses, projections, risques, décision)."""
    ca = bp["capital_allocation"]
    ue = bp["unit_economics"]
    cs = bp.get("commercial_strategy") or {}
    cm = bp.get("certified_market_metrics") or {}
    basis = bp.get("price_basis") or DEFAULT_PRICE_BASIS
    verdict = bp.get("verdict") or {"level": "amber", "label": ue.get("profitability_status", ""), "summary": ""}
    route = (
        f"{bp['origin_province']} → {bp['dest_province']}"
        if bp.get("dest_province")
        else f"{bp['origin_province']} (marché local / simulation)"
    )
    simulated = ue["is_simulated_sell_price"]
    sell_value = ue["target_sell_price_per_kg"] if simulated else ue["sell_price_per_kg"]
    sell_label = f"{sell_value} XAF/kg" + (" *(cible simulée : point mort + 15 %)*" if simulated else "")
    wc_pct = f"{ca.get('working_capital_share_pct', 80.0):.0f} %"
    capex_pct = f"{ca.get('capex_share_pct', 8.0):.0f} %"
    res_pct = f"{ca.get('safety_share_pct', 12.0):.0f} %"
    payback = ue.get("payback_month")
    safety = ue.get("safety_margin_pct")

    lines = [
        f"### Business Plan Financier — {bp['commodity_fr']} ({route})",
        "",
        f"> {_VERDICT_ICON.get(verdict['level'], '')} **Verdict : {verdict['label']}**  ",
        f"> {verdict.get('summary', '')}",
        "",
        "#### 1. Synthèse exécutive",
        "",
        "| Indicateur | Valeur |",
        "| :--- | ---: |",
        f"| Capital engagé | {_xaf(ca['total_capital_xaf'])} XAF |",
        f"| Volume acheté (cycle 1) | {_xaf(ue['volume_bought_kg'])} kg ({ue['volume_bought_bags_100kg']} sacs de 100 kg) |",
        f"| Prix d'achat → prix de vente retenus | {ue['buy_price_per_kg']} → {sell_value} XAF/kg |",
        f"| Point mort (prix de vente minimal) | {ue['break_even_price_per_kg']} XAF/kg ({_xaf(ue['break_even_bag_100kg_xaf'])} XAF/sac) |",
        f"| Marge de sécurité sur le point mort | {safety:+.1f} % |" if safety is not None else "| Marge de sécurité sur le point mort | n/d |",
        f"| Résultat net — cycle 1 | **{_signed_xaf(ue['net_profit_cycle1_xaf'])} XAF** (ROI {ue['roi_cycle1_pct']:+.1f} %) |",
        f"| Retour sur capital (bénéfices cumulés ≥ capital) | {'mois ' + str(payback) if payback else 'au-delà de 6 mois'} |",
    ]

    if ue.get("profitability_status") == "NON RENTABLE À CETTE ÉCHELLE":
        min_cap = ue.get("min_theoretical_capital_xaf")
        if min_cap is not None and min_cap > 0:
            lines += ["", f"**Capital minimum théorique** pour absorber {_xaf(ue['monthly_fixed_costs_xaf'])} XAF de charges fixes : **{_xaf(min_cap)} XAF**."]
        else:
            lines += ["", "**Corridor structurellement déficitaire** à ces prix (marge unitaire ≤ 0) : aucun capital ne le rend rentable."]

    lines += [
        "",
        "#### 2. Hypothèses et provenance des chiffres",
        "",
        "| Paramètre | Valeur | Origine |",
        "| :--- | ---: | :--- |",
        f"| Prix d'achat | {ue['buy_price_per_kg']} XAF/kg | Données FreeData.AI — {basis['buy']} |",
        f"| Prix de vente | {sell_value} XAF/kg | "
        + ("Hypothèse de calcul (aucun prix de destination disponible)" if simulated else f"Données FreeData.AI — {basis['sell']}")
        + " |",
        f"| Fret | {ue['transport_cost_per_kg']} XAF/kg | Hypothèse à confirmer par devis transporteur |",
        f"| Sacherie | {ue['packaging_cost_per_kg']} XAF/kg | Hypothèse (500 XAF par sac de 100 kg) |",
        f"| Pertes techniques | {ue['loss_rate_pct']} % | Hypothèse standard à ajuster |",
        f"| Charges fixes mensuelles | {_xaf(ue['monthly_fixed_costs_xaf'])} XAF | Hypothèse à ajuster |",
        f"| Volatilité des prix (CV) | {_volatility_label(cm.get('volatility_cv_pct'))} | Données FreeData.AI |",
        f"| Score Credit Passport | {cm['credit_score']:.0f} / 100 | Données FreeData.AI |"
        if cm.get("credit_score") is not None
        else "| Score Credit Passport | non disponible | — |",
    ]
    if ue.get("sell_price_capped"):
        lines.append(
            f"\n*Prix de vente plafonné à {ue['sell_price_per_kg']} XAF/kg (plus haut prix réellement constaté à destination) ; "
            f"prix initialement envisagé : {ue['requested_sell_price_per_kg']} XAF/kg.*"
        )

    lines += [
        "",
        "#### 3. Allocation du capital",
        "",
        "| Poste | Montant (XAF) | Part |",
        "| :--- | ---: | ---: |",
        f"| BFR opérationnel (stock + fret + sacherie) | {_xaf(ca['working_capital_xaf'])} | {wc_pct} |",
        f"| CAPEX équipement (balance, bâches, palettes) | {_xaf(ca['capex_equipment_xaf'])} | {capex_pct} |",
        f"| Réserve de trésorerie (jamais investie en stock) | {_xaf(ca['safety_cash_reserve_xaf'])} | {res_pct} |",
        f"| **Total** | **{_xaf(ca['total_capital_xaf'])}** | **100 %** |",
        "",
        "#### 4. Économie unitaire (par kg acheté)",
        "",
        "| Élément | XAF/kg |",
        "| :--- | ---: |",
        f"| Prix d'achat | {ue['buy_price_per_kg']} |",
        f"| + Fret | {ue['transport_cost_per_kg']} |",
        f"| + Sacherie | {ue['packaging_cost_per_kg']} |",
        f"| **= Coût de revient rendu** | **{ue['unit_landed_cost']}** |",
        f"| Recette nette de pertes ({ue['loss_rate_pct']} %) | {round(sell_value * (1 - ue['loss_rate_pct'] / 100.0), 1)} |",
        f"| **Marge unitaire** | **{ue['unit_margin_per_bought_kg']:+}** |",
        "",
        "#### 5. Projection sur 6 mois",
        "",
        f"*{('Réinvestissement de ' + format(ue.get('reinvest_rate_pct', 75.0), '.0f') + ' % du bénéfice net dans le BFR') if ue.get('reinvest_enabled', True) else 'Sans réinvestissement (BFR constant M1-M6)'}.*",
        "",
        "| Mois | BFR (XAF) | Chiffre d'affaires | Coûts totaux | Résultat net | Trésorerie cumulée |",
        "| :---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in bp["projection_6_months"]:
        lines.append(
            f"| M{row['month']} | {_xaf(row['working_capital'])} | {_xaf(row['revenue'])} | {_xaf(row['total_costs'])} "
            f"| {_signed_xaf(row['net_profit'])} | {_xaf(row['cumulative_cash'])} |"
        )

    lines += [
        "",
        "#### 6. Tests de résistance (cycle 1)",
        "",
        "| Scénario | Hypothèse | Résultat net (XAF) | ROI | Viable |",
        "| :--- | :--- | ---: | ---: | :---: |",
    ]
    for st in bp["stress_tests"]:
        lines.append(
            f"| {st['scenario']} | {st['assumption']} | {_signed_xaf(st['net_profit_xaf'])} | {st['roi_pct']:+.1f} % | {'✔' if st['viable'] else '✘'} |"
        )

    risks: list[str] = []
    if safety is not None and safety < 10.0:
        risks.append(f"Marge de sécurité faible ({safety:+.1f} %) : une baisse de prix modeste efface le bénéfice.")
    cv = cm.get("volatility_cv_pct")
    if cv is not None and cv >= 20.0:
        risks.append(f"Volatilité élevée du produit (CV {cv:.1f} %) : privilégier une rotation rapide et des achats fractionnés.")
    if cs.get("long_distance_freight_warning"):
        risks.append("Fret inter-provinces au tarif par défaut (25 XAF/kg) : à remplacer par un devis réel avant décaissement.")
    if ue.get("is_simulated_sell_price"):
        risks.append("Prix de vente simulé (aucune donnée de destination) : les résultats sont indicatifs.")
    if ue.get("sell_price_capped"):
        risks.append("Prix de vente plafonné au plus haut prix constaté à destination : ne pas compter sur un prix supérieur.")
    if not risks:
        risks.append("Aucun signal de risque majeur détecté dans les données disponibles ; les hypothèses restent à valider sur le terrain.")
    lines += ["", "#### 7. Risques identifiés", ""] + [f"- {r}" for r in risks]

    if cs:
        lines += [
            "",
            "#### 8. Stratégie commerciale et validation terrain",
            "",
            f"- **Écoulement** : {cs.get('flow_strategy', '')}",
            f"- **Canal de distribution** : {cs.get('distribution_channel', '')}",
            "- **À vérifier avant tout décaissement (24-48 h)** :",
        ]
        for idx, item in enumerate(cs.get("field_validation_checklist", []), 1):
            lines.append(f"  {idx}. {item}")

    lines += [
        "",
        "---",
        "*Les prix et la volatilité proviennent de FreeData.AI (prévisions statistiques, non garanties). Fret, sacherie, pertes et charges "
        "fixes sont des hypothèses standards à remplacer par vos devis locaux. Ce document est une aide à la décision, pas un conseil financier.*",
    ]
    return "\n".join(lines)
