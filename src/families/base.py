"""Contrat commun des « familles » d'analyses (prévision/saisonnalité, anomalies, ...).

Une famille est un module autonome qui sait :
  - **reconnaître** une question dans le chat (`pattern`, `intent`) ;
  - **calculer** la réponse à partir des données (`run`) et la présenter (`intro`) ;
  - **demander** une précision quand il manque un produit, etc. (`clarify`) ;
  - décrire sa partie **hors ligne** (`gold_tables`, `offline_script`) pour la documentation et les contrôles.

Le cœur du chat (src/ai_agent.py) ne connaît que ce contrat : ajouter une famille = écrire un module
dans src/families/ et l'enregistrer dans src/families/__init__.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover
    from src.ai_agent import FreeDataAIAgent

# run(agent, entities) -> (faits formatés en Markdown, données brutes du fournisseur)
RunFn = Callable[["FreeDataAIAgent", dict], "tuple[str, dict]"]
# intro(entities, what, where) -> phrase d'introduction ; what/where : fragments déjà formatés (« du mil », « à Lac »)
IntroFn = Callable[[dict, str, str], str]
# clarify(agent, entities, has_history) -> message de précision, ou None si la question est assez précise
ClarifyFn = Callable[["FreeDataAIAgent", dict, bool], Optional[str]]


@dataclass(frozen=True)
class FamilySpec:
    name: str                      # identifiant technique, ex. "seasonality"
    label: str                     # nom lisible, ex. "Famille A — Saisonnalité"
    intent: str                    # intention de chat gérée, ex. "timing"
    pattern: re.Pattern            # détection sur le texte normalisé (minuscules, sans accents)
    router_hint: str               # une ligne décrivant l'intention pour le routeur LLM
    run: RunFn
    intro: IntroFn
    clarify: Optional[ClarifyFn] = None
    yields_to_route: bool = True   # une question « A → B » est traitée comme un trajet, pas par cette famille
    gold_tables: tuple[str, ...] = ()   # tables Supabase alimentées hors ligne
    offline_script: Optional[str] = None  # script qui les calcule
