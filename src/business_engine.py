"""Moteur déterministe de Business Plan professionnel (CAPEX, BFR, 6 mois, Point mort, Stress-tests)."""
from __future__ import annotations

import math
from typing import Optional

# Source unique de vérité pour l'allocation du capital (spécification officielle 80 / 8 / 12)
WORKING_CAPITAL_SHARE = 0.80
CAPEX_SHARE = 0.08
RESERVE_SHARE = 0.12


def allocate_capital(total_capital: float) -> dict:
    """
    Ventile le capital selon la règle officielle 80 / 8 / 12 :
    - 80 % BFR opérationnel (achat de stock + transport + sacherie)
    - 8 % CAPEX équipement (balance, bâches, palettes ; reste disponible s'il n'est pas requis)
    - 12 % Réserve de liquidités d'urgence (jamais incluse dans le budget d'achat de stock)
    """
    total = float(total_capital)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("Le capital total doit être strictement positif.")
    total_r = round(total, 2)
    capex_budget = round(total_r * CAPEX_SHARE, 2)
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
        "working_capital_share_pct": WORKING_CAPITAL_SHARE * 100.0,
        "capex_equipment_xaf": capex_budget,
        "capex_share_pct": CAPEX_SHARE * 100.0,
        "safety_cash_reserve_xaf": reserve_budget,
        "safety_share_pct": RESERVE_SHARE * 100.0,
        "remaining_liquidity_xaf": reserve_budget,
        "capex_note": "Budget équipement alloué (8 %) : balance, bâches, palettes ; peut rester inutilisé si non requis.",
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
) -> dict:
    """Construit un modèle financier complet et déterministe pour un business plan bancable."""
    cap = max(float(capital_xaf), 1.0)
    buy_p = max(float(buy_price_per_kg), 1.0)
    transport_p = max(float(transport_cost_per_kg), 0.0)
    loss_pct = min(max(float(loss_rate_pct), 0.0), 50.0)
    fixed_xaf = max(float(monthly_fixed_costs_xaf), 0.0)
    cycles = max(float(cycles_per_month), 0.25)

    # 1. Allocation du capital initial (source unique 80 / 8 / 12)
    capital_allocation = allocate_capital(cap)
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

    is_simulated_sell_price = sell_price_per_kg is None
    eff_sell_price = (
        round(float(sell_price_per_kg), 1)
        if sell_price_per_kg is not None
        else round(break_even_price_per_kg * 1.15, 1)
    )

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
        "sell_price_per_kg": round(float(sell_price_per_kg), 1) if sell_price_per_kg is not None else None,
        "target_sell_price_per_kg": eff_sell_price if is_simulated_sell_price else None,
        "is_simulated_sell_price": is_simulated_sell_price,
        "gross_revenue_xaf": gross_revenue_xaf,
        "total_variable_cost_xaf": total_variable_cost_xaf,
        "gross_margin_xaf": gross_margin_xaf,
        "net_profit_cycle1_xaf": net_profit_cycle1_xaf,
        "roi_cycle1_pct": roi_cycle1_pct,
    }

    # 3. Projection financière sur 6 mois (70 % du bénéfice réinvesti dans le BFR, plafonné à 3x capital initial)
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
        if net > 0:
            reinvested = min(net * 0.70, max(0.0, max_working_capital - wc))
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

    return {
        "commodity": commodity,
        "commodity_fr": commodity_fr,
        "origin_province": origin_province,
        "dest_province": dest_province,
        "cycles_per_month": cycles,
        "certified_market_metrics": {
            "buy_price_per_kg": round(buy_p, 1),
            "sell_price_per_kg": round(float(sell_price_per_kg), 1) if sell_price_per_kg is not None else None,
            "volatility_cv_pct": round(float(volatility_cv_pct), 1) if volatility_cv_pct is not None else None,
            "credit_score": round(float(credit_score), 1) if credit_score is not None else None,
        },
        "capital_allocation": capital_allocation,
        "unit_economics": unit_economics,
        "projection_6_months": projection_6_months,
        "stress_tests": stress_tests,
        "user_instructions": list(user_instructions or []),
    }


def format_business_plan_markdown(bp: dict) -> str:
    """Rendu Markdown structuré du modèle financier pour le mode gratuit ou repli LLM."""
    ca = bp["capital_allocation"]
    ue = bp["unit_economics"]
    route = (
        f"{bp['origin_province']} -> {bp['dest_province']}"
        if bp.get("dest_province")
        else f"{bp['origin_province']} (marché local / simulation)"
    )
    sell_label = (
        f"{ue['target_sell_price_per_kg']} XAF/kg *(cible simulée +15 % sur point mort)*"
        if ue["is_simulated_sell_price"]
        else f"{ue['sell_price_per_kg']} XAF/kg"
    )
    lines = [
        f"### Business Plan Financier — {bp['commodity_fr']} ({route})",
        "",
        f"- **Capital engagé** : {ca['total_capital_xaf']:,} XAF | **Résultat net Cycle 1** : {ue['net_profit_cycle1_xaf']:+,} XAF (**ROI {ue['roi_cycle1_pct']:+.1f}%**)".replace(",", " "),
        f"- **Volume acheté** : {ue['volume_bought_kg']:,} kg ({ue['volume_bought_bags_100kg']} sacs de 100 kg) | **Point mort** : {ue['break_even_price_per_kg']} XAF/kg ({ue['break_even_bag_100kg_xaf']:,} XAF/sac)".replace(",", " "),
        f"- **Prix de vente retenu** : {sell_label}",
        "",
        "| Poste de capital | Montant (XAF) | Part |",
        "| :--- | ---: | ---: |",
        f"| BFR opérationnel (stock + fret + sacherie) | {ca['working_capital_xaf']:,} | 80 % |".replace(",", " "),
        f"| CAPEX équipement (balance, bâches, palettes) | {ca['capex_equipment_xaf']:,} | 8 % |".replace(",", " "),
        f"| Réserve de trésorerie (sécurité) | {ca['safety_cash_reserve_xaf']:,} | 12 % |".replace(",", " "),
        "",
        "| Mois | BFR (XAF) | Chiffre d'affaires | Coûts totaux | Résultat net | Trésorerie cumulée |",
        "| :---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in bp["projection_6_months"]:
        lines.append(
            f"| M{row['month']} | {row['working_capital']:,} | {row['revenue']:,} | {row['total_costs']:,} | {row['net_profit']:+,} | {row['cumulative_cash']:,} |".replace(",", " ")
        )
    lines += ["", "| Scénario de résistance (Cycle 1) | Hypothèse | Résultat net (XAF) | ROI |", "| :--- | :--- | ---: | ---: |"]
    for st in bp["stress_tests"]:
        lines.append(
            f"| {st['scenario']} | {st['assumption']} | {st['net_profit_xaf']:+,} | {st['roi_pct']:+.1f}% |".replace(",", " ")
        )
    lines.append("")
    lines.append(
        "*Note : Prix observés/prévus, volatilité (CV %) et score Credit Passport proviennent de FreeData.AI ; "
        "CAPEX 8 %, sacherie 5 XAF/kg, pertes 5 % et charges fixes 35 000 XAF/mois sont des hypothèses standards à ajuster selon vos devis locaux.*"
    )
    return "\n".join(lines)

