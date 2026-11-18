"""Phase 7 Product Acceptance Tests: 13-step E2E journey and 5 representative simulated business projects."""
from dataclasses import replace

import pandas as pd
import pytest

from api import server
from src.ai_agent import extract_client_state
from src.projects import ProjectStore
from src.reports import build_market_study_dossier, render_market_study_pdf


def _acceptance_state(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    fc = pd.DataFrame([
        {
            "source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 210.0,
            "forecast_month": "2026-11", "forecast_t1": 220.0,
            "ci_low_80": 195.0, "ci_high_80": 245.0, "hist_mae": 18.0,
        },
        {
            "source": "WFP", "province": "Batha", "market_name": "Ati", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 340.0,
            "forecast_month": "2026-11", "forecast_t1": 330.0,
            "ci_low_80": 315.0, "ci_high_80": 385.0, "hist_mae": 22.0,
        },
        {
            "source": "WFP", "province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Rice (imported)",
            "last_observed_month": "2026-10", "last_observed_price": 550.0,
            "forecast_month": "2026-11", "forecast_t1": 560.0,
            "ci_low_80": 520.0, "ci_high_80": 600.0, "hist_mae": 20.0,
        },
        {
            "source": "WFP", "province": "Logone Occidental", "market_name": "Moundou", "commodity_std": "Groundnuts (shelled)",
            "last_observed_month": "2026-10", "last_observed_price": 420.0,
            "forecast_month": "2026-11", "forecast_t1": 430.0,
            "ci_low_80": 395.0, "ci_high_80": 465.0, "hist_mae": 21.0,
        },
        {
            "source": "WFP", "province": "Ouaddai", "market_name": "Abeche", "commodity_std": "Sorghum (red)",
            "last_observed_month": "2026-10", "last_observed_price": 230.0,
            "forecast_month": "2026-11", "forecast_t1": 240.0,
            "ci_low_80": 215.0, "ci_high_80": 265.0, "hist_mae": 19.0,
        },
    ])
    cp = pd.DataFrame([
        {"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "ltv_ratio": 0.8, "cv_pct": 8.5, "max_drawdown_pct": 6.0},
        {"province": "N'Djamena", "commodity_std": "Rice (imported)", "credit_score": 78.0, "grade": "A", "ltv_ratio": 0.75, "cv_pct": 9.2, "max_drawdown_pct": 7.0},
    ])
    st = server.build_state_from_gold(fc, cp)
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: []
    return st


def test_e2e_13_step_user_journey(tmp_path, monkeypatch):
    st = _acceptance_state(monkeypatch)
    store = ProjectStore(db_path=str(tmp_path / "acc.db"), artifacts_dir=str(tmp_path / "art"))

    # 1-2. User creates project
    owner = "user:entrepreneur_1"
    proj = store.create_project(owner, "Distribution Mil Lac-Batha", description="Négoce inter-provinces")
    pid = proj["project_id"]

    # 3-4. User explains business idea; assistant detects missing capital/destination
    conv = store.create_conversation(owner, pid, title="Cadrage")
    cs1 = extract_client_state([], "Je veux lancer un négoce de mil à Lac.", provider=st["agent"].provider)
    assert "capital_xaf" in cs1["missing_fields"]
    store.add_message(owner, pid, conv["conversation_id"], "user", "Je veux lancer un négoce de mil à Lac.", updated_study_context=cs1["study_context"])

    # 5-6. User provides financials, promoter, instructions, then corrects budget
    cs2 = extract_client_state(
        [],
        "Vendre à Batha avec 500 000 XAF, promoteur : Moussa, inclure SWOT, sans équipement (CAPEX = 0).",
        provider=st["agent"].provider,
        previous_context=cs1["study_context"],
    )
    cs3 = extract_client_state(
        [],
        "Finalement budget de 1 000 000 XAF.",
        provider=st["agent"].provider,
        previous_context=cs2["study_context"],
    )
    store.add_message(owner, pid, conv["conversation_id"], "user", "Finalement budget de 1 000 000 XAF.", updated_study_context=cs3["study_context"])

    # 7-12. Study Builder + QA Validator + PDF generation + Version storage
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province="Batha",
        capital_xaf=cs3["known_params"]["capital_xaf"],
        promoter_name=cs3["known_params"]["promoter_name"],
        study_context=cs3["study_context"],
    )
    assert dossier["validation"]["can_deliver_pdf"] is True
    assert dossier["promoter_name"] == "Moussa"
    pdf = render_market_study_pdf(dossier)
    assert pdf.startswith(b"%PDF-1.")
    ver = store.create_study_version(owner, pid, study_id=None, dossier=dossier, generation_params={"capital_xaf": 1_000_000}, pdf_bytes=pdf)
    assert ver["version_number"] == 1

    # 13. User returns later and resumes project
    store_reloaded = ProjectStore(db_path=str(tmp_path / "acc.db"), artifacts_dir=str(tmp_path / "art"))
    resumed = store_reloaded.get_project(owner, pid)
    assert resumed["study_context"]["budget_and_assumptions"]["capital_xaf"] == 1_000_000.0
    assert "SWOT" in resumed["study_context"]["required_sections"]
    assert store_reloaded.get_study_version_pdf(owner, pid, ver["study_id"], 1).startswith(b"%PDF-1.")


def test_5_representative_business_projects(monkeypatch):
    st = _acceptance_state(monkeypatch)
    prov = st["agent"].provider

    # 1. Agricultural distribution (supported)
    d_agri = build_market_study_dossier(prov, "Millet", "Lac", "Batha", capital_xaf=1_000_000)
    assert d_agri["validation"]["can_deliver_pdf"] is True
    assert d_agri["business_plan"]["commercial_strategy"]["long_distance_freight_warning"] is True

    # 2. Food retail (local market, supported)
    d_retail = build_market_study_dossier(prov, "Rice (imported)", "N'Djamena", None, capital_xaf=250_000)
    assert d_retail["validation"]["can_deliver_pdf"] is True
    assert render_market_study_pdf(d_retail).startswith(b"%PDF-1.")

    # 3. Small manufacturing / transformation (raw input price observed; transformation/demand gaps flagged)
    d_mfg = build_market_study_dossier(prov, "Groundnuts (shelled)", "Logone Occidental", None, capital_xaf=500_000)
    assert d_mfg["validation"]["can_deliver_pdf"] is True
    assert any("volumes de demande" in g.lower() for g in d_mfg["data_gaps"])

    # 4. Digital services startup (outside agricultural dataset -> must NOT fabricate prices!)
    with pytest.raises(ValueError):
        build_market_study_dossier(prov, "SaaS Cloud Platform", "N'Djamena", None, capital_xaf=2_000_000)

    # 5. Import/Export corridor (cross-province long distance -> freight warning + missing customs/taxes flagged)
    d_imp = build_market_study_dossier(prov, "Sorghum (red)", "Ouaddai", "Batha", capital_xaf=1_500_000)
    assert d_imp["validation"]["can_deliver_pdf"] is True
    assert any("taxes communales" in g.lower() for g in d_imp["data_gaps"])
