from decimal import Decimal
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Organization

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_offer_requires_auth():
    response = client.post("/api/offers", json={})
    assert response.status_code == 401


def test_transactions_require_auth():
    assert client.get("/api/transactions").status_code == 401
    assert client.get("/api/esg/dashboard").status_code == 401


def test_buyer_creates_offer_then_seller_accepts_and_recovery_completes():
    buyer = _login("buyer@recircle.local")
    generator = _login("generator@recircle.local")

    # A fresh listing per run keeps this test safe to rerun on a shared DB
    created_listing = client.post(
        "/api/listings",
        json={
            "title": "Trade Workflow Probe Steel Scrap",
            "description": "Temporary listing for the offer -> transaction -> recovery flow.",
            "category": "metals",
            "quantity": "400.000",
            "unit": "kg",
            "city": "Pune",
            "region": "Maharashtra",
        },
        headers=_auth(generator),
    )
    assert created_listing.status_code == 201, created_listing.text
    listing_id = created_listing.json()["id"]
    activated = client.post(
        f"/api/listings/{listing_id}/activate", headers=_auth(generator)
    )
    assert activated.status_code == 200

    with SessionLocal() as db:
        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        from app.models import MaterialRequirement, WasteListing

        listing_row = db.get(WasteListing, uuid.UUID(listing_id))
        requirement_row = db.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.organization_id == buyer_org.id,
                MaterialRequirement.category == "metals",
            )
        )
        requirement_id = str(requirement_row.id)
        listing_db_id = listing_row.id

    created = client.post(
        "/api/offers",
        json={
            "listing_id": listing_id,
            "requirement_id": requirement_id,
            "quantity": "400.000",
            "price_per_unit": "19.50",
            "message": "test offer",
        },
        headers=_auth(buyer),
    )
    assert created.status_code == 201, created.text
    offer = created.json()
    assert offer["status"] == "pending"
    offer_id = offer["id"]

    # Only the listing's organization can accept
    refused = client.post(f"/api/offers/{offer_id}/accept", headers=_auth(buyer))
    assert refused.status_code == 403

    accepted = client.post(f"/api/offers/{offer_id}/accept", headers=_auth(generator))
    assert accepted.status_code == 200, accepted.text
    transaction = accepted.json()
    assert transaction["status"] == "agreed"
    assert Decimal(transaction["agreed_quantity"]) == Decimal("400.000")
    transaction_id = transaction["id"]

    # Accepting again fails
    again = client.post(f"/api/offers/{offer_id}/accept", headers=_auth(generator))
    assert again.status_code == 409

    # Listings move to matched
    with SessionLocal() as db:
        from app.models import WasteListing

        row = db.get(WasteListing, listing_db_id)
        assert row.status == "matched"

    # Recovery can only be recorded once
    recovery = client.post(
        f"/api/transactions/{transaction_id}/recovery",
        json={
            "recovered_quantity": "400.000",
            "unit": "kg",
            "recovery_route": "recycle",
            "calculation_notes": "test recovery outcome",
        },
        headers=_auth(buyer),
    )
    assert recovery.status_code == 201, recovery.text
    record = recovery.json()
    assert record["verification_status"] == "unverified"
    recovery_id = record["id"]

    duplicate = client.post(
        f"/api/transactions/{transaction_id}/recovery",
        json={
            "recovered_quantity": "400.000",
            "unit": "kg",
            "recovery_route": "recycle",
        },
        headers=_auth(buyer),
    )
    assert duplicate.status_code == 409

    admin = _login("admin@recircle.local")
    verified = client.post(
        f"/api/recovery-records/{recovery_id}/verify", headers=_auth(admin)
    )
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"

    # Only platform admins may verify
    buyer_verify = client.post(
        f"/api/recovery-records/{recovery_id}/verify", headers=_auth(buyer)
    )
    assert buyer_verify.status_code in (403, 409)

    # Transaction is completed now
    detail = client.get(f"/api/transactions/{transaction_id}", headers=_auth(buyer))
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["completed_at"] is not None

    # Cross-organization access is forbidden: a third org cannot see it.
    # (Only two demo orgs exist; the platform admin org is not a party.)
    admin_list = client.get("/api/transactions", headers=_auth(admin))
    assert admin_list.status_code == 200
    assert all(
        item["id"] != transaction_id for item in admin_list.json()["items"]
    )


def test_offer_on_inactive_listing_conflicts():
    buyer = _login("buyer@recircle.local")
    with SessionLocal() as db:
        from app.models import MaterialRequirement, WasteListing

        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        draft = db.scalar(
            select(WasteListing).where(WasteListing.title == "Wood Pallet Offcuts")
        )
        requirement = db.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.organization_id == buyer_org.id
            )
        )
    response = client.post(
        "/api/offers",
        json={
            "listing_id": str(draft.id),
            "requirement_id": str(requirement.id),
            "quantity": "1.000",
        },
        headers=_auth(buyer),
    )
    assert response.status_code == 409


def test_offer_unit_mismatch_rejected():
    buyer = _login("buyer@recircle.local")
    generator = _login("generator@recircle.local")
    created = client.post(
        "/api/listings",
        json={
            "title": "Unit Mismatch Probe Liquid",
            "description": "Temporary listing for unit-mismatch validation.",
            "category": "chemicals",
            "quantity": "300.000",
            "unit": "litre",
            "city": "Nashik",
        },
        headers=_auth(generator),
    )
    assert created.status_code == 201
    listing_id = created.json()["id"]
    client.post(f"/api/listings/{listing_id}/activate", headers=_auth(generator))

    with SessionLocal() as db:
        from app.models import MaterialRequirement, Organization

        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        requirement = db.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.organization_id == buyer_org.id
            )
        )
        requirement_id = str(requirement.id)

    response = client.post(
        "/api/offers",
        json={
            "listing_id": listing_id,
            "requirement_id": requirement_id,
            "quantity": "100.000",
        },
        headers=_auth(buyer),
    )
    assert response.status_code == 422
    assert "Unit mismatch" in response.json()["detail"]


def test_create_offer_requires_requirement_ownership():
    generator = _login("generator@recircle.local")
    with SessionLocal() as db:
        from app.models import MaterialRequirement, WasteListing

        listing = db.scalar(
            select(WasteListing).where(WasteListing.title == "Clear PET Plastic Flakes")
        )
        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        requirement = db.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.organization_id == buyer_org.id
            )
        )
    response = client.post(
        "/api/offers",
        json={
            "listing_id": str(listing.id),
            "requirement_id": str(requirement.id),
            "quantity": "10.000",
        },
        headers=_auth(generator),
    )
    assert response.status_code == 403


def test_negative_quantity_rejected():
    buyer = _login("buyer@recircle.local")
    with SessionLocal() as db:
        from app.models import MaterialRequirement, Organization, WasteListing

        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        listing = db.scalar(
            select(WasteListing).where(WasteListing.title == "Clean Cardboard Sheets")
        )
        requirement = db.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.organization_id == buyer_org.id
            )
        )
    response = client.post(
        "/api/offers",
        json={
            "listing_id": str(listing.id),
            "requirement_id": str(requirement.id),
            "quantity": "0",
        },
        headers=_auth(buyer),
    )
    assert response.status_code == 422
