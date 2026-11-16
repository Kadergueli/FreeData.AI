"""Registre des familles : le chat les interroge sans connaître leur contenu."""
from __future__ import annotations

from typing import Optional

from src.families.base import FamilySpec

_FAMILIES: dict[str, FamilySpec] = {}


def register(spec: FamilySpec) -> FamilySpec:
    if spec.name in _FAMILIES:
        raise ValueError(f"Famille déjà enregistrée : {spec.name}")
    if any(f.intent == spec.intent for f in _FAMILIES.values()):
        raise ValueError(f"Intention déjà prise : {spec.intent}")
    _FAMILIES[spec.name] = spec
    return spec


def families() -> list[FamilySpec]:
    return list(_FAMILIES.values())


def by_intent(intent: Optional[str]) -> Optional[FamilySpec]:
    return next((f for f in _FAMILIES.values() if f.intent == intent), None)


def detect(q_norm: str, *, has_route: bool = False) -> Optional[FamilySpec]:
    """Première famille dont le motif correspond (ordre d'enregistrement)."""
    for f in _FAMILIES.values():
        if f.pattern.search(q_norm) and not (has_route and f.yields_to_route):
            return f
    return None
