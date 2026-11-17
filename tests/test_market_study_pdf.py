"""Tests pour le générateur d'études de marché & PDF PRO (zéro hallucination, accès PRO strict)."""
from dataclasses import replace

import pandas as pd
from fastapi.testclient import TestClient

from api import server


def _setup_state(monkeypatch, premium_keys: str = "pro-key-1234567890"):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys=premium_keys))
    fc = pd.DataFrame([
        {
            "source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 210.0, "forecast_month": "2026-11",
            "forecast_t1": 220.0, "ci_low_80": 195.0, "ci_high_80": 245.0, "hist_mae": 18.0,
        },
        {
            "source": "WFP", "province": "N'Djamena", "market_name": "Dembe", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 340.0, "forecast_month": "2026-11",
            "forecast_t1": 350.0, "ci_low_80": 315.0, "ci_high_80": 385.0, "hist_mae": 22.0,
        },
    ])
    cp = pd.DataFrame([{
        "province": "Lac", "commodity_std": "Millet", "credit_score": 82.0,
        "grade": "A", "ltv_ratio": 0.8, "cv_pct": 8.5, "max_drawdown_pct": 6.0,
    }])
    server.STATE.clear()
    state = server.build_state_from_gold(fc, cp)
    monkeypatch.setattr(
        state["agent"].provider,
        "retrieve_rag_chunks",
        lambda q, match_count=3: [{"titre": "Bulletin PAM Tchad", "editeur": "WFP", "page": 4, "url_source": "https://wfp.org"}],
    )
    server.STATE.update(state)


def test_market_study_and_pdf_require_premium_key(monkeypatch):
    try:
        payload = {
            "commodity": "Millet",
            "origin_province": "Lac",
            "dest_province": "N'Djamena",
            "capital_xaf": 1_000_000,
            "transport_cost_per_kg": 35.0,
            "user_instructions": ["Sans produits périssables"],
        }
        _setup_state(monkeypatch, premium_keys="")
        c = TestClient(server.app)
        assert c.post("/api/v1/reports/market-study", json=payload).status_code == 503
        assert c.post("/api/v1/reports/market-study/pdf", json=payload).status_code == 503

        _setup_state(monkeypatch, premium_keys="pro-key-1234567890")
        assert c.post("/api/v1/reports/market-study", json=payload).status_code == 403
        assert c.post("/api/v1/reports/market-study/pdf", json=payload, headers={"X-Premium-Key": "wrong"}).status_code == 403

        hdr = {"X-Premium-Key": "pro-key-1234567890"}
        r_json = c.post("/api/v1/reports/market-study", json=payload, headers=hdr)
        assert r_json.status_code == 200
        dossier = r_json.json()
        assert dossier["provenance"]["buy_price_per_kg"] == "retrieved_from_dataset"
        assert dossier["provenance"]["capital_xaf"] == "user_provided"
        assert [s["name"] for s in dossier["scenarios"]] == ["Prudent", "Central", "Favorable"]
        assert any("volumes de demande" in g.lower() for g in dossier["data_gaps"])

        r_pdf = c.post("/api/v1/reports/market-study/pdf", json=payload, headers=hdr)
        assert r_pdf.status_code == 200
        assert r_pdf.headers["content-type"] == "application/pdf"
        assert r_pdf.content.startswith(b"%PDF-1.")
        assert len(r_pdf.content) > 1500
    finally:
        server.STATE.clear()

