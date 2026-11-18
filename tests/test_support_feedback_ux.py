"""Tests for Support Tickets, Structured Feedback, Product Analytics, Privacy, and Admin RBAC."""
import pytest
from fastapi import HTTPException

from api import server
from src.admin import AdminService
from src.support_feedback import SupportFeedbackStore


def test_support_tickets_isolation_and_admin_rbac(tmp_path):
    sup = SupportFeedbackStore(db_path=str(tmp_path / "support.db"))
    admin = AdminService(db_path=str(tmp_path / "admin.db"))

    # Alice creates a ticket
    t = server.create_support_ticket_endpoint(
        server.SupportTicketCreateRequest(
            category="pdf_issue",
            subject="Erreur PDF sur corridor Lac-Batha",
            description="Le téléchargement affiche une alerte 422.",
            priority="high",
        ),
        owner_id="user:alice",
        sup=sup,
    )
    assert t["status"] == "open"
    assert t["priority"] == "high"

    # Bob cannot see Alice's tickets
    bob_list = server.list_my_support_tickets_endpoint(owner_id="user:bob", sup=sup)
    assert bob_list["tickets"] == []
    with pytest.raises(KeyError):
        sup.get_user_ticket("user:bob", t["ticket_id"])

    # read_only_analyst cannot update ticket status
    with pytest.raises(HTTPException) as exc_ro:
        server.admin_update_ticket_endpoint(
            t["ticket_id"],
            server.AdminTicketUpdateRequest(status="resolved"),
            actor_info=("analyst1", "read_only_analyst"),
            admin=admin,
            sup=sup,
        )
    assert exc_ro.value.status_code == 403

    # support_admin can resolve ticket and it is audited
    updated = server.admin_update_ticket_endpoint(
        t["ticket_id"],
        server.AdminTicketUpdateRequest(status="resolved", priority="normal"),
        actor_info=("sup1", "support_admin"),
        admin=admin,
        sup=sup,
    )
    assert updated["status"] == "resolved"
    assert len(admin.list_audit_logs()) == 1


def test_feedback_and_privacy_conscious_product_analytics(tmp_path):
    sup = SupportFeedbackStore(db_path=str(tmp_path / "support.db"))

    server.submit_feedback_endpoint(
        server.FeedbackSubmitRequest(feature="pdf_quality", rating=5, comment="Très clair et honnête."),
        owner_id="user:alice",
        sup=sup,
    )
    server.submit_feedback_endpoint(
        server.FeedbackSubmitRequest(feature="rag_relevance", rating=4, comment="Bonnes sources."),
        owner_id="user:bob",
        sup=sup,
    )

    # Record product events (private prompt/message keys stripped automatically)
    server.record_product_event_endpoint(
        server.ProductEventRequest(
            event_name="onboarding_completed",
            properties={"language": "fr", "prompt": "SECRET_PROMPT_DO_NOT_STORE"},
        ),
        owner_id="user:alice",
        sup=sup,
    )
    with sup._connect() as conn:
        raw_props = conn.execute("SELECT properties_json FROM product_events").fetchone()[0]
    assert "SECRET_PROMPT_DO_NOT_STORE" not in raw_props

    admin = AdminService(db_path=str(tmp_path / "admin.db"))
    ov = server.admin_support_overview_endpoint(actor_info=("analyst", "read_only_analyst"), admin=admin, sup=sup)
    assert ov["feedback"]["total_count"] == 2
    assert ov["feedback"]["avg_rating"] == 4.5
    assert ov["product_analytics"]["unique_active_users"] == 1
    assert ov["product_analytics"]["events_by_name"]["onboarding_completed"] == 1

