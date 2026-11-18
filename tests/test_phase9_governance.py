"""Phase 9 tests: licensing registry, redistribution blocks, lineage, privacy deletion, AI eval, and admin audit."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server
from src.ai_eval import run_ai_evaluation_suite
from src.governance import LicenseEntry, LicensingRegistry, PrivacyController, build_default_lineage
from src.projects import ProjectStore


def test_missing_and_incompatible_licenses_block_redistribution():
    reg = LicensingRegistry()
    # Unclear licensing on raw table_public -> blocked
    assert reg.check_redistribution_allowed("table_public") is False
    with pytest.raises(PermissionError):
        reg.assert_redistribution_allowed("table_public")

    # Restricted PRO table -> blocked
    assert reg.check_redistribution_allowed("table_ml_anomalies") is False

    # Missing dataset -> blocked
    assert reg.check_redistribution_allowed("unknown_dataset") is False
    with pytest.raises(PermissionError):
        reg.assert_redistribution_allowed("unknown_dataset")

    # Attribution-required approved dataset -> allowed + attribution preserved
    assert reg.check_redistribution_allowed("table_ml_forecasts") is True
    notices = reg.get_attribution_notices(["table_ml_forecasts", "table_public"])
    assert len(notices) == 2


def test_lineage_and_governance_admin_workflow(monkeypatch):
    lineage = build_default_lineage()
    assert len(lineage) >= 3
    assert lineage[0]["original_dataset_id"] == "table_public"
    assert lineage[1]["original_dataset_id"] == "v_clean_markets"

    reg = LicensingRegistry()
    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="adm-token-99"))

    # Unauthorized admin call -> 403
    with pytest.raises(HTTPException) as exc:
        server.governance_admin_decision_endpoint(
            "table_ml_forecasts",
            server.GovernanceDecisionRequest(action="suspend_dataset", reason="Audit"),
            x_admin_token="wrong",
            registry=reg,
        )
    assert exc.value.status_code == 403

    # Authorized suspension blocks redistribution and records audit log
    res = server.governance_admin_decision_endpoint(
        "table_ml_forecasts",
        server.GovernanceDecisionRequest(action="suspend_dataset", reason="Quality review"),
        x_admin_token="adm-token-99",
        registry=reg,
    )
    assert res["entry"]["publication_status"] == "suspended"
    assert reg.check_redistribution_allowed("table_ml_forecasts") is False
    assert len(reg.get_audit_log()) == 1


def test_privacy_redaction_and_user_data_deletion(tmp_path):
    redacted = PrivacyController.redact_sensitive_text("Contact alice@example.com with gsk_1234567890abcdef")
    assert "alice@example.com" not in redacted
    assert "gsk_1234567890abcdef" not in redacted

    store = ProjectStore(db_path=str(tmp_path / "p.db"), artifacts_dir=str(tmp_path / "art"))
    p_a = store.create_project("user:alice", "Alice Proj")
    p_b = store.create_project("user:bob", "Bob Proj")
    store.create_study_version(
        "user:alice",
        p_a["project_id"],
        study_id=None,
        dossier={"commodity": "Millet", "origin_province": "Lac"},
        generation_params={},
        pdf_bytes=b"%PDF-1.4\n...",
    )

    out = PrivacyController.delete_user_data(store, "user:alice")
    assert out["deleted_projects"] == 1
    assert out["deleted_artifacts_dir"] is True
    assert store.list_projects("user:alice", include_archived=True) == []
    # Bob's data remains untouched
    assert len(store.list_projects("user:bob", include_archived=True)) == 1


def test_deterministic_ai_evaluation_suite():
    eval_res = run_ai_evaluation_suite()
    assert eval_res["total_checks"] == 5
    assert eval_res["failed_checks"] == 0
    assert eval_res["pass_rate_pct"] == 100.0

