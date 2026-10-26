"""Material Passport foundation tests (blueprint Phase 3 / §4.1)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import MaterialPassport

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "ReCircleDemo123!"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_listing(token: str, title: str, activate: bool = True) -> str:
    response = client.post(
        "/api/listings",
        json={
            "title": title,
            "description": "Passport test listing description",
            "category": "metals",
            "material_name": "Copper wire",
            "composition": "Pure copper",
            "grade": None,
            "condition": "Stripped",
            "quantity": "50.000",
            "unit": "kg",
            "city": "Pune",
            "region": "Maharashtra",
        },
        headers=_headers(token),
    )
    assert response.status_code == 201
    listing_id = response.json()["id"]
    if activate:
        activate_response = client.post(
            f"/api/listings/{listing_id}/activate", headers=_headers(token)
        )
        assert activate_response.status_code == 200
    return listing_id


def test_passport_is_created_from_listing_with_provenance():
    token = _login("generator@recircle.local")
    listing_id = _create_listing(token, "Passport Copper Creation")

    response = client.post(
        f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["status"] == "active"
    assert body["review_status"] == "unreviewed"

    attrs = body["attributes"]
    assert attrs["material_name"]["value"] == "Copper wire"
    assert attrs["material_name"]["provenance"] == "user_provided"
    # Unknown values are unknown, never zero or fabricated.
    assert attrs["grade"]["value"] is None
    assert attrs["grade"]["provenance"] == "unverified"


def test_passport_cannot_be_created_twice():
    token = _login("generator@recircle.local")
    listing_id = _create_listing(token, "Passport Duplicate Create")
    first = client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token))
    assert first.status_code == 201
    second = client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token))
    assert second.status_code == 409


def test_passport_edit_creates_new_version_and_supersedes_old():
    token = _login("generator@recircle.local")
    listing_id = _create_listing(token, "Passport Versioning")
    client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token))

    response = client.patch(
        f"/api/listings/{listing_id}/passport",
        json={
            "possible_applications": ["Cable manufacturing", "Conductive fillers"],
            "suitable_industries": ["Electrical equipment"],
            "candidate_pathways": ["recycle", "reuse"],
        },
        headers=_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["possible_applications"] == ["Cable manufacturing", "Conductive fillers"]
    assert body["review_status"] == "unreviewed"

    # The active passport is version 2; version 1 is superseded, not deleted.
    active = client.get(f"/api/listings/{listing_id}/passport", headers=_headers(token))
    assert active.json()["version"] == 2
    with SessionLocal() as db:
        rows = db.scalars(
            select(MaterialPassport)
            .where(MaterialPassport.listing_id == listing_id)
            .order_by(MaterialPassport.version)
        ).all()
        assert len(rows) == 2
        assert rows[0].version == 1 and rows[0].status == "superseded"
        assert rows[1].version == 2 and rows[1].status == "active"


def test_passport_review_flow_records_reviewer():
    token = _login("generator@recircle.local")
    listing_id = _create_listing(token, "Passport Review Flow")
    client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token))

    response = client.post(
        f"/api/listings/{listing_id}/passport/review",
        json={"review_status": "reviewed"},
        headers=_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "reviewed"
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None

    unreview = client.post(
        f"/api/listings/{listing_id}/passport/review",
        json={"review_status": "unreviewed"},
        headers=_headers(token),
    )
    assert unreview.status_code == 200
    assert unreview.json()["review_status"] == "unreviewed"
    assert unreview.json()["reviewed_by"] is None


def test_passport_requires_ownership():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")
    listing_id = _create_listing(generator, "Passport Ownership")
    client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(generator))

    assert (
        client.get(f"/api/listings/{listing_id}/passport", headers=_headers(buyer)).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/listings/{listing_id}/passport",
            json={"notes": "hijack"},
            headers=_headers(buyer),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/listings/{listing_id}/passport/review",
            json={"review_status": "reviewed"},
            headers=_headers(buyer),
        ).status_code
        == 403
    )
    assert client.get(f"/api/listings/{listing_id}/passport").status_code == 401


def test_public_marketplace_passport_only_for_active_listings_with_passport():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")

    # Draft listing: passport exists but is not exposed publicly.
    draft_id = _create_listing(generator, "Passport Public Draft", activate=False)
    client.post(f"/api/listings/{draft_id}/passport", json={}, headers=_headers(generator))
    assert (
        client.get(
            f"/api/marketplace/listings/{draft_id}/passport", headers=_headers(buyer)
        ).status_code
        == 404
    )

    # Active listing with passport: exposed with provenance intact.
    active_id = _create_listing(generator, "Passport Public Active")
    client.post(f"/api/listings/{active_id}/passport", json={}, headers=_headers(generator))
    response = client.get(
        f"/api/marketplace/listings/{active_id}/passport", headers=_headers(buyer)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["attributes"]["material_name"]["provenance"] == "user_provided"
    assert body["review_status"] == "unreviewed"

    # Archiving the listing hides the passport again.
    client.post(f"/api/listings/{active_id}/archive", headers=_headers(generator))
    assert (
        client.get(
            f"/api/marketplace/listings/{active_id}/passport", headers=_headers(buyer)
        ).status_code
        == 404
    )


def test_passport_provenance_values_are_validated():
    token = _login("generator@recircle.local")
    listing_id = _create_listing(token, "Passport Provenance Validation")
    client.post(f"/api/listings/{listing_id}/passport", json={}, headers=_headers(token))

    response = client.patch(
        f"/api/listings/{listing_id}/passport",
        json={"attributes": {"grade": {"value": "C11000", "provenance": "made-up"}}},
        headers=_headers(token),
    )
    assert response.status_code == 422
