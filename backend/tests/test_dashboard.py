from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import MaterialRequirement, Match, WasteListing

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


def test_dashboard_requires_auth():
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 401


def test_generator_dashboard_matches_database(generator_token=None):
    token = _login("generator@recircle.local")
    summary = client.get("/api/dashboard/summary", headers=_auth(token)).json()

    with SessionLocal() as db:
        expected_active = db.scalar(
            select(func.count())
            .select_from(WasteListing)
            .where(WasteListing.status == "active", WasteListing.organization_id.is_not(None))
        )
        # generator org only
        from app.models import Organization

        org = db.scalar(select(Organization).where(Organization.name == "Shakti Metals Works"))
        expected_org_active = db.scalar(
            select(func.count())
            .select_from(WasteListing)
            .where(WasteListing.status == "active", WasteListing.organization_id == org.id)
        )
        expected_unit_rows = db.execute(
            select(WasteListing.unit, func.sum(WasteListing.quantity))
            .where(WasteListing.status == "active", WasteListing.organization_id == org.id)
            .group_by(WasteListing.unit)
        ).all()

    assert summary["active_listings"] == expected_org_active
    assert expected_active >= summary["active_listings"]

    units_in_summary = {row["unit"] for row in summary["quantity_by_unit"]}
    assert units_in_summary <= {"kg", "tonne", "litre", "unit"}
    for row in summary["quantity_by_unit"]:
        matching_row = next(r for r in expected_unit_rows if r[0] == row["unit"])
        assert abs(float(matching_row[1]) - row["total"]) < 0.001

    # recent listings belong to the org and are sorted newest first
    recent = summary["recent_listings"]
    assert 0 < len(recent) <= 5
    timestamps = [item["updated_at"] for item in recent]
    assert timestamps == sorted(timestamps, reverse=True)


def test_buyer_dashboard_counts_requirements_and_matches():
    token = _login("buyer@recircle.local")
    summary = client.get("/api/dashboard/summary", headers=_auth(token)).json()

    with SessionLocal() as db:
        from app.models import Organization

        org = db.scalar(select(Organization).where(Organization.name == "GreenPack Industries"))
        expected_requirements = db.scalar(
            select(func.count())
            .select_from(MaterialRequirement)
            .where(MaterialRequirement.status == "active", MaterialRequirement.organization_id == org.id)
        )
        expected_matches = db.scalar(
            select(func.count())
            .select_from(Match)
            .join(MaterialRequirement, Match.requirement_id == MaterialRequirement.id)
            .where(MaterialRequirement.organization_id == org.id)
        )

    assert summary["requirements_count"] == expected_requirements
    assert summary["matches_count"] == expected_matches


def test_dashboard_never_mixes_units_in_one_total():
    token = _login("generator@recircle.local")
    summary = client.get("/api/dashboard/summary", headers=_auth(token)).json()

    # each unit appears at most once; totals are per-unit, never merged
    units = [row["unit"] for row in summary["quantity_by_unit"]]
    assert len(units) == len(set(units))
    for row in summary["quantity_by_unit"]:
        assert isinstance(row["total"], float)
        assert row["listing_count"] >= 1
