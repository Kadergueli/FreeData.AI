"""Load, concurrency, job-retry, and backup/restoration verification tests."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pandas as pd

from api import server
from src.analytics import AnalyticsService
from src.backup import backup_sqlite_file, verify_sqlite_integrity
from src.monetization import SubscriptionStore
from src.projects import ProjectStore
from src.reports import build_market_study_dossier, render_market_study_pdf
from src.reports.jobs import ReportJobManager


def test_concurrent_analytics_and_pdf_generation_load(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890"))
    fc = pd.DataFrame([
        {
            "source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 210.0,
            "forecast_month": "2026-11", "forecast_t1": 220.0, "ci_low_80": 195.0, "ci_high_80": 245.0, "hist_mae": 18.0,
        },
        {
            "source": "WFP", "province": "Batha", "market_name": "Ati", "commodity_std": "Millet",
            "last_observed_month": "2026-10", "last_observed_price": 340.0,
            "forecast_month": "2026-11", "forecast_t1": 330.0, "ci_low_80": 315.0, "ci_high_80": 385.0, "hist_mae": 22.0,
        },
    ])
    cp = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "ltv_ratio": 0.8, "cv_pct": 8.5, "max_drawdown_pct": 6.0}])
    st = server.build_state_from_gold(fc, cp)
    st["agent"].provider.retrieve_rag_chunks = lambda q, match_count=3: []
    svc = AnalyticsService()

    # 24 concurrent analytics queries
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ana_res = list(pool.map(lambda _: svc.get_regional_comparison(fc, commodity="Millet"), range(24)))
    ana_ms = (time.perf_counter() - t0) * 1000.0
    assert len(ana_res) == 24
    assert all(r["spatial_spread_xaf_kg"] == 130.0 for r in ana_res)
    assert ana_ms < 2000.0

    # 8 concurrent PDF generations
    def _gen_pdf(_):
        d = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=1_000_000)
        return render_market_study_pdf(d)

    t1 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        pdfs = list(pool.map(_gen_pdf, range(8)))
    pdf_ms = (time.perf_counter() - t1) * 1000.0
    assert len(pdfs) == 8
    assert all(p.startswith(b"%PDF-1.") for p in pdfs)
    assert pdf_ms < 10000.0


def test_job_retry_and_sqlite_hot_backup_restoration(tmp_path):
    # 1. Job retry after transient failure
    jobs = ReportJobManager(max_workers=1)
    attempts = {"n": 0}

    def _flaky(progress_cb):
        attempts["n"] += 1
        progress_cb(40)
        if attempts["n"] == 1:
            raise TimeoutError("Transient upstream timeout")
        return {"pdf_bytes": b"%PDF-1.4\nok", "validation": {"overall_status": "PASSED"}, "study_id": "FD-1", "version_number": 1}

    job = jobs.submit("user:alice", _flaky, max_retries=1)
    for _ in range(40):
        st = jobs.get_status("user:alice", job["job_id"])
        if st["status"] in ("failed", "completed"):
            break
        time.sleep(0.02)
    assert st["status"] == "failed"

    retried = jobs.retry_job("user:alice", job["job_id"])
    for _ in range(40):
        st2 = jobs.get_status("user:alice", job["job_id"])
        if st2["status"] == "completed":
            break
        time.sleep(0.02)
    assert st2["status"] == "completed"
    assert jobs.get_pdf("user:alice", job["job_id"]).startswith(b"%PDF-1.4")

    # 2. Concurrent DB writes + hot backup + integrity check
    p_store = ProjectStore(db_path=str(tmp_path / "projects.db"), artifacts_dir=str(tmp_path / "art"))
    s_store = SubscriptionStore(db_path=str(tmp_path / "billing.db"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: p_store.create_project("user:alice", f"LoadProj {i}"), range(10)))
    s_store.admin_update_subscription(actor="admin", target_user_id="user:alice", plan_id="premium")

    bak = backup_sqlite_file(p_store.db_path, tmp_path / "backups")
    assert bak["status"] == "verified"
    assert bak["integrity_ok"] is True
    assert verify_sqlite_integrity(s_store.db_path) is True

