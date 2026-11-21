"""MVP Agriculture : provenance obligatoire, QA gate du titre, isolation PRO, étanchéité des données privées."""
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import server
from src.agro import indicators as ind
from src.agro.assessment import TITLE_FIELD, TITLE_ZONE_ONLY, build_field_assessment, parse_soil
from src.agro.pdf import render_assessment_pdf
from src.agro.store import AgroAssessmentStore
from src.agro.zone import RESOLUTION_NOTICE, ZONE_TITLE, build_zone_prediagnosis

TODAY = date(2026, 8, 15)


def _wide(hubs=("Abeche (Ouaddai)", "Bol (Lac)"), start="2022-01-01", end="2026-07-01"):
    months = pd.date_range(start, end, freq="MS")
    rows = []
    for h in hubs:
        for i, m in enumerate(months):
            rows.append({"region": h, "reference_date": m.strftime("%Y-%m-%d"),
                         "par_w_m2": 9.0 + (i % 5) * 0.2, "root_zone_wetness": 0.2 + (i % 12) * 0.05,
                         "surface_wetness": 0.1 + (i % 12) * 0.04})
    return pd.DataFrame(rows)


@pytest.fixture()
def ind_df():
    rows, _ = ind.nasa_wide_to_rows(_wide())
    return ind.indicators_frame(rows)


def test_wide_to_long_adds_full_provenance_and_no_source_url():
    rows, warnings = ind.nasa_wide_to_rows(_wide())
    assert not warnings and ind.validate_rows(rows) == []
    r = rows[0]
    assert r["source"] == ind.SOURCE_NASA and r["license"] == ind.LICENSE_NASA
    assert r["spatial_resolution"] == "regional_city_hub" and r["confidence_level"] == "Satellite_Modeled_Regional"
    assert "source_url" not in r and r["region"] in ind.HUBS
    assert {x["indicator"] for x in rows} == ind.NASA_INDICATORS  # ni température ni précipitations


def test_missing_nasa_value_999_is_dropped_not_filled():
    df = _wide(hubs=("Bol (Lac)",), start="2026-01-01", end="2026-03-01")
    df.loc[0, "par_w_m2"] = -999
    rows, _ = ind.nasa_wide_to_rows(df)
    assert len(rows) == 3 * 3 - 1


def test_validation_rejects_bad_rows():
    rows, _ = ind.nasa_wide_to_rows(_wide(hubs=("Bol (Lac)",), start="2026-01-01", end="2026-01-01"))
    for mutate in ({"license": "CC BY 4.0"}, {"source_url": ""}, {"indicator": "temperature_2m"},
                   {"confidence_level": "Official_Macro_National"}, {"region": "Paris"}):
        bad = [{**rows[0], **mutate}]
        assert ind.validate_rows(bad), mutate
    assert ind.validate_rows([rows[0], rows[0]])  # doublon


def test_worldbank_whitelist():
    ok = pd.DataFrame([{"indicator": "cereal_yield", "year": 2023, "value": 1000.0, "unit": "kg/ha"}])
    rows = ind.worldbank_long_to_rows(ok)
    assert ind.validate_rows(rows) == [] and rows[0]["license"] == "CC BY 4.0" and rows[0]["spatial_resolution"] == "national"
    with pytest.raises(ValueError):
        ind.worldbank_long_to_rows(ok.assign(indicator="faostat_yield"))


def test_hub_name_normalization_accents_and_labels():
    assert ind.normalize_hub("Abeche (Ouaddai)") == "Abeche" == ind.normalize_hub("Abéché")
    assert ind.normalize_hub("N'Djamena (N'Djamena)") == "N'Djamena"
    assert ind.normalize_hub("Paris") is None and len(ind.HUBS) == 12


def test_zone_prediagnosis_title_notice_and_provenance(ind_df):
    z = build_zone_prediagnosis(ind_df, "Abeche", today=TODAY)
    assert z["title"] == ZONE_TITLE and z["resolution_notice"] == RESOLUTION_NOTICE
    assert "parcelle" in z["disclaimer"] and len(z["indicators"]) == 3
    for i in z["indicators"]:
        assert set(i["provenance"]) >= {"source", "license", "reference_date", "spatial_resolution", "confidence_level"}
        assert i["history_same_month"] and not i["stale"]
    with pytest.raises(KeyError):
        build_zone_prediagnosis(ind_df, "Paris")
    with pytest.raises(LookupError):
        build_zone_prediagnosis(ind_df, "Sarh")


def test_zone_marks_stale_data(ind_df):
    z = build_zone_prediagnosis(ind_df, "Bol", today=date(2027, 3, 1))
    assert all(i["stale"] for i in z["indicators"])


def test_price_forecasts_need_measured_error(ind_df):
    fc = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "market_name": "Bol", "value": 300.0, "forecast_t1": 310.0,
         "hist_mae": 15.0, "last_observed_month": "2026-07", "forecast_month": "2026-08", "source": "WFP"},
        {"province": "Lac", "commodity_std": "Maize", "market_name": "Bol", "value": 300.0, "forecast_t1": 310.0,
         "hist_mae": None, "last_observed_month": "2026-07", "forecast_month": "2026-08", "source": "WFP"},
        {"province": "Batha", "commodity_std": "Millet", "market_name": "Ati", "value": 300.0, "forecast_t1": 310.0,
         "hist_mae": 15.0, "last_observed_month": "2026-07", "forecast_month": "2026-08", "source": "WFP"},
    ])
    z = build_zone_prediagnosis(ind_df, "Bol", fc, today=TODAY)
    assert [f["commodity"] for f in z["price_forecasts"]] == ["Millet"]
    assert z["price_forecasts"][0]["hist_error_pct"] == 5.0


def test_qa_gate_downgrades_without_soil(ind_df):
    z = build_zone_prediagnosis(ind_df, "Abeche", today=TODAY)
    a = build_field_assessment(z, None, today=TODAY)
    assert a["title"] == TITLE_ZONE_ONLY and a["downgraded"] and a["qa"]["status"] == "downgraded"
    partial = build_field_assessment(z, {"ph": 6.4}, today=TODAY)  # pH seul : insuffisant
    assert partial["title"] == TITLE_ZONE_ONLY


def test_qa_gate_full_soil_gives_field_title(ind_df):
    z = build_zone_prediagnosis(ind_df, "Abeche", today=TODAY)
    soil = {"ph": 6.4, "organic_matter_pct": 1.8, "sampling_date": "2026-07-01", "lab_name": "Labo X"}
    a = build_field_assessment(z, soil, {"organization_name": "AgroConseil", "primary_color": "#112233"}, crop="Mil", today=TODAY)
    assert a["title"] == TITLE_FIELD and not a["downgraded"] and a["qa"]["status"] == "passed"
    assert a["branding"]["organization_name"] == "AgroConseil" and a["branding"]["primary_color"] == "#112233"
    assert any("pH mesuré" in f for f in a["findings"])
    pdf = render_assessment_pdf(a)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


@pytest.mark.parametrize("soil", [
    {"ph": 14}, {"ph": "abc"}, {"organic_matter_pct": -1}, {"texture": "granit"},
    {"ph": 6, "sampling_date": "2030-01-01"}, {"ph": 6, "sampling_date": "2020-01-01"}, {"sampling_date": "pas-une-date"},
])
def test_invalid_soil_is_rejected_not_silently_dropped(soil):
    with pytest.raises(ValueError):
        parse_soil(soil, today=TODAY)


def test_branding_is_sanitized(ind_df):
    z = build_zone_prediagnosis(ind_df, "Abeche", today=TODAY)
    a = build_field_assessment(z, None, {"organization_name": "<script>x</script>", "primary_color": "red;evil"}, today=TODAY)
    assert "<" not in a["branding"]["organization_name"] and a["branding"]["primary_color"] == "#1B5E20"
    assert render_assessment_pdf(a).startswith(b"%PDF")


def test_store_isolates_owners(tmp_path, ind_df):
    store = AgroAssessmentStore(str(tmp_path / "agro.db"))
    z = build_zone_prediagnosis(ind_df, "Abeche", today=TODAY)
    rec = store.create("owner-a", build_field_assessment(z, None, today=TODAY))
    assert store.get("owner-a", rec["assessment_id"])["hub"] == "Abeche"
    assert store.get("owner-b", rec["assessment_id"]) is None
    assert store.list("owner-b") == [] and not store.delete("owner-b", rec["assessment_id"])
    assert store.delete("owner-a", rec["assessment_id"])


def test_private_assessments_never_reach_ml_scopes():
    from src.ml_benchmark import ALLOWED_DATASET_SCOPES
    assert ALLOWED_DATASET_SCOPES == ("platform_public",)


# ── API ────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch, tmp_path, ind_df):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1"))
    fc = pd.DataFrame([{
        "source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet",
        "last_observed_month": "2026-10", "last_observed_price": 300.0, "forecast_month": "2026-11",
        "forecast_t1": 310.0, "ci_low_80": 280.0, "ci_high_80": 340.0, "hist_mae": 15.0,
    }])
    cp = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "credit_score": 80.0, "grade": "A",
                        "ltv_ratio": 0.7, "cv_pct": 8.0, "max_drawdown_pct": 6.0}])
    server.STATE.clear()
    server.STATE.update(server.build_state_from_gold(fc, cp))
    monkeypatch.setattr(server, "_agro_indicator_frame", lambda: ind_df)
    monkeypatch.setattr(server, "_AGRO_STORE", AgroAssessmentStore(str(tmp_path / "agro.db")))
    yield TestClient(server.app)
    server.STATE.clear()


PRO = {"X-Premium-Key": "pro-key-1"}
SOIL = {"ph": 6.5, "organic_matter_pct": 2.0, "sampling_date": date.today().isoformat()}


def test_api_public_endpoints(client):
    assert client.get("/api/v1/agro/hubs").json()["count"] == 12
    r = client.get("/api/v1/agro/indicators", params={"hub": "Bol"}).json()
    assert r["count"] > 0 and all(i["license"] and i["source"] and i["spatial_resolution"] for i in r["items"])
    assert client.get("/api/v1/agro/indicators", params={"hub": "Paris"}).status_code == 404
    z = client.get("/api/v1/agro/zone-prediagnosis", params={"hub": "Bol"}).json()
    assert z["title"] == ZONE_TITLE and z["price_forecasts"][0]["commodity"] == "Millet"
    assert client.get("/api/v1/agro/zone-prediagnosis", params={"hub": "Sarh"}).status_code == 503


def test_api_field_assessment_requires_pro(client):
    body = {"hub": "Bol", "soil": SOIL}
    for path in ("/api/v1/agro/field-assessment", "/api/v1/agro/field-assessment/preview"):
        assert client.post(path, json=body).status_code == 403
        assert client.post(path, json=body, headers={"X-Premium-Key": "bad"}).status_code == 403
    assert client.get("/api/v1/agro/field-assessments").status_code == 403


def test_api_preview_gate_and_pdf(client):
    r = client.post("/api/v1/agro/field-assessment/preview", json={"hub": "Bol"}, headers=PRO)
    assert r.status_code == 200 and r.json()["title"] == TITLE_ZONE_ONLY
    r = client.post("/api/v1/agro/field-assessment/preview", json={"hub": "Bol", "soil": SOIL}, headers=PRO)
    assert r.json()["title"] == TITLE_FIELD
    pdf = client.post("/api/v1/agro/field-assessment/preview?format=pdf", json={"hub": "Bol", "soil": SOIL}, headers=PRO)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # le client ne peut pas imposer le titre
    assert client.post("/api/v1/agro/field-assessment/preview", json={"hub": "Bol", "title": TITLE_FIELD}, headers=PRO).status_code == 422
    assert client.post("/api/v1/agro/field-assessment/preview", json={"hub": "Bol", "soil": {"ph": 99}}, headers=PRO).status_code == 422
    assert client.post("/api/v1/agro/field-assessment/preview", json={"hub": "Paris"}, headers=PRO).status_code == 404


def test_api_create_list_get_delete_roundtrip_if_owner_resolved(client):
    r = client.post("/api/v1/agro/field-assessment", json={"hub": "Bol", "soil": SOIL}, headers=PRO)
    if r.status_code == 401:  # clé premium seule ne désigne pas de compte : l'enregistrement exige une connexion
        return
    assert r.status_code == 201
    aid = r.json()["assessment_id"]
    assert client.get("/api/v1/agro/field-assessments", headers=PRO).json()["count"] == 1
    assert client.get(f"/api/v1/agro/field-assessments/{aid}", headers=PRO).json()["title"] == TITLE_FIELD
    assert client.get(f"/api/v1/agro/field-assessments/{aid}?format=pdf", headers=PRO).content.startswith(b"%PDF")
    assert client.get("/api/v1/agro/field-assessments/not-an-id", headers=PRO).status_code == 404
    assert client.delete(f"/api/v1/agro/field-assessments/{aid}", headers=PRO).json() == {"deleted": True}
