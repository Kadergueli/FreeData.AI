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


# ── Convergence avec le moteur Agronome PRO : le sol réel de la zone nourrit l'analyse ───────────────────────────

def _nasa_rows(hub="Moundou (Logone Occidental)"):
    rows = []
    for y in (2020, 2021, 2022, 2023, 2026):
        for m, v in ((6, 0.5), (7, 0.55), (8, 0.6)):
            rows.append({"indicator": "Root zone soil wetness index", "value": v, "unit": "ratio (0-1)",
                         "reference_date": f"{y}-{m:02d}-01", "region": "Moundou", "source": "NASA POWER Agro",
                         "license": "Public Domain (U.S. Government / NASA)", "spatial_resolution": "regional_city_hub",
                         "confidence_level": "Satellite_Modeled_Regional"})
    return rows


def _assess(lab=None):
    from src.agro_engine import evaluate_field_assessment
    return evaluate_field_assessment(region="Moundou", regional_rows=_nasa_rows(), national_rows=[], lab_soil_inputs=lab,
                                     target_crops=["millet", "maize"], today=__import__("datetime").date(2026, 8, 1))


@pytest.mark.parametrize("clay,sand,usda", [(5, 90, "sand"), (15, 60, "sandy loam"), (20, 40, "loam"),
                                            (50, 20, "clay"), (30, 30, "clay loam"), (10, 15, "silt loam")])
def test_usda_texture(clay, sand, usda):
    assert site.usda_texture(clay, sand) == usda


def test_zonal_soil_estimate_uses_real_soilgrids_values():
    z = site.zonal_soil_estimate("Moundou")
    assert z["ph"] == 6.08 and z["texture"] and z["provenance"]["license"] == "CC BY 4.0"
    assert z["organic_matter_pct"] == pytest.approx(z["organic_matter_pct"]) and z["organic_matter_pct"] > 0
    assert site.zonal_soil_estimate("Paris") is None


def test_without_lab_analysis_uses_zonal_soil_but_stays_zone_only():
    a = _assess()
    assert a["has_lab_measurements"] is False and a["soil_basis"] == "soilgrids_zonal"
    assert "DIAGNOSTIC DE TERRAIN" not in a["title"].upper() and "PRÉ-DIAGNOSTIC" in a["title"].upper()
    for c in a["crop_assessments"]:
        assert c["soil_score"] <= 22.0  # plafond : une estimation de zone n'égale pas une mesure
        assert any("SoilGrids" in str(x.get("factor", "")) for x in c["criteria"])
    ph_row = next(r for r in a["bulletin"]["lab_parameters"] if "pH" in r["parameter"])
    assert "SoilGrids" in ph_row["value"] and ph_row["source"].startswith("SoilGrids")


def test_lab_measurements_override_zonal_and_are_cross_checked():
    a = _assess({"ph": 4.6, "texture": "sandy", "organic_matter": 1.0})
    assert a["has_lab_measurements"] is True and a["soil_basis"] == "lab"
    cc = a["soil_cross_check"]
    assert cc["zonal_ph"] == 6.08 and cc["ph_gap"] == pytest.approx(4.6 - 6.08, abs=0.01)
    assert cc["ph_gap"] < -1.0 and cc["source"].startswith("SoilGrids")
    assert all("labo" in str(x.get("factor", "")) or "SoilGrids" not in str(x.get("factor", "")) for c in a["crop_assessments"] for x in c["criteria"])


def test_zonal_soil_changes_the_score_for_unfavourable_ph(monkeypatch):
    base = _assess()
    monkeypatch.setattr("src.agro_engine.zonal_soil_estimate", lambda hub: {
        "hub": hub, "ph": 4.0, "texture": "clay", "texture_usda": "clay", "clay_pct": 60, "sand_pct": 10,
        "organic_matter_pct": 0.5, "provenance": site.SOIL_PROVENANCE})
    worse = _assess()
    b = {c["crop_id"]: c["soil_score"] for c in base["crop_assessments"]}
    w = {c["crop_id"]: c["soil_score"] for c in worse["crop_assessments"]}
    assert all(w[k] <= b[k] for k in b) and any(w[k] < b[k] for k in b)


def test_aberrant_lab_values_do_not_unlock_certified_title():
    from src import agro_engine as ae

    for lab in ({"ph": 99}, {"ph": "abc"}, {"ph": -4, "organic_matter": 500}, {"texture": "foo"}):
        r = ae.evaluate_field_assessment(
            region="Moundou", regional_rows=[], national_rows=[], target_crops=["maize"], area_hectares=2, lab_soil_inputs=lab
        )
        assert r["has_lab_measurements"] is False
        assert r["soil_basis"] != "lab"
        assert "CERTIFIÉ" not in r["resolution_label"]
    ok = ae.evaluate_field_assessment(
        region="Moundou", regional_rows=[], national_rows=[], target_crops=["maize"], area_hectares=2,
        lab_soil_inputs={"ph": "6,5", "texture": "Sandy Loam"},
    )
    assert ok["has_lab_measurements"] is True and ok["soil_basis"] == "lab"
