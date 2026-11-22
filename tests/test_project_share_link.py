import time

import pytest
from fastapi import HTTPException

from api import server


class _Store:
    def get_project(self, owner_id, project_id):
        if project_id != "p1":
            raise KeyError("introuvable")
        return {"project_id": "p1", "title": "T", "description": "d", "domain": "agro", "created_at": "x", "studies": []}


def test_routes_registered_once():
    paths = [(r.path, tuple(sorted(r.methods))) for r in server.app.routes if hasattr(r, "methods")]
    assert len(paths) == len(set(paths)), "route dupliquée"
    for p in (
        "/api/v1/projects/{project_id}/share-link",
        "/api/v1/shared/projects/{token}",
        "/api/v1/agro/field-assessment/{assessment_id}/credit-passport",
        "/api/v1/admin/ai/benchmark/{job_id}/report",
    ):
        assert any(path == p for path, _ in paths), p


def test_share_link_roundtrip_and_tamper(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "x" * 32)
    out = server.create_project_share_link_endpoint("p1", ttl_hours=1, owner_id="u1", store=_Store())
    token = out["share_token"]
    assert server.get_shared_project_endpoint(token, store=_Store())["read_only"] is True
    b64, sig = token.split(".")
    with pytest.raises(HTTPException) as e:
        server.get_shared_project_endpoint(b64 + "." + "0" * len(sig), store=_Store())
    assert e.value.status_code == 403


def test_share_link_expired(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "x" * 32)
    token = server.create_project_share_link_endpoint("p1", ttl_hours=1, owner_id="u1", store=_Store())["share_token"]
    real = time.time
    monkeypatch.setattr(server.time, "time", lambda: real() + 7200)
    with pytest.raises(HTTPException) as e:
        server.get_shared_project_endpoint(token, store=_Store())
    assert e.value.status_code == 410


def test_share_link_requires_secret(monkeypatch):
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(HTTPException) as e:
        server.create_project_share_link_endpoint("p1", ttl_hours=1, owner_id="u1", store=_Store())
    assert e.value.status_code == 503
