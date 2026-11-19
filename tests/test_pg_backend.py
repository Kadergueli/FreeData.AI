"""Backend PostgreSQL (Supabase). Ignoré sans TEST_PG_URL ; sans base, seuls les tests purs tournent."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import db
from src.admin import AdminService
from src.monetization import SubscriptionStore
from src.projects.store import ProjectStore
from src.support_feedback import SupportFeedbackStore

PG = os.getenv("TEST_PG_URL", "").strip()
needs_pg = pytest.mark.skipif(not PG, reason="TEST_PG_URL non défini")


def test_translate_placeholders_and_percent():
    assert db._translate("SELECT * FROM t WHERE a = ? AND b LIKE '%x%'") == "SELECT * FROM t WHERE a = %s AND b LIKE '%%x%%'"
    assert "DOUBLE PRECISION" in db._translate_ddl("latency_ms REAL NOT NULL")
    assert "BYTEA" in db._translate_ddl("pdf BLOB NOT NULL")


def test_pgrow_behaves_like_sqlite_row():
    r = db.PgRow((1, "a"), {"x": 0, "y": 1})
    assert r["x"] == 1 and r[1] == "a" and dict(r) == {"x": 1, "y": "a"} and list(r) == [1, "a"]


def test_schema_name_is_validated():
    with pytest.raises(ValueError):
        db.validate_schema('x"; DROP SCHEMA public; --')


def test_explicit_sqlite_path_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x@h/db")
    monkeypatch.delenv("FREEDATA_TEST_ALL_PG", raising=False)
    assert db.resolve_backend(str(tmp_path / "a.db")) is None
    assert db.resolve_backend(None) == "postgresql://x@h/db"


def _schema() -> str:
    return "t_" + uuid.uuid4().hex[:10]


@needs_pg
def test_quota_is_atomic_under_concurrency():
    st = SubscriptionStore(database_url=PG, schema=_schema())
    def hit(_):
        try:
            st.consume_usage_atomic("user:a", "chat_daily", 5, period_key="2026-11-19")
            return 1
        except OverflowError:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = sum(pool.map(hit, range(30)))
    assert ok == 5


@needs_pg
def test_data_survives_a_new_store_instance_and_is_locked_down():
    schema = _schema()
    p1 = ProjectStore(database_url=PG, schema=schema, artifacts_dir="/tmp/_unused_art")
    proj = p1.create_project("user:alice", "Persisté")
    p2 = ProjectStore(database_url=PG, schema=schema, artifacts_dir="/tmp/_unused_art")  # « redémarrage »
    assert p2.get_project("user:alice", proj["project_id"])["name"] == "Persisté"
    with pytest.raises(KeyError):
        p2.get_project("user:bob", proj["project_id"])  # isolation entre propriétaires conservée
    import psycopg2
    with psycopg2.connect(PG) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname=%s AND NOT rowsecurity", (schema,))
        assert cur.fetchone()[0] == 0  # RLS active sur toutes les tables


@needs_pg
def test_pdf_is_stored_in_database_and_deleted_with_project():
    store = ProjectStore(database_url=PG, schema=_schema(), artifacts_dir="/tmp/_unused_art")
    proj = store.create_project("user:alice", "PDF")
    dossier = {"study_context": {}, "validation": {}, "data_traceability": {}, "title": "T"}
    v = store.create_study_version("user:alice", proj["project_id"], study_id=None, dossier=dossier,
                                   generation_params={}, pdf_bytes=b"%PDF-1.4 hello")
    assert v["artifact_available"] is True
    assert store.get_study_version_pdf("user:alice", proj["project_id"], v["study_id"], 1) == b"%PDF-1.4 hello"
    store.delete_project("user:alice", proj["project_id"])
    with pytest.raises(KeyError):
        store.get_study_version_pdf("user:alice", proj["project_id"], v["study_id"], 1)


@needs_pg
def test_support_admin_and_billing_roundtrip():
    schema = _schema()
    sup = SupportFeedbackStore(database_url=PG, schema=schema)
    t = sup.create_ticket("user:alice", category="bug", subject="s", description="d" * 12)
    assert t["ticket_id"].startswith("TKT-")
    sup.submit_feedback("user:alice", feature="chat", rating=4)
    sup.submit_feedback("user:bob", feature="chat", rating=5)
    ov = sup.get_admin_overview()
    assert ov["tickets_by_status"]
    assert ov["feedback"]["total_count"] == 2 and ov["feedback"]["avg_rating"] == 4.5
    adm = AdminService(database_url=PG, schema=schema)
    res = adm.assign_role(actor="root", actor_role="super_admin", target_user_id="user:alice", new_role="support_admin")
    assert res
    bill = SubscriptionStore(database_url=PG, schema=schema)
    bill.admin_update_subscription(actor="root", target_user_id="user:alice", plan_id="premium")
    assert bill.get_subscription("user:alice")["effective_plan_id"] == "premium"
    assert bill.get_audit_logs()[0]["target_user_id"] == "user:alice"
