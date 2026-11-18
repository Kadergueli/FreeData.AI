"""Phase 2 tests: end-to-end StudyContext -> MarketStudyRequest -> StudyBuilder -> PDF."""
from dataclasses import replace

import pandas as pd
import pytest

from api import server
from src.ai_agent import extract_client_state
from src.reports import build_market_study_dossier, render_market_study_pdf


def _make_state(monkeypatch, *, with_dest: bool = True, with_passport: bool = True):
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
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: []
    return st


def test_phase2_context_transmission_and_dynamic_sections(monkeypatch):
    st = _make_state(monkeypatch)
    history = [
        {
            "role": "user",
            "content": "Négoce de mil de Lac vers N'Djamena avec 500 000 XAF, promoteur : Moussa Mahamat, sans équipement (CAPEX = 0), BFR constant.",
        },
        {"role": "assistant", "content": "Noté."},
        {
            "role": "user",
            "content": "Inclure SWOT, PESTEL, analyse concurrentielle et recommandations opérationnelles pour les restaurateurs.",
        },
        {"role": "assistant", "content": "Noté."},
    ]
    for i in range(8):
        history.append({"role": "user", "content": f"Question {i}"})
        history.append({"role": "assistant", "content": f"Réponse {i}"})

    client_state = extract_client_state(history, "Finalement budget 1 000 000 XAF et exclure projection 6 mois.", provider=st["agent"].provider)
    study_ctx = client_state["study_context"]

    req = server.MarketStudyRequest(
        commodity="Millet",
        origin_province="Lac",
        dest_province="N'Djamena",
        capital_xaf=1_000_000,
        study_context=study_ctx,
    )
    dossier = server._build_study_dossier_or_404(req, st)

    assert dossier["promoter_name"] == "Moussa Mahamat"
    assert dossier["business_plan"]["capital_allocation"]["capex_equipment_xaf"] == 0
    assert dossier["business_plan"]["capital_allocation"]["working_capital_xaf"] == 880_000
    assert dossier["business_plan"]["unit_economics"]["reinvest_enabled"] is False
    assert "SWOT" in dossier["requirement_compliance"]["requested_sections"]
    assert "PESTEL" in dossier["requirement_compliance"]["requested_sections"]
    assert "competitor_analysis" in dossier["requirement_compliance"]["unsupported_sections"]
    assert "six_month_projection" in dossier["requirement_compliance"]["excluded_sections"]

    pdf_bytes = render_market_study_pdf(dossier)
    assert pdf_bytes.startswith(b"%PDF-1.")
    assert len(pdf_bytes) > 5000


def test_phase2_backward_compatible_without_study_context(monkeypatch):
    st = _make_state(monkeypatch)
    req = server.MarketStudyRequest(
        commodity="Millet",
        origin_province="Lac",
        dest_province="N'Djamena",
        capital_xaf=500_000,
    )
    dossier = server._build_study_dossier_or_404(req, st)
    assert dossier["promoter_name"] == "Non précisé"
    assert dossier["business_plan"]["capital_allocation"]["working_capital_xaf"] == 400_000
    pdf_bytes = render_market_study_pdf(dossier)
    assert pdf_bytes.startswith(b"%PDF-1.")


def test_phase2_incomplete_data_and_missing_market_data(monkeypatch):
    st = _make_state(monkeypatch, with_dest=False, with_passport=False)
    dossier = build_market_study_dossier(
        st["agent"].provider,
        commodity="Millet",
        origin_province="Lac",
        dest_province=None,
        capital_xaf=250_000,
    )
    assert dossier["provenance"]["market_stability_index"] == "unavailable"
    pdf_bytes = render_market_study_pdf(dossier)
    assert pdf_bytes.startswith(b"%PDF-1.")

    with pytest.raises(ValueError):
        build_market_study_dossier(
            st["agent"].provider,
            commodity="Millet",
            origin_province="ProvinceInexistante",
            capital_xaf=250_000,
        )

