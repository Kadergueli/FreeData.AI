"""Phase 6 tests: background report jobs, pagination, observability metrics, and latency measurement."""
import time
from dataclasses import replace

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.projects import ProjectStore
from src.reports import build_market_study_dossier, render_market_study_pdf
from src.reports.jobs import ReportJobManager


def test_background_report_job_lifecycle_and_isolation(tmp_path, monkeypatch):
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
    cp = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "ltv_ratio": 0.8, "cv_pct": 8.5, "max_drawdown_pct": 6.0}])
    st = server.build_state_from_gold(fc, cp)
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: []

    jobs = ReportJobManager(max_workers=1)
    store = ProjectStore(db_path=str(tmp_path / "p.db"), artifacts_dir=str(tmp_path / "art"))
    proj = store.create_project("user:alice", "Job Project")

    def _run(progress_cb):
        progress_cb(35)
        d = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=1_000_000)
        progress_cb(75)
        pdf = render_market_study_pdf(d)
        ver = store.create_study_version("user:alice", proj["project_id"], study_id=None, dossier=d, generation_params={"capital_xaf": 1_000_000}, pdf_bytes=pdf)
        return {"pdf_bytes": pdf, "validation": d["validation"], "study_id": ver["study_id"], "version_number": ver["version_number"]}

    job = jobs.submit("user:alice", _run)
    for _ in range(50):
        status = jobs.get_status("user:alice", job["job_id"])
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["progress_pct"] == 100
    assert status["version_number"] == 1
    assert jobs.get_pdf("user:alice", job["job_id"]).startswith(b"%PDF-1.")

    # Cross-user isolation
    with pytest.raises(KeyError):
        jobs.get_status("user:bob", job["job_id"])
    with pytest.raises(KeyError):
        jobs.get_pdf("user:bob", job["job_id"])


def test_project_pagination_and_metrics_auth(tmp_path, monkeypatch):
    store = ProjectStore(db_path=str(tmp_path / "p.db"), artifacts_dir=str(tmp_path / "art"))
    for i in range(5):
        store.create_project("user:alice", f"Projet {i}")

    page1 = store.list_projects("user:alice", limit=2, offset=0)
    page2 = store.list_projects("user:alice", limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["project_id"] != page2[0]["project_id"]

    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="adm-secret"))
    with pytest.raises(HTTPException) as exc:
        server.get_metrics(x_admin_token="wrong")
    assert exc.value.status_code == 403
    metrics = server.get_metrics(x_admin_token="adm-secret")
    assert "total_requests" in metrics
    assert "avg_latency_ms" in metrics

