"""Familles d'analyses branchées sur le chat. Pour en ajouter une : créer le module puis l'enregistrer ici."""
from src.families.registry import by_intent, detect, families, register  # noqa: F401
from src.families import seasonality as _seasonality

register(_seasonality.SPEC)
