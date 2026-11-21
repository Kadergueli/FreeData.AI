"""Point-level satellite climate retrieval for field assessments.

NASA POWER climatology is used only when parcel coordinates are supplied.
Unavailable parameters remain None; this module never substitutes synthetic values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
NASA_POWER_PARAMETERS = ("GWETROOT", "GWETTOP", "PRECTOTCORR", "T2M")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def fetch_nasa_power_point(
    latitude: Optional[float],
    longitude: Optional[float],
    *,
    timeout: float = 12.0,
    http_get: Any = requests.get,
) -> Optional[dict[str, Any]]:
    """Fetch point climatology for a parcel. Returns None on provider failure."""
    if latitude is None or longitude is None:
        return None
    lat, lon = float(latitude), float(longitude)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordonnées GPS hors limites.")

    try:
        response = http_get(
            NASA_POWER_URL,
            params={
                "parameters": ",".join(NASA_POWER_PARAMETERS),
                "community": "HY",
                "longitude": lon,
                "latitude": lat,
                "format": "JSON",
            },
            headers={"User-Agent": "FreeData.AI/1.0 (agricultural decision support; https://github.com/Kadergueli/FreeData.AI)"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        properties = payload.get("properties") or {}
        parameter_data = properties.get("parameter") or {}
        if not isinstance(parameter_data, dict):
            return None
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None

    def monthly_values(key: str) -> dict[str, float]:
        raw = parameter_data.get(key) or {}
        values: dict[str, float] = {}
        if isinstance(raw, dict):
            for month in MONTHS:
                value = raw.get(month)
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number > -900:
                    values[month] = number
        return values

    monthly = {key: monthly_values(key) for key in NASA_POWER_PARAMETERS}
    growing_months = ("JUN", "JUL", "AUG", "SEP")

    def mean_months(key: str) -> Optional[float]:
        values = [monthly[key][m] for m in growing_months if m in monthly[key]]
        return round(sum(values) / len(values), 4) if values else None

    if not any(monthly.values()):
        return None

    header = payload.get("header") or {}
    return {
        "source": "NASA POWER",
        "service": "Temporal Climatology Point API",
        "community": "HY",
        "latitude": lat,
        "longitude": lon,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_period": header.get("time") or header.get("start") or "Climatologie fournisseur (période à confirmer)",
        "spatial_resolution": "Point POWER — résolution native variable selon paramètre; voir métadonnées fournisseur",
        "monthly_values": monthly,
        "growing_season": {
            "months": list(growing_months),
            "root_zone_wetness_mean": mean_months("GWETROOT"),
            "surface_wetness_mean": mean_months("GWETTOP"),
            "precipitation_mean": mean_months("PRECTOTCORR"),
            "temperature_mean_c": mean_months("T2M"),
        },
        "parameter_metadata": {
            "GWETROOT": {"label": "Humidité de la zone racinaire", "unit": "fraction (0–1)"},
            "GWETTOP": {"label": "Humidité de surface", "unit": "fraction (0–1)"},
            "PRECTOTCORR": {"label": "Précipitations corrigées", "unit": "mm/jour (moyenne climatologique, à confirmer par métadonnées API)"},
            "T2M": {"label": "Température de l'air à 2 m", "unit": "°C"},
        },
        "provenance": {
            "source": "NASA POWER",
            "service": "Temporal Climatology Point API",
            "community": "HY",
            "license": "NASA POWER — aucune restriction générale d'usage indiquée par NASA; citation requise",
            "attribution": "NASA Prediction of Worldwide Energy Resources (POWER), https://power.larc.nasa.gov/",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_period": header.get("time") or "Climatologie fournisseur; période exacte non exposée dans la réponse",
            "coordinates": {"latitude": lat, "longitude": lon},
            "resolution": "Résolution native propre à chaque paramètre; ne pas assimiler au contour exact de la parcelle",
        },
    }
