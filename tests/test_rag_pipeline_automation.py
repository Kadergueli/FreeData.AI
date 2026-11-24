"""Chantier 2 tests: RAG manifest validation & dry-run automation."""
import json
from pathlib import Path

from scripts import build_vector_store as bvs


def test_repo_rag_manifest_uses_first_party_corpus_and_defers_missing_pam_source():
    res = bvs.validate_manifest(bvs.MANIFEST_PATH, bvs.DOCS_DIR)
    assert res["status"] == "ok"
    assert res["missing_files"] == []
    assert res["deferred_files"] == ["pam_tchad_2026_06.pdf"]
    assert len(res["present_files"]) == 3
    assert res["errors"] == []


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


def test_rag_manifest_rejects_path_traversal_and_non_pdf_files(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 fake")
    (docs_dir / "notes.csv").write_text("rapport marche agricole", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps([
            {"filename": "../outside.pdf", "titre": "Outside", "editeur": "WFP"},
            {"filename": "notes.csv", "titre": "Notes", "editeur": "WFP"},
        ]),
        encoding="utf-8",
    )

    result = bvs.validate_manifest(manifest, docs_dir)
    assert result["status"] == "invalid"
    assert len(result["errors"]) == 2
    assert result["present_files"] == []


def test_embedding_response_requires_exact_count_dimension_and_finite_values(monkeypatch):
    from dataclasses import replace
    import pytest
    from scripts import build_vector_store as bvs

    monkeypatch.setattr(
        bvs,
        "settings",
        replace(bvs.settings, embed_api_key="test", embed_base_url="https://embeddings.invalid", embed_model="jina-embeddings-v3"),
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1] * 1023}]}

    monkeypatch.setattr(bvs.requests, "post", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(RuntimeError, match="1024"):
        bvs.get_embeddings(["extrait"])


def test_public_rag_migration_enforces_approved_document_visibility():
    migration = (bvs.DOCS_DIR.parent / "sql" / "16_public_rag.sql").read_text(encoding="utf-8")
    assert "vector(1024)" in migration
    assert "SECURITY INVOKER" in migration
    assert "redistribution_ok = true" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "GRANT ALL PRIVILEGES" in migration
    assert "match_chunks" in migration



def test_manifest_allows_deferred_missing_pdf_and_indexes_markdown(tmp_path):
    docs_dir = tmp_path / "docs"
    (docs_dir / "knowledge").mkdir(parents=True)
    (docs_dir / "knowledge" / "method.md").write_text(
        "# Méthode\nLes marges distinguent le prix brut et les coûts opérationnels.",
        encoding="utf-8",
    )
    manifest = docs_dir / "manifest.json"
    manifest.write_text(
        json.dumps([
            {"filename": "pam_missing.pdf", "titre": "PAM", "editeur": "WFP", "enabled": False},
            {"filename": "knowledge/method.md", "titre": "Méthode", "editeur": "FreeData.td", "enabled": True},
        ]),
        encoding="utf-8",
    )

    result = bvs.validate_manifest(manifest, docs_dir)
    assert result["status"] == "ok"
    assert result["deferred_files"] == ["pam_missing.pdf"]
    assert result["present_files"] == ["knowledge/method.md"]
    assert result["missing_files"] == []
    assert result["errors"] == []
