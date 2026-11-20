"""Jetons administrateur par personne : rôle et acteur viennent du jeton, jamais des en-têtes."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from api import server

TOK_ANA = "analyst-token-" + "a" * 12
TOK_SUP = "support-token-" + "s" * 12
TOK_SUPER = "super-token--" + "z" * 12
LEGACY = "legacy-root-token-" + "l" * 8


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setattr(
        server, "settings",
        replace(server.settings, admin_token=LEGACY,
                admin_tokens=f"amina:read_only_analyst:{TOK_ANA};moussa:support_admin:{TOK_SUP}\nomar:super_admin:{TOK_SUPER}"),
    )


def test_identity_comes_from_token(creds):
    assert server._resolve_admin(TOK_ANA) == ("amina", "read_only_analyst")
    assert server._resolve_admin(TOK_SUP) == ("moussa", "support_admin")
    assert server._resolve_admin(TOK_SUPER) == ("omar", "super_admin")
    assert server._resolve_admin(LEGACY) == ("root_admin", "super_admin")
    assert server._resolve_admin("nope") is None
    assert server._resolve_admin(None) is None
    assert server._resolve_admin("") is None


def test_headers_cannot_forge_role_or_actor(creds):
    # Même si un client envoie X-Admin-Role: super_admin, seul le jeton compte.
    assert server._require_admin_actor(x_admin_token=TOK_ANA) == ("amina", "read_only_analyst")
    with pytest.raises(TypeError):
        server._require_admin_actor(x_admin_token=TOK_ANA, x_admin_role="super_admin")  # type: ignore[call-arg]


def test_permission_enforced_per_role(creds):
    assert server._require_admin_token(TOK_ANA, "read_overview") == ("amina", "read_only_analyst")
    with pytest.raises(HTTPException) as e:
        server._require_admin_token(TOK_ANA, "manage_system")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        server._require_admin_token(TOK_SUP, "manage_system")
    assert e.value.status_code == 403
    assert server._require_admin_token(TOK_SUP, "manage_subscriptions")[0] == "moussa"
    assert server._require_admin_token(TOK_SUPER, "manage_system")[1] == "super_admin"


def test_invalid_entries_are_ignored(monkeypatch):
    monkeypatch.setattr(
        server, "settings",
        replace(server.settings, admin_token="",
                admin_tokens=f"bad:unknown_role:{TOK_ANA};short:super_admin:abc;x y:super_admin:{TOK_SUP};ok:platform_admin:{TOK_SUPER}"),
    )
    assert [c[0] for c in server._admin_credentials()] == ["ok"]


def test_disabled_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, admin_token="", admin_tokens=""))
    with pytest.raises(HTTPException) as e:
        server._require_admin_token("anything", "read_overview")
    assert e.value.status_code == 503


def test_http_role_is_enforced_despite_forged_headers(creds):
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    forged = {"X-Admin-Role": "super_admin", "X-Admin-Actor": "ceo"}
    # Analyste en lecture seule : /metrics (read_overview) OK, /refresh (manage_system) refusé.
    assert c.get("/api/v1/metrics", headers={"X-Admin-Token": TOK_ANA, **forged}).status_code == 200
    assert c.post("/api/v1/refresh", headers={"X-Admin-Token": TOK_ANA, **forged}).status_code == 403
    assert c.get("/api/v1/metrics", headers={"X-Admin-Token": "wrong-token-123456789"}).status_code == 403


@pytest.fixture
def admin_db(monkeypatch, tmp_path):
    from src.admin import AdminService
    svc = AdminService(db_path=str(tmp_path / "admin.db"))
    monkeypatch.setattr(server, "_ADMIN_SERVICE", svc)
    return svc


def test_assigned_role_can_restrict_a_token_but_never_elevate(creds, admin_db):
    # Rétrogradation : le jeton « support_admin » de moussa devient lecture seule
    admin_db.assign_role(actor="omar", actor_role="super_admin", target_user_id="moussa", new_role="read_only_analyst")
    assert server._resolve_admin(TOK_SUP) == ("moussa", "read_only_analyst")
    # Élévation impossible : un rôle plus élevé en base ne change pas le jeton lecture seule
    admin_db.assign_role(actor="omar", actor_role="super_admin", target_user_id="amina", new_role="super_admin")
    assert server._resolve_admin(TOK_ANA) == ("amina", "read_only_analyst")


def test_assigning_user_role_revokes_a_leaked_token(creds, admin_db):
    admin_db.assign_role(actor="omar", actor_role="super_admin", target_user_id="moussa", new_role="user")
    with pytest.raises(HTTPException) as e:
        server._require_admin_token(TOK_SUP, "read_overview")
    assert e.value.status_code == 403 and "révoqué" in e.value.detail


def test_admin_cannot_change_own_role(creds, admin_db):
    with pytest.raises(ValueError):
        admin_db.assign_role(actor="omar", actor_role="super_admin", target_user_id="omar", new_role="user")
