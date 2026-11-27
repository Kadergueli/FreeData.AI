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
    assert "Copernicus ERA5-Land" in mod.instructions
    assert "données de terrain" in mod.instructions


def test_environment_domain_uses_structured_climate_data():
    mod = DomainRegistry.get_domain("environment")
    assert mod.data_status == "operational"
    assert mod.execution_pipeline == "chad_agent"
    assert "Copernicus ERA5-Land" in mod.instructions
    assert DomainRegistry.classify_domain("Quelle est la température moyenne à Moundou ?").domain_id == "environment"
    assert DomainRegistry.classify_domain("Quelle est la pluviométrie à Sarh ?").domain_id == "environment"


def test_climate_chat_context_keeps_sources_separate_and_discloses_missing_baseline():
    profile = {
        "indicator_labels": {
            "precipitation_daily_mean": "Précipitations moyennes quotidiennes",
            "temperature_mean_copernicus": "Température moyenne — Copernicus ERA5-Land",
        },
        "series": {
            "precipitation_daily_mean": [
                {"reference_date": "2026-10-01", "value": 1.7, "unit": "mm/day", "anomaly_pct": -12.5}
            ],
            "temperature_mean_copernicus": [
                {"reference_date": "2026-10-01", "value": 29.2, "unit": "°C", "anomaly_pct": None}
            ],
        },
    }
    lines = server._climate_series_lines(profile)
    joined = "\n".join(lines)
    assert "NASA POWER" in joined
    assert "Copernicus ERA5-Land" in joined
    assert "-12.5 %" in joined
    assert "ne couvre pas la période de référence 2020–2023" in joined


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


def test_climate_duplicate_audit_collapses_only_identical_measurements(tmp_path):
    base = _nasa_row(
        source="NASA POWER", license="CC BY 4.0", sector="environment",
        indicator="Monthly precipitation", value=3.4, unit="mm/day",
        ref="2024-01-01",
    )
    alias = {**base, "id": 2, "region": "Moundou"}
    clean, report = validate_agro_dataframe(pd.DataFrame([base, alias]))
    assert len(clean) == 1
    assert report["identical_duplicate_rows_collapsed"] == 1
    assert report["conflicting_duplicate_groups"] == 0
    assert report["duplicate_diagnostics"][0]["type"] == "identical"

    conflicting = {**alias, "value": 4.1}
    clean, report = validate_agro_dataframe(pd.DataFrame([base, conflicting]))
    assert clean == []
    assert report["rows_valid"] == 0
    assert report["conflicting_duplicate_rows_excluded"] == 2
    assert report["conflicting_duplicate_groups"] == 1
    diagnostic = report["duplicate_diagnostics"][0]
    assert diagnostic["type"] == "conflicting"
    assert diagnostic["measurements"] == ["3.4 mm/day", "4.1 mm/day"]
    assert set(diagnostic["source_regions"]) == {"Moundou", "Moundou (Logone Occidental)"}

    store = AgroIndicatorStore(str(tmp_path / "conflict.db"))
    with pytest.raises(AgroIngestError, match="doublons contradictoires"):
        store.ingest_dataframe(pd.DataFrame([base, conflicting]), dry_run=False)
    assert store.count() == 0


def test_region_parsing_and_province_check():
    assert canonical_region("Abéché (Ouaddaï)") == "Abeche"
    assert canonical_region("Am Timan (Salamat)") == "Am Timan"
    assert canonical_region("Moussoro (Barh el Gazel)") == "Moussoro"
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
    for i, y in enumerate((2020, 2021, 2022, 2023, 2026)):
        rainfall = 3.0 if y < 2026 else 0.5
        temperature = 28.0 if y < 2026 else 30.0
        copernicus_rows.append(_nasa_row(
            i + 200, indicator="Monthly precipitation", value=rainfall, unit="mm/day",
            ref=f"{y}-03-01", source="Copernicus ERA5-Land",
            license="Licence to use Copernicus Products", sector="environment",
        ))
        copernicus_rows.append(_nasa_row(
            i + 210, indicator="Monthly mean temperature", value=temperature, unit="°C",
            ref=f"{y}-03-01", source="Copernicus ERA5-Land",
            license="Licence to use Copernicus Products", sector="environment",
        ))
    prof = build_zone_profile("Moundou", rows + copernicus_rows, [], today=date(2026, 4, 15))
    assert "precipitation_daily_mean_copernicus" in prof["series"]
    assert "temperature_mean_copernicus" in prof["series"]
    assert any(a["indicator_key"] == "precipitation_daily_mean_copernicus" for a in prof["alerts"])
    assert prof["series"]["precipitation_daily_mean"][-1]["anomaly_pct"] == pytest.approx(-83.33, abs=0.1)
    assert any(a["indicator_key"] == "precipitation_daily_mean" for a in prof["alerts"])
    assert set(prof["provenance"]["sources"]) == {"NASA POWER", "Copernicus ERA5-Land"}


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


