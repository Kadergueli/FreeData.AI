"""Phase 3 QA tests: modular report engine, dynamic report types, charts, provenance, and PDF output."""
from dataclasses import replace

import pandas as pd

from api import server
from src.reports import PDFRenderer, ReportOrchestrator, build_market_study_dossier, render_market_study_pdf
from src.reports.sections import detect_report_type, select_sections


def _sample_state(monkeypatch, *, with_dest: bool = True, with_passport: bool = True):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    rows = [
        {
            "source": "WFP",
            "province": "Lac",
            "market_name": "Bol",
            "commodity_std": "Millet",
            "last_observed_month": "2026-10",
            "last_observed_price": 210.0,
            "forecast_month": "2026-11",
            "forecast_t1": 220.0,
            "ci_low_80": 195.0,
            "ci_high_80": 245.0,
            "hist_mae": 18.0,
        }
    ]
    if with_dest:
        rows.append(
            {
                "source": "WFP",
                "province": "N'Djamena",
                "market_name": "Dembe",
                "commodity_std": "Millet",
                "last_observed_month": "2026-10",
                "last_observed_price": 340.0,
                "forecast_month": "2026-11",
                "forecast_t1": 330.0,
                "ci_low_80": 315.0,
                "ci_high_80": 385.0,
                "hist_mae": 22.0,
            }
        )
    fc = pd.DataFrame(rows)
    cp = (
        pd.DataFrame([
            {
                "province": "Lac",
                "commodity_std": "Millet",
                "credit_score": 82.0,
                "grade": "A",
                "ltv_ratio": 0.8,
                "cv_pct": 8.5,
                "max_drawdown_pct": 6.0,
            }
        ])
        if with_passport
        else pd.DataFrame()
    )
    st = server.build_state_from_gold(fc, cp)
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: [
        {"titre": "Bulletin PAM Tchad", "editeur": "WFP", "page": 4, "url_source": "https://wfp.org"}
    ]
    return st


def test_dynamic_report_types_and_section_selection(monkeypatch):
    st = _sample_state(monkeypatch)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province="N'Djamena",
        capital_xaf=1_000_000,
    )
    assert detect_report_type(dossier, {}) == "feasibility_study"

    # Market study type (no destination, market_study requested)
    ms_dossier = {**dossier, "dest_province": None}
    ms_ctx = {"required_sections": ["market_study", "SWOT", "competitor_analysis"]}
    assert detect_report_type(ms_dossier, ms_ctx) == "market_study"
    ms_secs = select_sections("market_study", ms_dossier, ms_ctx)
    assert "SWOT" in ms_secs
    assert "competitor_analysis" in ms_secs
    assert "six_month_projection" not in ms_secs

    # Financial analysis type with exclusion
    fin_ctx = {"required_sections": ["six_month_projection", "stress_tests"], "excluded_sections": ["stress_tests"]}
    assert detect_report_type(dossier, fin_ctx) == "financial_analysis"
    fin_secs = select_sections("financial_analysis", dossier, fin_ctx)
    assert "six_month_projection" in fin_secs
    assert "risk_and_sensitivity" not in fin_secs


def test_orchestrator_verdict_provenance_unsupported_and_pdf_rendering(monkeypatch):
    st = _sample_state(monkeypatch)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province="N'Djamena",
        capital_xaf=1_000_000,
        promoter_name="Moussa Mahamat",
        study_context={
            "objectives": ["Obtenir un financement bancaire"],
            "target_customers": ["restaurateurs", "demi-grossistes"],
            "required_sections": ["SWOT", "PESTEL", "competitor_analysis", "supply_demand", "operational_recommendations"],
            "excluded_sections": [],
        },
    )
    doc = ReportOrchestrator().build_document(dossier)
    sec_map = {s.section_id: s for s in doc.sections}

    assert doc.verdict["is_non_rentable"] is False
    assert sec_map["competitor_analysis"].is_available is False
    assert sec_map["supply_demand"].is_available is False
    assert sec_map["SWOT"].is_available is True
    assert sec_map["PESTEL"].is_available is True
    assert any(b.get("type") == "chart_cashflow" for b in sec_map["six_month_projection"].blocks)

    pdf_bytes = PDFRenderer().render(doc)
    assert pdf_bytes.startswith(b"%PDF-1.")
    assert len(pdf_bytes) > 10000


def test_missing_datasets_and_non_rentable_scale_pdf(monkeypatch):
    st = _sample_state(monkeypatch, with_dest=False, with_passport=False)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province=None,
        capital_xaf=100_000,
    )
    doc = ReportOrchestrator().build_document(dossier)
    assert doc.verdict["is_non_rentable"] is True
    assert "NON RENTABLE" in doc.verdict["title"]

    pdf_bytes = render_market_study_pdf(dossier)
    assert pdf_bytes.startswith(b"%PDF-1.")
    assert len(pdf_bytes) > 5000

