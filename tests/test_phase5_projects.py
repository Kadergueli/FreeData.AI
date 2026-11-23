"""Phase 5 tests: persistent projects, StudyContext persistence, conversations, study versions, and user isolation."""
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from src.projects import ProjectStore
from src.reports import build_market_study_dossier, render_market_study_pdf


def _make_state(monkeypatch):
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


def test_project_lifecycle_and_restart_persistence(tmp_path):
    db_file = str(tmp_path / "projects.db")
    art_dir = str(tmp_path / "artifacts")
    store1 = ProjectStore(db_path=db_file, artifacts_dir=art_dir)

    created = store1.create_project(
        "user:alice",
        "Négoce Mil Lac-Batha",
        description="Projet commercial",
        study_context={"objectives": ["Rentabilité Cycle 1"], "required_sections": ["SWOT"]},
        idempotency_key="idem-1",
    )
    pid = created["project_id"]
    # Idempotency prevents duplicate creation
    dup = store1.create_project("user:alice", "Négoce Mil Lac-Batha", idempotency_key="idem-1")
    assert dup["project_id"] == pid

    # Conversation & message persistence + context update
    conv = store1.create_conversation("user:alice", pid, title="Cadrage initial")
    store1.add_message(
        "user:alice",
        pid,
        conv["conversation_id"],
        "user",
        "Inclure PESTEL",
        updated_study_context={"objectives": ["Rentabilité Cycle 1"], "required_sections": ["SWOT", "PESTEL"]},
    )

    # Simulate application restart by creating a brand new ProjectStore instance
    store2 = ProjectStore(db_path=db_file, artifacts_dir=art_dir)
    loaded = store2.get_project("user:alice", pid)
    assert loaded["name"] == "Négoce Mil Lac-Batha"
    assert "PESTEL" in loaded["study_context"]["required_sections"]
    msgs = store2.get_conversation_messages("user:alice", pid, conv["conversation_id"])
    assert len(msgs) == 1 and msgs[0]["content"] == "Inclure PESTEL"

    # Rename & archive
    renamed = store2.update_project("user:alice", pid, name="Mil Lac-Batha v2", status="archived")
    assert renamed["name"] == "Mil Lac-Batha v2"
    assert renamed["status"] == "archived"
    assert store2.list_projects("user:alice", include_archived=False) == []
    assert len(store2.list_projects("user:alice", include_archived=True)) == 1


def test_study_versions_comparison_and_missing_artifact(tmp_path, monkeypatch):
    st = _make_state(monkeypatch)
    store = ProjectStore(db_path=str(tmp_path / "projects.db"), artifacts_dir=str(tmp_path / "artifacts"))
    proj = store.create_project("user:alice", "Étude Mil")
    pid = proj["project_id"]

    d1 = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=500_000)
    pdf1 = render_market_study_pdf(d1)
    v1 = store.create_study_version("user:alice", pid, study_id=None, dossier=d1, generation_params={"capital_xaf": 500_000}, pdf_bytes=pdf1)
    assert v1["version_number"] == 1

    d2 = build_market_study_dossier(st["agent"].provider, "Millet", "Lac", "Batha", capital_xaf=1_000_000)
    pdf2 = render_market_study_pdf(d2)
    v2 = store.create_study_version("user:alice", pid, study_id=v1["study_id"], dossier=d2, generation_params={"capital_xaf": 1_000_000}, pdf_bytes=pdf2)
    assert v2["version_number"] == 2

    versions = store.list_study_versions("user:alice", pid, v1["study_id"])
    assert [v["version_number"] for v in versions] == [2, 1]
    assert store.get_study_version_pdf("user:alice", pid, v1["study_id"], 1).startswith(b"%PDF-1.")

    diff = store.compare_study_versions("user:alice", pid, v1["study_id"], 1, 2)
    assert diff["metrics_diff"]["capital_xaf"]["v1"] == 500_000
    assert diff["metrics_diff"]["capital_xaf"]["v2"] == 1_000_000

    # Delete PDF artifact on disk -> FileNotFoundError
    for p in (tmp_path / "artifacts").rglob("*_v1.pdf"):
        p.unlink()
    with pytest.raises(FileNotFoundError):
        store.get_study_version_pdf("user:alice", pid, v1["study_id"], 1)


def test_user_data_isolation_and_auth_checks(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"), artifacts_dir=str(tmp_path / "artifacts"))
    proj = store.create_project("user:alice", "Secret Alice")
    pid = proj["project_id"]

    assert store.list_projects("user:bob") == []
    with pytest.raises(KeyError):
        store.get_project("user:bob", pid)
    with pytest.raises(KeyError):
        store.update_project("user:bob", pid, name="Hijacked")
    with pytest.raises(KeyError):
        store.delete_project("user:bob", pid)

    with pytest.raises(HTTPException) as exc:
        server._require_project_owner(x_user_id=None, x_premium_key=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc_del:
        server.delete_project_endpoint(pid, confirm=False, owner_id="user:alice", store=store)
    assert exc_del.value.status_code == 400

def test_delete_project_removes_all_generated_pdf_artifacts(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    store = ProjectStore(
        db_path=str(tmp_path / "projects.db"),
        artifacts_dir=str(artifacts_dir),
    )
    project = store.create_project("user:alice", "Project with PDFs")
    created = store.create_study_version(
        "user:alice",
        project["project_id"],
        study_id=None,
        dossier={"commodity": "Millet", "origin_province": "Lac", "dest_province": "Batha"},
        generation_params={"capital_xaf": 500000},
        pdf_bytes=b"%PDF-1.4\naccount deletion cleanup test",
    )
    pdf_files = list(artifacts_dir.rglob("*.pdf"))
    assert len(pdf_files) == 1 and pdf_files[0].is_file()

    store.delete_project("user:alice", project["project_id"])

    assert not pdf_files[0].exists()
    assert store.list_projects("user:alice", include_archived=True) == []
