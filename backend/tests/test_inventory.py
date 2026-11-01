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
def generator_token():
    return _login("generator@recircle.local")


@pytest.fixture(scope="module")
def buyer_token():
    return _login("buyer@recircle.local")


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@recircle.local")


def _listing_payload(**overrides) -> dict:
    payload = {
        "title": "Test Copper Wire Scrap",
        "description": "SYNTHETIC test listing created by automated tests.",
        "category": "metals",
        "quantity": "250.000",
        "unit": "kg",
        "price_per_unit": "320.00",
        "city": "Pune",
        "region": "Maharashtra",
    }
    payload.update(overrides)
    return payload


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_create_listing_returns_201_and_draft(generator_token):
    response = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["title"] == "Test Copper Wire Scrap"
    assert Decimal(body["quantity"]) == Decimal("250.000")


def test_create_listing_requires_generator_role(buyer_token):
    response = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(buyer_token)
    )
    assert response.status_code == 403


def test_create_listing_requires_auth():
    response = client.post("/api/listings", json=_listing_payload())
    assert response.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": "0"},
        {"quantity": "-5"},
        {"unit": "barrels"},
        {"category": "nuclear_waste"},
        {"city": ""},
        {"title": ""},
    ],
)
def test_create_listing_rejects_invalid_fields(generator_token, overrides):
    response = client.post(
        "/api/listings",
        json=_listing_payload(**overrides),
        headers=_auth(generator_token),
    )
    assert response.status_code == 422


def test_get_listing_by_creator(generator_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    response = client.get(f"/api/listings/{create['id']}", headers=_auth(generator_token))
    assert response.status_code == 200
    assert response.json()["id"] == create["id"]


def test_get_missing_listing_returns_404(generator_token):
    response = client.get(f"/api/listings/{uuid4()}", headers=_auth(generator_token))
    assert response.status_code == 404


def test_buyer_cannot_read_or_edit_generator_listing(generator_token, buyer_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()

    read = client.get(f"/api/listings/{create['id']}", headers=_auth(buyer_token))
    assert read.status_code == 403

    patch = client.patch(
        f"/api/listings/{create['id']}",
        json={"title": "Hijacked"},
        headers=_auth(buyer_token),
    )
    assert patch.status_code == 403

    archive = client.post(
        f"/api/listings/{create['id']}/archive", headers=_auth(buyer_token)
    )
    assert archive.status_code == 403


def test_admin_can_manage_any_listing(generator_token, admin_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    response = client.patch(
        f"/api/listings/{create['id']}",
        json={"title": "Admin Renamed Title"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Admin Renamed Title"


def test_update_listing_persists_changes(generator_token):
    create = client.post(
        "/api/listings",
        json=_listing_payload(title="Original Title"),
        headers=_auth(generator_token),
    ).json()
    response = client.patch(
        f"/api/listings/{create['id']}",
        json={"quantity": "412.500", "price_per_unit": "301.25"},
        headers=_auth(generator_token),
    )
    assert response.status_code == 200
    assert Decimal(response.json()["quantity"]) == Decimal("412.500")

    refetched = client.get(
        f"/api/listings/{create['id']}", headers=_auth(generator_token)
    ).json()
    assert Decimal(refetched["quantity"]) == Decimal("412.500")


def test_activate_draft_listing(generator_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    response = client.post(
        f"/api/listings/{create['id']}/activate", headers=_auth(generator_token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_activate_already_active_returns_409(generator_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    client.post(f"/api/listings/{create['id']}/activate", headers=_auth(generator_token))
    again = client.post(
        f"/api/listings/{create['id']}/activate", headers=_auth(generator_token)
    )
    assert again.status_code == 409


def test_archive_listing(generator_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    response = client.post(
        f"/api/listings/{create['id']}/archive", headers=_auth(generator_token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_cannot_activate_or_edit_archived_listing(generator_token):
    create = client.post(
        "/api/listings", json=_listing_payload(), headers=_auth(generator_token)
    ).json()
    client.post(f"/api/listings/{create['id']}/archive", headers=_auth(generator_token))

    edit = client.patch(
        f"/api/listings/{create['id']}",
        json={"title": "Zombie Edit"},
        headers=_auth(generator_token),
    )
    assert edit.status_code == 409

    activate = client.post(
        f"/api/listings/{create['id']}/activate", headers=_auth(generator_token)
    )
    assert activate.status_code == 409


def test_list_listings_filters_by_status_and_search(generator_token):
    created = client.post(
        "/api/listings",
        json=_listing_payload(title="Filterable Nickel Alloy Remnant"),
        headers=_auth(generator_token),
    ).json()
    client.post(f"/api/listings/{created['id']}/activate", headers=_auth(generator_token))

    active = client.get(
        "/api/listings?status=active&q=Nickel", headers=_auth(generator_token)
    ).json()
    assert any(item["id"] == created["id"] for item in active["items"])
    assert active["total"] >= 1

    drafts = client.get(
        "/api/listings?status=draft&q=Nickel", headers=_auth(generator_token)
    ).json()
    assert all(item["id"] != created["id"] for item in drafts["items"])

    none = client.get("/api/listings?q=zebra-unicorn-missing", headers=_auth(generator_token)).json()
    assert none["total"] == 0
    assert none["items"] == []


def test_listings_pagination(generator_token):
    page = client.get("/api/listings?page=1&page_size=2", headers=_auth(generator_token)).json()
    assert len(page["items"]) <= 2
    assert page["total"] >= 5  # seeded listings included
