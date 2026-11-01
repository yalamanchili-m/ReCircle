from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.seed import DEMO_PASSWORD, seed

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


@pytest.fixture(scope="module")
def buyer_token():
    return _login("buyer@recircle.local")


@pytest.fixture(scope="module")
def generator_token():
    return _login("generator@recircle.local")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_marketplace_requires_auth():
    response = client.get("/api/marketplace/listings")
    assert response.status_code == 401


def test_marketplace_returns_only_active_listings(buyer_token):
    body = client.get("/api/marketplace/listings", headers=_auth(buyer_token)).json()
    assert body["total"] >= 3
    assert all(item["status"] == "active" for item in body["items"])


def test_newly_activated_listing_appears_and_archived_disappears(
    buyer_token, generator_token
):
    created = client.post(
        "/api/listings",
        json={
            "title": "Marketplace Visibility Test Material",
            "description": "Temporary listing for marketplace visibility checks.",
            "category": "other",
            "quantity": "99.000",
            "unit": "unit",
            "city": "Nashik",
            "region": "Maharashtra",
        },
        headers=_auth(generator_token),
    ).json()

    before = client.get(
        "/api/marketplace/listings?q=Marketplace Visibility", headers=_auth(buyer_token)
    ).json()
    assert before["total"] == 0  # drafts are not public

    activated = client.post(
        f"/api/listings/{created['id']}/activate", headers=_auth(generator_token)
    ).json()
    assert activated["status"] == "active"

    visible = client.get(
        "/api/marketplace/listings?q=Marketplace Visibility", headers=_auth(buyer_token)
    ).json()
    assert visible["total"] == 1
    assert visible["items"][0]["id"] == created["id"]

    client.post(f"/api/listings/{created['id']}/archive", headers=_auth(generator_token))
    after = client.get(
        "/api/marketplace/listings?q=Marketplace Visibility", headers=_auth(buyer_token)
    ).json()
    assert after["total"] == 0


def test_text_search_filters(buyer_token):
    body = client.get(
        "/api/marketplace/listings?q=steel offcuts", headers=_auth(buyer_token)
    ).json()
    assert body["total"] >= 1
    assert all(
        "steel" in item["title"].lower() or "steel" in item["description"].lower()
        for item in body["items"]
    )


def test_category_filter(buyer_token):
    body = client.get(
        "/api/marketplace/listings?category=metals", headers=_auth(buyer_token)
    ).json()
    assert body["total"] >= 2  # steel offcuts + aluminium scrap are active metals
    assert all(item["category"] == "metals" for item in body["items"])


def test_city_filter(buyer_token):
    body = client.get(
        "/api/marketplace/listings?city=Pune", headers=_auth(buyer_token)
    ).json()
    assert body["total"] >= 3
    assert all(item["city"].lower() == "pune" for item in body["items"])


def test_min_quantity_with_unit_filter(buyer_token):
    body = client.get(
        "/api/marketplace/listings?min_quantity=700&unit=kg", headers=_auth(buyer_token)
    ).json()
    assert body["total"] >= 1
    assert all(item["unit"] == "kg" for item in body["items"])
    assert all(Decimal(item["quantity"]) >= Decimal("700") for item in body["items"])

    only_cardboard = client.get(
        "/api/marketplace/listings?min_quantity=1000&unit=kg&category=paper_cardboard",
        headers=_auth(buyer_token),
    ).json()
    assert only_cardboard["total"] == 1  # clean cardboard (1200 kg)


def test_max_price_filter_excludes_unpriced(buyer_token, generator_token):
    created = client.post(
        "/api/listings",
        json={
            "title": "Unpriced Rubber Scraps",
            "description": "Listing without a price for budget filter tests.",
            "category": "other",
            "quantity": "50.000",
            "unit": "kg",
            "city": "Pune",
        },
        headers=_auth(generator_token),
    ).json()
    client.post(f"/api/listings/{created['id']}/activate", headers=_auth(generator_token))

    body = client.get(
        "/api/marketplace/listings?q=Unpriced Rubber&max_price=100",
        headers=_auth(buyer_token),
    ).json()
    assert body["total"] == 0  # no price -> cannot verify budget -> excluded

    without_budget = client.get(
        "/api/marketplace/listings?q=Unpriced Rubber", headers=_auth(buyer_token)
    ).json()
    assert without_budget["total"] == 1

    client.post(f"/api/listings/{created['id']}/archive", headers=_auth(generator_token))


def test_pagination(buyer_token):
    page = client.get(
        "/api/marketplace/listings?page=1&page_size=2", headers=_auth(buyer_token)
    ).json()
    assert len(page["items"]) <= 2
    assert page["total"] >= 3

    second = client.get(
        "/api/marketplace/listings?page=2&page_size=2", headers=_auth(buyer_token)
    ).json()
    first_ids = {item["id"] for item in page["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert not (first_ids & second_ids)


def test_public_detail_shows_org_name_not_private_details(buyer_token):
    body = client.get("/api/marketplace/listings?category=metals", headers=_auth(buyer_token))
    listing_id = body.json()["items"][0]["id"]

    detail = client.get(
        f"/api/marketplace/listings/{listing_id}", headers=_auth(buyer_token)
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["organization_name"] == "Shakti Metals Works"
    # private account details must not leak
    serialized = str(payload).lower()
    assert "password" not in serialized
    assert "generator@recircle.local" not in serialized
    assert "email" not in payload


def test_detail_404_for_draft_archived_or_missing(buyer_token, generator_token):
    response = client.get(f"/api/marketplace/listings/{uuid4()}", headers=_auth(buyer_token))
    assert response.status_code == 404

    draft = client.post(
        "/api/listings",
        json={
            "title": "Draft Only Detail Test",
            "description": "Should not be publicly visible.",
            "category": "wood",
            "quantity": "10.000",
            "unit": "kg",
            "city": "Pune",
        },
        headers=_auth(generator_token),
    ).json()
    detail = client.get(
        f"/api/marketplace/listings/{draft['id']}", headers=_auth(buyer_token)
    )
    assert detail.status_code == 404
