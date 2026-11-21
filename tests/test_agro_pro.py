"""Tests Étape 3 (P2) — Espace Agronome PRO : diagnostic de terrain, porte QA et PDF co-brandé."""
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.agro_assessments import AgroFieldAssessmentStore
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
    res_no_lab = server.create_agro_field_assessment_endpoint(
        server.AgroFieldAssessmentRequest(province_hub="Moundou", area_hectares=5.0),
        owner_id=pro_owner, x_premium_key=None,
        store=ind_store, assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
    )
    assert res_no_lab["assessment"]["computed_scores"]["confidence_level"] == "Régional uniquement — Mesures sol non fournies"
    assert res_no_lab["qa"]["can_deliver_pdf"] is False
    with pytest.raises(HTTPException) as exc_qa:
        server.agro_field_assessment_pdf_endpoint(
            res_no_lab["assessment"]["id"],
            payload=server.AgroFieldPdfRequest(agronomist_name="Cabinet Agro Tchad"),
            owner_id=pro_owner, x_premium_key=None,
            assess_store=assess_store, sub_store=sub_store,
        )
    assert exc_qa.value.status_code == 422

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
        assess_store=assess_store, sub_store=sub_store,
    )
    assert pdf_resp.media_type == "application/pdf"
    assert pdf_resp.body.startswith(b"%PDF")

    # Autre utilisateur PRO ne peut pas lire ni télécharger le diagnostic d'un confrère
    other_pro = "user:u_other_pro_1234567890abcdef1234"
    sub_store.admin_update_subscription(
        actor="admin", target_user_id=other_pro, plan_id="premium", status="active", period_days=30,
    )
    assert server.list_agro_field_assessments_endpoint(
        project_id=None, owner_id=other_pro, x_premium_key=None,
        assess_store=assess_store, project_store=proj_store, sub_store=sub_store,
    )["count"] == 0
    with pytest.raises(HTTPException) as exc_idor:
        server.agro_field_assessment_pdf_endpoint(
            res_lab["assessment"]["id"],
            owner_id=other_pro, x_premium_key=None,
            assess_store=assess_store, sub_store=sub_store,
        )
    assert exc_idor.value.status_code == 404

