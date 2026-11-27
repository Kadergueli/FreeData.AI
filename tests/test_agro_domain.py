"""Domaine Agriculture : ingestion stricte du CSV commercial, moteur d'anomalies et endpoints publics."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.agro_engine import (
    MODERATE_DEFICIT_PCT,
    build_zone_profile,
    compute_monthly_anomalies,
    deficit_level,
)
from src.agro_indicators import (
    AgroIndicatorStore,
    AgroIngestError,
    canonical_region,
    parse_region,
    validate_agro_dataframe,
    regional_indicator_key,
)
from src.domains import DomainRegistry

REAL_CSV = Path(__file__).resolve().parent.parent / "freedatatd-agriculture-commercial-clean.csv"


def _nasa_row(i=1, indicator="Root zone soil wetness index", value=0.4, region="Moundou (Logone Occidental)", ref="2024-01-01", **kw):
    row = {
        "id": i, "sector": "agriculture", "indicator": indicator, "value": value, "unit": "ratio (0-1)",
        "reference_date": ref, "country_code": "TCD", "region": region, "source": "NASA POWER Agro",
        "license": "Public Domain (U.S. Government / NASA)", "notes": "", "collected_at": "2026-09-10T13:53:16",
        "spatial_resolution": "regional_city_hub", "confidence_level": "Satellite_Modeled_Regional",
    }
    row.update(kw)
    return row


def test_domain_agriculture_operational_with_climate_scope():
    mod = DomainRegistry.get_domain("agriculture")
    assert mod.data_status == "operational"
    assert "table_agro_indicators" in mod.knowledge_sources
    assert "températures mensuelles" in mod.instructions
    assert "NASA POWER" in mod.instructions
    assert "données de terrain" in mod.instructions


@pytest.mark.skipif(not REAL_CSV.exists(), reason="CSV agricole commercial absent")
def test_real_csv_is_fully_valid_and_matches_audit(tmp_path):
    store = AgroIndicatorStore(str(tmp_path / "agro.db"))
    report = store.ingest_csv(str(REAL_CSV))
    assert report["rows_valid"] == 2593 and report["written"] == 2593
    assert report["by_source"] == {"NASA POWER Agro": 2316, "World Bank": 277}
    assert report["by_indicator"]["Root zone soil wetness index"] == 780
    assert report["by_indicator"]["Photosynthetically Active Radiation (PAR)"] == 756
    assert len(report["regions"]) == 13  # 12 pôles + national
    # idempotent : relancer ne duplique rien
    store.ingest_csv(str(REAL_CSV))
    assert store.count() == 2593
    # aucune température/précipitation dans les indicateurs
    names = " ".join(report["by_indicator"]).lower()
    assert "temperature" not in names and "precipitation" not in names and "rain" not in names

    zones = server.agro_zones_endpoint(store)
    assert zones["data_available"] and len(zones["zones"]) == 12
    assert zones["title"] == "Pré-diagnostic agro-climatique de zone"
    prof = server.agro_zone_profile_endpoint("moundou", store)
    assert prof["region"] == "Moundou" and prof["province"] == "Logone Occidental"
    assert set(prof["series"]) == {"root_zone_wetness", "surface_wetness", "par"}
    assert prof["provenance"]["sources"] == ["NASA POWER Agro"]
    assert prof["national"]["provenance"]["licenses"] == ["CC BY 4.0"]
    assert any("temp" in lim.lower() for lim in prof["limitations"])


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ({"source": "Open-Meteo Agro-Climate"}, "source non autorisée"),
        ({"source": "FAOSTAT"}, "source non autorisée"),
        ({"license": "CC BY-NC 4.0"}, "licence"),
        ({"value": 1.7}, "hors de l'intervalle physique"),
        ({"region": "Moundou (Mandoul)"}, "province incohérente"),
        ({"region": "Paris"}, "région inconnue"),
        ({"country_code": "FRA"}, "pays"),
        ({"reference_date": "pas-une-date"}, "date de référence invalide"),
        ({"spatial_resolution": "national"}, "incohérentes"),
    ],
)
def test_validation_rejects_non_compliant_rows(mutation, expected):
    with pytest.raises(AgroIngestError) as exc:
        validate_agro_dataframe(pd.DataFrame([_nasa_row(**mutation)]))
    assert expected in str(exc.value)


def test_validation_rejects_missing_values_and_columns():
    row = _nasa_row()
    row["unit"] = None
    with pytest.raises(AgroIngestError):
        validate_agro_dataframe(pd.DataFrame([row]))
    with pytest.raises(AgroIngestError) as exc:
        validate_agro_dataframe(pd.DataFrame([{"indicator": "x"}]))
    assert "Colonnes obligatoires manquantes" in str(exc.value)

def test_nasa_power_monthly_climate_is_accepted_with_environment_provenance():
    row = _nasa_row(
        source="NASA POWER",
        license="CC BY 4.0",
        sector="environment",
        indicator="Monthly precipitation",
        value=3.4,
        unit="mm/day",
    )
    clean, report = validate_agro_dataframe(pd.DataFrame([row]))
    assert report["rows_valid"] == 1
    assert clean[0]["source"] == "NASA POWER"
    assert clean[0]["sector"] == "environment"
    assert clean[0]["region"] == "Moundou"
    assert regional_indicator_key(clean[0]["indicator"]) == "precipitation_daily_mean"

    copernicus = _nasa_row(
        source="Copernicus ERA5-Land",
        license="Licence to use Copernicus Products",
        sector="environment",
        indicator="Monthly precipitation",
        value=2.8,
        unit="mm/day",
    )
    copernicus_clean, copernicus_report = validate_agro_dataframe(pd.DataFrame([copernicus]))
    assert copernicus_report["rows_valid"] == 1
    assert copernicus_clean[0]["source"] == "Copernicus ERA5-Land"

    bad = {**row, "indicator": "Monthly max temperature", "value": 95, "unit": "°C"}
    with pytest.raises(AgroIngestError) as exc:
        validate_agro_dataframe(pd.DataFrame([bad]))
    assert "température hors plage plausible" in str(exc.value)

    wrong_unit = {**row, "unit": "mm"}
    with pytest.raises(AgroIngestError) as unit_exc:
        validate_agro_dataframe(pd.DataFrame([wrong_unit]))
    assert "unité de précipitation attendue" in str(unit_exc.value)


def test_region_parsing_and_province_check():
    assert canonical_region("Abéché (Ouaddaï)") == "Abeche"
    assert canonical_region("N'Djamena (N'Djamena)") == "N'Djamena"
    assert canonical_region("national") == "national"
    assert parse_region("Sarh (Moyen-Chari)") == ("Sarh", "Moyen-Chari")
    assert canonical_region("Sarh (Lac)") is None


def test_anomaly_requires_three_baseline_years_and_flags_deficit():
    pts = [{"reference_date": f"{y}-03-01", "value": 0.50, "unit": "ratio"} for y in (2020, 2021, 2022, 2023)]
    pts.append({"reference_date": "2026-03-01", "value": 0.30, "unit": "ratio"})
    out = {p["reference_date"]: p for p in compute_monthly_anomalies(pts)}
    assert out["2026-03-01"]["baseline_years"] == 4
    assert out["2026-03-01"]["anomaly_pct"] == -40.0
    assert deficit_level(-40.0) == "severe" and deficit_level(-25.0) == "moderate" and deficit_level(-5.0) is None

    short = [{"reference_date": f"{y}-03-01", "value": 0.5, "unit": "r"} for y in (2020, 2021)]
    short.append({"reference_date": "2026-03-01", "value": 0.1, "unit": "r"})
    last = compute_monthly_anomalies(short)[-1]
    assert last["anomaly_pct"] is None  # pas assez d'années de référence : aucune anomalie inventée


def test_zone_profile_emits_deficit_alert_and_stale_flag():
    rows = []
    for i, y in enumerate((2020, 2021, 2022, 2023)):
        rows.append(_nasa_row(i, ref=f"{y}-03-01", value=0.50))
    rows.append(_nasa_row(9, ref="2026-03-01", value=0.30))
    prof = build_zone_profile("Moundou", rows, [], today=date(2026, 4, 15))
    assert prof["alerts"] and prof["alerts"][0]["level"] == "severe"
    assert prof["alerts"][0]["anomaly_pct"] <= MODERATE_DEFICIT_PCT
    assert prof["stale"] is False
    stale = build_zone_profile("Moundou", rows, [], today=date(2027, 1, 1))
    assert stale["stale"] is True and stale["alerts"][0]["stale"] is True

def test_zone_profile_integrates_nasa_rainfall_and_temperature_without_new_screen():
    rows = []
    for i, y in enumerate((2020, 2021, 2022, 2023)):
        rows.append(_nasa_row(
            i, indicator="Monthly precipitation", value=3.0, unit="mm/day",
            ref=f"{y}-03-01", source="NASA POWER", license="CC BY 4.0", sector="environment",
        ))
        rows.append(_nasa_row(
            i + 20, indicator="Monthly mean temperature", value=28.0, unit="°C",
            ref=f"{y}-03-01", source="NASA POWER", license="CC BY 4.0", sector="environment",
        ))
    rows.append(_nasa_row(
        99, indicator="Monthly precipitation", value=0.5, unit="mm/day",
        ref="2026-03-01", source="NASA POWER", license="CC BY 4.0", sector="environment",
    ))
    rows.append(_nasa_row(
        100, indicator="Monthly mean temperature", value=30.0, unit="°C",
        ref="2026-03-01", source="NASA POWER", license="CC BY 4.0", sector="environment",
    ))
    prof = build_zone_profile("Moundou", rows, [], today=date(2026, 4, 15))
    assert "precipitation_daily_mean" in prof["series"]
    assert "temperature_mean" in prof["series"]
    copernicus_rows = []
    for i, y in enumerate((2025, 2026)):
        copernicus_rows.append(_nasa_row(
            i + 200, indicator="Monthly precipitation", value=2.0 + i, unit="mm/day",
            ref=f"{y}-03-01", source="Copernicus ERA5-Land",
            license="Licence to use Copernicus Products", sector="environment",
        ))
        copernicus_rows.append(_nasa_row(
            i + 210, indicator="Monthly mean temperature", value=29.0 + i, unit="°C",
            ref=f"{y}-03-01", source="Copernicus ERA5-Land",
            license="Licence to use Copernicus Products", sector="environment",
        ))
    prof = build_zone_profile("Moundou", rows + copernicus_rows, [], today=date(2026, 4, 15))
    assert "precipitation_daily_mean_copernicus" in prof["series"]
    assert "temperature_mean_copernicus" in prof["series"]
    assert prof["series"]["precipitation_daily_mean"][-1]["anomaly_pct"] == pytest.approx(-83.33, abs=0.1)
    assert any(a["indicator_key"] == "precipitation_daily_mean" for a in prof["alerts"])
    assert set(prof["provenance"]["sources"]) == {"NASA POWER"}


def test_endpoints_handle_unknown_zone_and_empty_database(tmp_path):
    store = AgroIndicatorStore(str(tmp_path / "empty.db"))
    zones = server.agro_zones_endpoint(store)
    assert zones["data_available"] is False and zones["zones"] == []
    with pytest.raises(HTTPException) as unknown:
        server.agro_zone_profile_endpoint("Paris", store)
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as national:
        server.agro_zone_profile_endpoint("national", store)
    assert national.value.status_code == 404
    with pytest.raises(HTTPException) as empty:
        server.agro_zone_profile_endpoint("Sarh", store)
    assert empty.value.status_code == 503


def test_agriculture_chat_grounds_hub_and_overview(monkeypatch):
    sample_rows = [
        _nasa_row(i, region="Abeche", ref=f"{y}-03-01", value=0.50)
        for i, y in enumerate((2020, 2021, 2022, 2023))
    ] + [_nasa_row(99, region="Abeche", ref="2026-03-01", value=0.35)]

    class _FakeAgroStore:
        def rows(self):
            return sample_rows

    monkeypatch.setattr(server, "get_agro_store", lambda: _FakeAgroStore())
    from src.domains import DomainRegistry

    classified = DomainRegistry.classify_domain(
        "Donne-moi le pré-diagnostic agro-climatique de la zone de N'Djamena (humidité des sols, rayonnement, anomalies par rapport à la normale 2020–2023) en citant les sources."
    )
    assert classified.domain_id == "agriculture"

    agro_mod = DomainRegistry.MODULES["agriculture"]
    req_hub = server.PlatformChatRequest(message="Quel est le statut hydrique à Abéché ?")
    res_hub = server._handle_agriculture_chat(
        payload=req_hub,
        agent=None,
        eff_tier="free",
        private_chunks=[],
        quota_info={"remaining": 10},
        domain_mod=agro_mod,
    )
    assert "Abeche" in res_hub["reply"]
    assert "0.35" in res_hub["reply"]
    assert "-30.0 %" in res_hub["reply"]
    assert any("NASA POWER Agro" in s["source"] for s in res_hub["sources"])

    req_all = server.PlatformChatRequest(message="Donne-moi un aperçu agricole du Tchad")
    res_all = server._handle_agriculture_chat(
        payload=req_all,
        agent=None,
        eff_tier="free",
        private_chunks=[],
        quota_info={"remaining": 10},
        domain_mod=agro_mod,
    )
    assert "Pôles couverts (1)" in res_all["reply"]
    assert "2026-03-01" in res_all["reply"]


