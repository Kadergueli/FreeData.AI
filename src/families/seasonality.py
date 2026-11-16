"""Famille A — calendrier saisonnier (quand acheter, stocker, vendre).

Calcul hors ligne : src/seasonality.py, src/season_study.py, scripts/update_seasonality.py
Stockage : table_ml_seasonality_studies. Cette famille ne fait que la partie « chat ».
"""
from __future__ import annotations

import re

from src.families.base import FamilySpec
from src.seasonality import MONTHS_FR as _MONTHS_FR

PATTERN = re.compile(
    r"\b(?:quand|quel\s+mois|quels\s+mois|meilleur(?:e|s)?\s+mois|bons?\s+mois|quelle\s+periode|quelles\s+periodes|meilleur\s+moment|meilleure\s+periode|"
    r"bon\s+moment|saison(?:s|nier|niere|nalite)?|soudure|periode\s+de\s+soudure|destock(?:er|age)?|stock(?:er|age)?)\b"
    r".*\b(?:acheter|achat|vendre|vente|stocker|stockage|destocker|destockage|prix|cher|bas|haut|monte|baisse)\b"
    r"|\b(?:saisonnalite|saisonnier|saisonniere|calendrier\s+(?:d[\s']?achat|des?\s+prix)|periode\s+de\s+soudure|soudure)\b"
)


def format_timing(data: dict) -> str:
    comm = data.get("commodity_fr") or data.get("commodity") or "ce produit"
    if data.get("status") != "ok":
        return (
            f"Je n'ai pas assez d'historique pour dégager une saisonnalité fiable du {comm}. "
            "Je préfère ne pas vous donner de calendrier d'achat qui reposerait sur trop peu de données."
        )
    names = lambda months: " et ".join(_MONTHS_FR[m - 1] for m in sorted(months))
    scope = data.get("scope_province")
    req = data.get("requested_province")
    where = f"à {scope}" if scope else "au niveau national (toutes provinces suivies)"
    lines = [f"**Saisonnalité du {comm} {where}** (historique observé, écarts par rapport à la moyenne annuelle) :"]
    if req and not scope:
        lines.append(f"- Pas assez de données propres à {req} : j'utilise la tendance nationale.")
    lines += [
        f"- Prix les plus bas : **{names(data['buy_months'])}** (environ {data['buy_discount_pct']:+.0f} %) → période favorable à l'achat/stockage.",
        f"- Prix les plus hauts : **{names(data['sell_months'])}** (environ {data['sell_premium_pct']:+.0f} %) → période favorable à la vente/déstockage.",
        f"- Écart entre le creux et le pic : environ {data['amplitude_pct']:.0f} %.",
    ]
    if data.get("reliable"):
        lines.append("- Ce schéma se répète d'une année à l'autre : il est jugé **fiable**.")
    elif data.get("min_years_observed", 3) < 3:
        lines.append(f"- ⚠️ Historique trop court pour **confirmer** ce schéma (chaque mois n'a été vu que sur "
                     f"{data.get('min_years_observed', 0)} année(s)) : c'est une indication, pas une règle.")
    else:
        lines.append("- ⚠️ Ce schéma est **peu régulier** d'une année à l'autre : prenez-le comme une indication, pas comme une règle.")
    lines.append("Ce calendrier décrit des tendances passées moyennes ; il ne garantit pas le prix d'une année donnée. "
                 "Il ne tient pas compte de vos coûts de stockage et de pertes.")
    return "\n".join(lines)


def run(agent, entities: dict) -> tuple[str, dict]:
    raw = agent.provider.get_seasonal_calendar(entities["province"], entities["commodity"] or "Millet")
    return format_timing(raw), raw


def intro(entities: dict, what: str, where: str) -> str:
    return f"Voici le calendrier saisonnier des prix{what}{where}, utile pour choisir quand acheter, stocker ou vendre."


def clarify(agent, entities: dict, has_history: bool):
    if entities.get("commodity") or has_history:
        return None
    prods = ", ".join(agent.provider.tracked_commodities_fr(8))
    return ("Pour vous indiquer les bons mois d'achat, de stockage ou de vente, il me faut le **produit** concerné"
            + (f" ({prods}…)" if prods else "") + ". Lequel vous intéresse, et dans quelle province ?")


SPEC = FamilySpec(
    name="seasonality",
    label="Famille A — Saisonnalité",
    intent="timing",
    pattern=PATTERN,
    router_hint="timing: QUAND acheter, vendre ou stocker (saison, soudure, meilleur mois)",
    run=run,
    intro=intro,
    clarify=clarify,
    gold_tables=("table_ml_seasonality_studies",),
    offline_script="scripts/update_seasonality.py",
)
