"""Chantier 2 tests: RAG manifest validation & dry-run automation."""
import json
from pathlib import Path

from scripts import build_vector_store as bvs


def test_repo_rag_manifest_is_valid_schema():
    res = bvs.validate_manifest(bvs.MANIFEST_PATH, bvs.DOCS_DIR)
    assert res["errors"] == []
    assert res["status"] in ("ok", "empty")


def test_rag_dry_run_catches_invalid_manifest_and_passes_valid(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "doc1.pdf").write_bytes(b"%PDF-1.4 fake")

    manifest_ok = docs_dir / "manifest.json"
    manifest_ok.write_text(
        json.dumps([{"filename": "doc1.pdf", "titre": "Bulletin Tchad", "editeur": "WFP"}]),
        encoding="utf-8",
    )
    ok_res = bvs.validate_manifest(manifest_ok, docs_dir)
    assert ok_res["status"] == "ok"
    assert ok_res["present_files"] == ["doc1.pdf"]
    assert ok_res["missing_files"] == []
    assert ok_res["errors"] == []

    manifest_bad = docs_dir / "bad.json"
    manifest_bad.write_text(json.dumps([{"filename": "doc1.pdf"}]), encoding="utf-8")
    bad_res = bvs.validate_manifest(manifest_bad, docs_dir)
    assert bad_res["status"] == "invalid"
    assert len(bad_res["errors"]) == 2

