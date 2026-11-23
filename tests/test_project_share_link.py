import time

import pytest
from fastapi import HTTPException

from api import server


class _Store:
    def get_project(self, owner_id, project_id):
        if project_id != "p1":
            raise KeyError("introuvable")
        return {"project_id": "p1", "name": "T", "description": "d", "created_at": "x", "studies": []}


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


class _StoreWithXss:
    def get_project(self, owner_id, project_id):
        return {
            "project_id": "p1",
            "name": "<script>alert(1)</script>Maïs",
            "description": "d & <b>x</b>",
            "created_at": "x",
            "studies": [{"study_id": "s1", "title": "<img src=x onerror=1>", "commodity": "Mil", "latest_version": 2}],
        }


def test_shared_project_returns_name_and_title(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "x" * 32)
    token = server.create_project_share_link_endpoint("p1", ttl_hours=1, owner_id="u1", store=_Store())["share_token"]
    out = server.get_shared_project_endpoint(token, store=_Store())
    assert out["name"] == "T" and out["title"] == "T"
    assert "domain" not in out


def test_shared_project_html_view_is_escaped_and_locked_down(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTH_SECRET", "x" * 32)
    server.app.dependency_overrides[server.get_project_store] = lambda: _StoreWithXss()
    try:
        token = server.create_project_share_link_endpoint("p1", ttl_hours=1, owner_id="u1", store=_Store())["share_token"]
        c = TestClient(server.app)
        html_resp = c.get(f"/api/v1/shared/projects/{token}", headers={"Accept": "text/html"})
        assert html_resp.status_code == 200
        assert html_resp.headers["content-type"].startswith("text/html")
        assert "default-src 'none'" in html_resp.headers["content-security-policy"]
        assert "<script>" not in html_resp.text and "<img" not in html_resp.text
        assert "&lt;script&gt;" in html_resp.text
        json_resp = c.get(f"/api/v1/shared/projects/{token}", headers={"Accept": "application/json"})
        assert json_resp.json()["read_only"] is True
    finally:
        server.app.dependency_overrides.clear()
