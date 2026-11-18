"""Phase 4 QA tests: RequirementCompliance, DataIntegrity, FinancialValidator, EvidenceVerifier, and PDF gate."""
import copy
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.reports import build_market_study_dossier, validate_market_study_report


def _valid_state(monkeypatch):
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
    ])
    cp = pd.DataFrame([{
        "province": "Lac", "commodity_std": "Millet", "credit_score": 82.0,
        "grade": "A", "ltv_ratio": 0.8, "cv_pct": 8.5, "max_drawdown_pct": 6.0,
    }])
    st = server.build_state_from_gold(fc, cp)
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: []
    return st


def test_successful_validation_and_transparent_scoring(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province="Batha",
        capital_xaf=1_000_000,
        study_context={
            "required_sections": ["SWOT", "PESTEL"],
            "excluded_sections": ["six_month_projection"],
            "budget_and_assumptions": {"capital_xaf": 1_000_000, "reinvest": False, "zero_capex": True},
        },
    )
    qa = dossier["validation"]
    assert qa["can_deliver_pdf"] is True
    assert qa["overall_status"] in ("PASSED", "PASSED_WITH_WARNINGS")
    assert set(qa["dimension_scores"].keys()) == {
        "requirement_compliance",
        "data_quality",
        "financial_consistency",
        "evidence_traceability",
        "report_completeness",
        "methodological_transparency",
    }
    assert len(qa["scoring_methodology"]) == 6


def test_missing_requested_section_and_excluded_section_failures(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=500_000)
    bad = copy.deepcopy(dossier)
    bad["study_context"]["required_sections"] = ["unknown_custom_section"]
    bad["study_context"]["excluded_sections"] = ["market_prices"]

    qa = validate_market_study_report(bad)
    codes = {f["code"] for f in qa["failed_checks"]}
    assert qa["can_deliver_pdf"] is False
    assert qa["overall_status"] == "FAILED"
    assert "MISSING_REQUESTED_SECTION" in codes


def test_incorrect_financial_calculations_blocked(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=500_000)
    bad = copy.deepcopy(dossier)
    bad["business_plan"]["capital_allocation"]["working_capital_xaf"] = 999_999
    bad["business_plan"]["unit_economics"]["net_profit_cycle1_xaf"] = 12_345_678

    qa = validate_market_study_report(bad)
    codes = {f["code"] for f in qa["failed_checks"]}
    assert qa["can_deliver_pdf"] is False
    assert "CAPITAL_ALLOCATION_IMBALANCE" in codes
    assert "CYCLE1_ACCOUNTING_MISMATCH" in codes


def test_duplicate_observations_and_invalid_geography_and_missing_sources(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=500_000)
    bad = copy.deepcopy(dossier)
    bad["dest_province"] = "Lac"  # same as origin
    bad["market_data"]["origin_forecasts"].append(bad["market_data"]["origin_forecasts"][0])
    bad["data_traceability"]["observed_sources"] = "Source primaire non renseignee"

    qa = validate_market_study_report(bad)
    codes = {f["code"] for f in qa["failed_checks"]}
    assert qa["can_deliver_pdf"] is False
    assert "GEOGRAPHIC_DUPLICATE_CORRIDOR" in codes
    assert "DUPLICATE_OBSERVATIONS" in codes
    assert any("Source primaire" in w for w in qa["warnings"])


def test_contradictions_and_unsupported_claims_flagged(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        "Millet",
        "Lac",
        "Batha",
        capital_xaf=500_000,
        study_context={
            "required_sections": ["competitor_analysis"],
            "needs_clarification": True,
            "contradictions": [{"field": "sections", "previous": "PESTEL", "new": "exclude:PESTEL", "message": "conflict"}],
        },
    )
    qa = dossier["validation"]
    assert any("competitor_analysis" in c for c in qa["unsupported_claims"])
    assert any("Contradictions" in w for w in qa["warnings"])


def test_pdf_endpoint_blocks_delivery_on_qa_failure(monkeypatch):
    st = _valid_state(monkeypatch)
    dossier = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=500_000)
    dossier["validation"] = {"can_deliver_pdf": False, "overall_status": "FAILED", "required_corrections": ["Fix capital"]}
    monkeypatch.setattr(server, "_build_study_dossier_or_404", lambda payload, state: dossier)

    req = server.MarketStudyRequest(commodity="Millet", origin_province="Lac", dest_province="Batha", capital_xaf=500_000)
    with pytest.raises(HTTPException) as exc:
        server.generate_market_study_pdf(req, state=st, x_premium_key="pro-key-1234567890")
    assert exc.value.status_code == 422
    assert exc.value.detail["validation"]["overall_status"] == "FAILED"

