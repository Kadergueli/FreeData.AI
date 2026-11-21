"""Profil de site agro : sol SoilGrids + climat NASA POWER pour les 12 pôles, moteur FAO inactif sans besoins licenciés."""
import pytest

from src import agro_site as site
from src.agro_indicators import HUBS


@pytest.mark.parametrize("hub", HUBS)
def test_every_hub_has_soil_and_climate_with_provenance(hub):
    p = site.site_profile(hub)
    assert p and p["soil"] and p["climate"]
    assert 4.0 < p["soil"]["ph"] < 9.0 and p["soil"]["provenance"]["license"] == "CC BY 4.0"
    assert "NASA" in p["climate"]["provenance"]["source"]
    assert len(p["climate"]["monthly_rain_mm"]) == 12 and len(p["climate"]["monthly_temp_c"]) == 12


def test_accents_and_unknown_places():
    assert site.site_profile("Abéché (Ouaddaï)")["hub"] == "Abeche"
    assert site.site_profile("Paris") is None and site.site_profile("national") is None


def test_rainy_season_sahel_vs_desert():
    rain = {m: 0.0 for m in site.MONTHS}
    temp = {m: 30.0 for m in site.MONTHS}
    assert site.rainy_season(rain, temp)["season_days"] == 0  # désert : saison vide
    rain.update(JUL=4.0, AUG=6.0, SEP=3.0)
    s = site.rainy_season(rain, temp)
    assert s["wet_months"] == ["JUL", "AUG", "SEP"] and s["season_days"] == 92 and s["rain_mm"] == 400.0


def test_engine_is_inactive_without_licensed_requirements():
    assert site.engine_available() is False  # EcoCrop non livré : conditions FAO à confirmer par écrit


CROP = {"rain_mm": [200, 400, 900, 1700], "temp_mean_c": [12, 25, 35, 40], "ph": [4.5, 5, 6.5, 8.3], "cycle_days": [60, 120]}


def test_assessment_with_synthetic_requirements():
    p = site.site_profile("Sarh")
    r = site.assess_crop(CROP, p)
    assert r["score"] is not None and r["verdict"] in ("very_suitable", "suitable", "marginal", "unsuitable")
    assert r["limiting"] in ("rain_mm", "temp_mean_c", "season_days")
    cal = site.sowing_calendar(CROP, p)
    assert len(cal) == 12 and {c["month"] for c in cal} == set(range(1, 13))


def test_assessment_never_guesses_missing_data():
    r = site.assess_crop(CROP, {"soil": None, "climate": None})
    assert r["score"] is None and r["verdict"] == "unknown" and "ph" in r["unknown"]
    assert site.sowing_calendar(CROP, {"climate": None}) is None


def test_trapezoid_shape():
    assert site.trapezoid(300, 200, 400, 900, 1700) == 0.5 and site.trapezoid(500, 200, 400, 900, 1700) == 1.0
    assert site.trapezoid(100, 200, 400, 900, 1700) == 0.0


def test_zone_profile_endpoint_exposes_site_profile():
    from api import server

    class _Store:
        def regional_rows(self, hub):
            return [{"indicator": "Root zone soil wetness", "value": 0.5, "unit": "index", "reference_date": f"2026-0{m}-01",
                     "region": hub, "source": "NASA POWER Agro", "license": "Public Domain",
                     "spatial_resolution": "regional_city_hub", "confidence_level": "Satellite_Modeled_Regional"}
                    for m in range(1, 7)]

        def national_rows(self):
            return []

    out = server.agro_zone_profile_endpoint(region="Sarh", store=_Store())
    sp = out["site_profile"]
    assert sp["hub"] == "Sarh" and sp["soil"]["provenance"]["license"] == "CC BY 4.0" and sp["climate"]["rainy_season"]["rain_mm"] > 900
