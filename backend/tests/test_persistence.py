"""Persistence and session-lifecycle tests (blueprint Phase 1).

Verifies that data written through the API is actually committed and survives
an engine disposal (backend restart simulation), that request-scoped sessions
roll back uncommitted work on failure, and that errors surface as safe
responses.
"""

from decimal import Decimal

from app.db.session import SessionLocal, engine
from app.models import User, WasteListing
from tests.test_inventory import _listing_payload
from tests.test_marketplace import _auth, client, generator_token


def test_created_listing_is_committed_and_survives_engine_disposal(generator_token):
    response = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    )
    assert response.status_code == 201
    listing_id = response.json()["id"]

    # Simulate a backend restart: dispose pooled connections, then re-query
    # through a brand new session.
    engine.dispose()
    with SessionLocal() as db:
        row = db.get(WasteListing, listing_id)
        assert row is not None
        assert row.title == _listing_payload()["title"]
        db.refresh(row)
        assert Decimal(row.quantity) == Decimal("250.000")


def test_uncommitted_rolls_back_on_session_error():
    # A session-level failure must not leave partial writes behind.
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "generator@recircle.local").first()
        user.full_name = "Rollback Probe"
        db.flush()
        db.rollback()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "generator@recircle.local").first()
        assert user.full_name != "Rollback Probe"


def test_integrity_violation_returns_safe_409(generator_token, monkeypatch):
    # Constraint violations must surface as a consistent conflict response
    # without leaking SQL, constraint names, or driver details.
    from sqlalchemy.exc import IntegrityError

    from app.services import inventory

    def raise_integrity_error(*args, **kwargs):
        raise IntegrityError(
            "INSERT INTO waste_listings ...", {}, Exception('duplicate key value violates unique constraint "uq_secret"')
        )

    monkeypatch.setattr(inventory, "create_listing", raise_integrity_error)
    response = client.post("/api/listings", json=_listing_payload(), headers=_auth(generator_token))
    assert response.status_code == 409
    body = second = response.json()
    assert body["detail"] == "The request conflicts with existing records"
    assert "INSERT" not in str(body)
    assert "constraint" not in str(body).lower()


def test_database_error_returns_safe_500(generator_token, monkeypatch):
    # Unexpected database failures must return a generic 500 with no internals.
    from sqlalchemy.exc import OperationalError

    from app.services import inventory

    def raise_operational_error(*args, **kwargs):
        raise OperationalError("SELECT password_hash FROM users", {}, Exception("connection reset"))

    monkeypatch.setattr(inventory, "create_listing", raise_operational_error)
    response = client.post("/api/listings", json=_listing_payload(), headers=_auth(generator_token))
    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error"}
    assert "SELECT" not in str(body)
    assert "password" not in str(body).lower()
