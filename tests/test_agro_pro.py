"""Tests Étape 3 (P2) — Espace Agronome PRO : diagnostic de terrain, porte QA et PDF co-brandé."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.agro_assessments import AgroFieldAssessmentStore, AgronomistProfileStore
from src.agro_indicators import AgroIndicatorStore
from src.monetization import SubscriptionStore

REAL_CSV = Path(__file__).resolve().parent.parent / "freedatatd-agriculture-commercial-clean.csv"


def _seed_agro(tmp_path):
    ind_store = AgroIndicatorStore(str(tmp_path / "agro.db"))
    assess_store = AgroFieldAssessmentStore(str(tmp_path / "agro.db"))
    if REAL_CSV.exists():
        ind_store.ingest_csv(str(REAL_CSV))
    else:
        rows = []
        for i, y in enumerate((2020, 2021, 2022, 2023, 2026)):
            rows.append({
                "id": i + 1, "sector": "agriculture", "indicator": "Root zone soil wetness index",
                "value": 0.42, "unit": "ratio (0-1)", "reference_date": f"{y}-06-01",
                "country_code": "TCD", "region": "Moundou (Logone Occidental)",
                "source": "NASA POWER Agro", "license": "Public Domain (U.S. Government / NASA)",
                "notes": "", "collected_at": "2026-09-10T13:53:16",
                "spatial_resolution": "regional_city_hub", "confidence_level": "Satellite_Modeled_Regional",
            })
        rows.append({
            "id": 99, "sector": "agriculture", "indicator": "Cereal yield",
            "value": 1050.0, "unit": "kg/ha", "reference_date": "2024-01-01",
            "country_code": "TCD", "region": "national",
            "source": "World Bank", "license": "CC BY 4.0",
            "notes": "", "collected_at": "2026-09-10T13:53:16",
            "spatial_resolution": "national", "confidence_level": "Official_Macro_National",
        })
        ind_store.ingest_dataframe(pd.DataFrame(rows))
    return ind_store, assess_store


def test_agronome_pro_requires_pro_and_qa_blocks_empty_lab_pdf(tmp_path):
    ind_store, assess_store = _seed_agro(tmp_path)
    profile_store = AgronomistProfileStore(str(tmp_path / "agro.db"))
    sub_store = SubscriptionStore(str(tmp_path / "billing.db"))
    proj_store = server.ProjectStore(str(tmp_path / "projects.db"))
    free_owner = "user:u_free_agro_1234567890abcdef123456"
    pro_owner = "user:u_pro_agro_1234567890abcdef1234567"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=pro_owner, plan_id="premium", status="active", period_days=30,
    )

    # 1. Utilisateur gratuit refusé (403 ou 503 selon PREMIUM_API_KEYS)
    with pytest.raises(HTTPException) as exc_free:
        server.create_agro_field_assessment_endpoint(
            server.AgroFieldAssessmentRequest(province_hub="Moundou"),
            owner_id=free_owner, x_premium_key=None,
            store=ind_store, assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
        )
    assert exc_free.value.status_code in (403, 503)

    # 2. Sans mesures de sol labo -> confidence_level régional + porte QA bloque le PDF (HTTP 422)
    profile_store.submit_profile(
        pro_owner,
        firm_name="Dr. Moussa — Bureau Agro",
        license_number="AGR-TD-001",
        address="N'Djamena",
        contact="+235 66 00 00 00",
    )
    # Tant que non approuvé par l'admin, le PDF est bloqué en 403
    with pytest.raises(HTTPException) as exc_unverified:
        server.agro_field_assessment_pdf_endpoint(
            "AG-ANY",
            payload=server.AgroFieldPdfRequest(),
            owner_id=pro_owner, x_premium_key=None,
            assess_store=assess_store, profile_store=profile_store, sub_store=sub_store,
        )
    assert exc_unverified.value.status_code == 403

    profile_store.review_profile(pro_owner, status="approved", reviewed_by="admin")

    res_no_lab = server.create_agro_field_assessment_endpoint(
        server.AgroFieldAssessmentRequest(
            province_hub="Moundou",
            gps_lat=8.65,
            gps_lon=16.25,
            area_hectares=5.0,
        ),
        owner_id=pro_owner, x_premium_key=None,
        store=ind_store, assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
    )
    assert "En attente d'analyse physique" in res_no_lab["assessment"]["computed_scores"]["confidence_level"]
    assert res_no_lab["qa"]["can_deliver_pdf"] is True
    assert res_no_lab["qa"]["qa_mode"] == "SATELLITE_ESTIMATION"
    assert any("22/30 pts" in warning for warning in res_no_lab["qa"]["warnings"])
    # Vérifier la formule unifiée 50/30/20 entre bandeau et meilleure culture + bulletin 6 paramètres
    cs = res_no_lab["assessment"]["computed_scores"]
    site_ctx = cs["site_context"]
    assert site_ctx["area_hectares"] == 5.0
    assert site_ctx["area_m2"] == 50000.0
    assert site_ctx["area_basis"] == "user_declared"
    assert site_ctx["coordinates"]["provided"] is True
    assert len(site_ctx["climate_hubs"]) == 3
    assert site_ctx["soil_method"] == "SoilGrids 2.0 regional estimate"
    assert "field boundary polygon" in site_ctx["area_usage"]
    ws = cs["weighted_score"]
    assert ws["breakdown"]["hydric_security"]["max"] == 50
    assert ws["breakdown"]["soil_quality"]["max"] == 30
    assert ws["breakdown"]["market_logistics"]["max"] == 20
    assert cs["crop_assessments"][0]["suitability_score"] == round(ws["total_score"])
    assert len(cs["bulletin"]["lab_parameters"]) == 6
    assert len(cs["bulletin"]["prescriptions"]) >= 1
    # Les 4 cultures doivent avoir des scores différenciés (plus de 75/100 uniforme)
    no_lab_scores = {c["crop_id"]: c["suitability_score"] for c in res_no_lab["assessment"]["computed_scores"]["crop_assessments"]}
    assert len(set(no_lab_scores.values())) >= 2
    # IDW k=3 sur les 3 pôles les plus proches
    idw_hubs = res_no_lab["assessment"]["computed_scores"]["gps_logistics"]["idw_hubs"]
    assert len(idw_hubs) == 3
    assert 99.8 <= sum(h["weight_pct"] for h in idw_hubs) <= 100.2
    # Le PDF est désormais générable même sans mesures labo (en mode Pré-diagnostic Satellitaire)
    pdf_sat = server.agro_field_assessment_pdf_endpoint(
        res_no_lab["assessment"]["id"],
        payload=server.AgroFieldPdfRequest(agronomist_name="Cabinet Agro Tchad"),
        owner_id=pro_owner, x_premium_key=None,
        assess_store=assess_store, profile_store=profile_store, sub_store=sub_store,
    )
    assert pdf_sat.media_type == "application/pdf"
    assert pdf_sat.body.startswith(b"%PDF")
    pdf_sat_text = "\\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_sat.body)).pages)
    assert "Références bibliographiques" in pdf_sat_text
    assert "NASA POWER" in pdf_sat_text
    assert "World Bank" in pdf_sat_text
    assert "Localisation, superficie et données spatiales utilisées" in pdf_sat_text
    assert "5 ha (50 000 m²)" in pdf_sat_text
    assert "Pôles contributeurs et poids" in pdf_sat_text
    assert "Humidité zone racinaire" in pdf_sat_text

    # 3. Avec mesures labo -> score complet + PDF co-brandé généré + isolation stricte entre comptes
    res_lab = server.create_agro_field_assessment_endpoint(
        server.AgroFieldAssessmentRequest(
            province_hub="Moundou",
            area_hectares=10.0,
            lab_soil_inputs={"ph": 6.3, "texture": "sandy_loam", "organic_matter": 1.9},
            agronomist_field_notes="Sol drainant adapté aux céréales pluviales.",
        ),
        owner_id=pro_owner, x_premium_key=None,
        store=ind_store, assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
    )
    assert res_lab["qa"]["can_deliver_pdf"] is True
    assert res_lab["assessment"]["report_verification_code"].startswith("FDT-")
    pdf_resp = server.agro_field_assessment_pdf_endpoint(
        res_lab["assessment"]["id"],
        payload=server.AgroFieldPdfRequest(agronomist_name="Dr. Moussa — Bureau Agro"),
        owner_id=pro_owner, x_premium_key=None,
        assess_store=assess_store, profile_store=profile_store, sub_store=sub_store,
    )
    assert pdf_resp.media_type == "application/pdf"
    assert pdf_resp.body.startswith(b"%PDF")

    # Autre utilisateur PRO ne peut pas lire ni télécharger le diagnostic d'un confrère
    other_pro = "user:u_other_pro_1234567890abcdef1234"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=other_pro, plan_id="premium", status="active", period_days=30,
    )
    profile_store.submit_profile(other_pro, firm_name="Autre Cabinet", license_number="AGR-TD-002")
    profile_store.review_profile(other_pro, status="approved", reviewed_by="admin")
    assert server.list_agro_field_assessments_endpoint(
        project_id=None, owner_id=other_pro, x_premium_key=None,
        assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
    )["count"] == 0
    with pytest.raises(HTTPException) as exc_idor:
        server.agro_field_assessment_pdf_endpoint(
            res_lab["assessment"]["id"],
            owner_id=other_pro, x_premium_key=None,
            assess_store=assess_store, profile_store=profile_store, sub_store=sub_store,
        )
    assert exc_idor.value.status_code == 404


def test_gps_logistics_verified_economics_and_compare_assessments(tmp_path):
    from src.agro_engine import compute_gps_logistics, compute_verified_economics

    # 1. GPS proche (< 15 km -> décote 8 %) et éloigné (> 50 km -> décote 22 % + alerte)
    near = compute_gps_logistics(12.14, 15.06)
    assert near["closest_hub"] == "N'Djamena"
    assert near["farmgate_discount_pct"] == 8.0
    assert near["remoteness_alert"] is False

    far = compute_gps_logistics(10.80, 17.20)
    assert far["distance_hub_km"] > 50.0
    assert far["farmgate_discount_pct"] == 22.0
    assert far["remoteness_alert"] is True

    # 2. Modèle économique vérifiable (formule explicite + 3 scénarios)
    econ = compute_verified_economics(
        crop_id="millet",
        area_hectares=10.0,
        yield_kg_ha=834.6,
        yield_source="World Bank 2020–2024",
        predicted_xaf_kg=300.0,
        mape_pct=10.0,
        stress_min_xaf_kg=200.0,
        farmgate_discount_pct=15.0,
        max_hub_price_xaf_kg=380.0,
        max_hub_province="Kanem",
    )
    assert econ["production_kg"] == 8346.0
    assert econ["farmgate_price_central_xaf_kg"] == 255.0
    assert econ["ca_central_xaf"] == round(8346.0 * 255.0)
    assert "834.6 kg/ha" in econ["formula_text"]
    assert len(econ["scenarios"]) == 3

    # 3. Comparaison multi-terrains (GPS candidats) + PDF comparatif
    ind_store, assess_store = _seed_agro(tmp_path)
    profile_store_cmp = AgronomistProfileStore(str(tmp_path / "agro.db"))
    sub_store = SubscriptionStore(str(tmp_path / "billing_cmp.db"))
    pro_owner = "user:u_pro_cmp_1234567890abcdef1234567"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=pro_owner, plan_id="premium", status="active", period_days=30,
    )
    profile_store_cmp.submit_profile(pro_owner, firm_name="Cabinet Audit Tchad", license_number="AGR-TD-042")
    profile_store_cmp.review_profile(pro_owner, status="approved", reviewed_by="admin")
    cmp_payload = server.AgroCompareRequest(
        candidates=[
            server.AgroCandidateInput(
                label="Terrain A (proche Moundou)",
                gps_lat=8.58,
                gps_lon=16.09,
                area_hectares=5.0,
                lab_soil_inputs={"ph": 6.3, "texture": "sandy_loam"},
            ),
            server.AgroCandidateInput(
                label="Terrain B (enclavé sans labo)",
                gps_lat=9.30,
                gps_lon=16.80,
                area_hectares=5.0,
            ),
        ],
        agronomist_name="Cabinet Audit Tchad",
        agronomist_license="AGR-TD-042",
    )
    cmp_res = server.compare_agro_assessments_endpoint(
        cmp_payload,
        owner_id=pro_owner,
        x_premium_key=None,
        store=ind_store,
        assess_store=assess_store,
        sub_store=sub_store,
    )
    assert cmp_res["count"] == 2
    assert "MAILLE SATELLITAIRE" in cmp_res["title"] or "Mesures sol non fournies" in cmp_res["title"]
    assert cmp_res["comparison_table"][0]["rank_label"] == "#1 Recommandé"

    pdf_cmp = server.compare_agro_assessments_pdf_endpoint(
        cmp_payload,
        owner_id=pro_owner,
        x_premium_key=None,
        store=ind_store,
        assess_store=assess_store,
        profile_store=profile_store_cmp,
        sub_store=sub_store,
    )
    assert pdf_cmp.media_type == "application/pdf"
    assert pdf_cmp.body.startswith(b"%PDF")

    # 4. Radar National Agro-Marché
    radar = server.agro_campaign_radar_endpoint(
        state=server.STATE,
        owner_id=pro_owner,
        x_premium_key=None,
        store=ind_store,
        sub_store=sub_store,
    )
    assert radar["summary"]["hubs_count"] >= 1
    assert len(radar["hubs"]) == radar["summary"]["hubs_count"]
    assert "NASA POWER Agro (Public Domain)" in radar["sources"]

@pytest.mark.parametrize("area_hectares", [1.0, 5.0, 10.0, 20.0])
def test_verified_economics_scales_linearly_with_declared_area(area_hectares):
    from src.agro_engine import compute_verified_economics

    result = compute_verified_economics(
        crop_id="sorghum_red",
        area_hectares=area_hectares,
        yield_kg_ha=834.6,
        yield_source="World Bank reference yield (model assumption)",
        predicted_xaf_kg=300.0,
        mape_pct=10.0,
        stress_min_xaf_kg=200.0,
        farmgate_discount_pct=15.0,
    )

    expected_production = round(area_hectares * 834.6, 1)
    expected_farmgate_price = round(300.0 * (1.0 - 0.15), 1)
    expected_revenue = round(expected_production * expected_farmgate_price)

    assert result["area_hectares"] == area_hectares
    assert result["area_assumed_1ha"] is False
    assert result["production_kg"] == expected_production
    assert result["farmgate_price_central_xaf_kg"] == expected_farmgate_price
    assert result["ca_central_xaf"] == expected_revenue
