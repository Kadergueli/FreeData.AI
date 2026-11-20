"""Upload de documents depuis un téléphone : MIME vide/générique, quota non consommé sur refus."""
import base64

import pytest

from src.security import validate_uploaded_document

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.mark.parametrize("mime", [None, "", "application/octet-stream", "application/x-pdf", "application/pdf"])
def test_pdf_accepted_with_mobile_mime_types(mime):
    out = validate_uploaded_document("Capture d’écran 2026.PDF", PDF, mime_type=mime)
    assert out["extension"] == ".pdf"


def test_csv_android_mime_accepted():
    out = validate_uploaded_document("prix.csv", b"a,b\n1,2\n", mime_type="application/vnd.ms-excel")
    assert out["extension"] == ".csv"


def test_real_wrong_mime_still_rejected():
    with pytest.raises(ValueError):
        validate_uploaded_document("x.pdf", PDF, mime_type="image/png")


def test_octet_stream_does_not_bypass_magic_bytes():
    with pytest.raises(ValueError):
        validate_uploaded_document("x.pdf", b"MZ\x90\x00fake", mime_type="application/octet-stream")


def test_rejected_upload_does_not_consume_rag_quota(tmp_path):
    from api import server
    from src.monetization import SubscriptionStore
    from src.projects import ProjectStore
    from src.user_documents import UserDocumentStore

    subs = SubscriptionStore(db_path=str(tmp_path / "s.db"))
    docs = UserDocumentStore(db_path=str(tmp_path / "d.db"))
    proj = ProjectStore(db_path=str(tmp_path / "p.db"), artifacts_dir=str(tmp_path / "a"))
    owner = "user:" + "q" * 40
    calls = []
    orig = server._consume_user_quota
    server._consume_user_quota = lambda *a, **k: calls.append(a[2])
    try:
        req = server.DocumentValidateRequest(
            filename="photo.jpg", content_base64=base64.b64encode(b"\xff\xd8\xff" + b"0" * 50).decode(), mime_type="image/jpeg"
        )
        with pytest.raises(Exception) as ei:
            server.upload_user_document_endpoint(
                req, owner_id=owner, x_premium_key=None, sub_store=subs, doc_store=docs, project_store=proj
            )
        assert getattr(ei.value, "status_code", None) == 422
        assert calls == []
    finally:
        server._consume_user_quota = orig
