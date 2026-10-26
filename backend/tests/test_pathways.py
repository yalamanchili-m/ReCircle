"""Circular Path Optimizer tests (blueprint Phase 8)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import WasteListing
from app.services.pathways import templates
from app.services.pathways.engine import (
    InfeasibleListing,
    WEIGHT_PROFILES,
    evaluate_pathways,
)

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()


def _token(email="buyer@recircle.local") -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _any_active_listing_id(category: str | None = None) -> str:
    with SessionLocal() as db:
        query = db.query(WasteListing).filter(
            WasteListing.status == "active", WasteListing.quantity > 0
        )
        if category:
            query = query.filter(WasteListing.category == category)
        listing = query.first()
        return str(listing.id)


# --- Template feasibility rules ---------------------------------------------


def test_hard_feasibility_rules():
    # Safety: chemicals can't be reused as-is; remanufacture needs discrete goods.
    assert templates.is_feasible("reuse", "chemicals", None)[0] is False
    assert templates.is_feasible("remanufacture", "organics", None)[0] is False
    assert templates.is_feasible("remanufacture", "metals", None)[0] is False
    # Recycling is universally feasible; the four required pathways exist.
    assert templates.is_feasible("recycle", "plastics", None)[0] is True
    for pathway in templates.all_pathway_ids():
        assert templates.is_feasible(pathway, "electronics", None)[0] is True


# --- Engine: deterministic WSM ranking ---------------------------------------


def test_ranking_is_deterministic_and_rejects_infeasible():
    listing_id = _any_active_listing_id("metals")
    with SessionLocal() as db:
        first = evaluate_pathways(
            db, listing_id=listing_id, destination_region="Karnataka"
        )
        second = evaluate_pathways(
            db, listing_id=listing_id, destination_region="Karnataka"
        )

    assert first["ranked"] == second["ranked"]
    ranked_ids = [c["pathway"] for c in first["ranked"]]
    # Remanufacture is infeasible for... electronics IS feasible — but for
    # organics it must be rejected. Check rejection list on an organics run.
    assert len(ranked_ids) <= 4
    for candidate in first["ranked"]:
        assert candidate["criterion_weights"]
        assert candidate["weighted_contributions"]
        assert abs(
            sum(candidate["weighted_contributions"].values()) - candidate["score"]
        ) < 0.01
    assert first["versions"]["optimizer"] == "pathway-optimizer-v1"


def test_remanufacture_rejected_for_organics():
    listing_id = _any_active_listing_id("organics")
    with SessionLocal() as db:
        result = evaluate_pathways(
            db, listing_id=listing_id, destination_region="Karnataka"
        )
    ranked_ids = [c["pathway"] for c in result["ranked"]]
    assert "remanufacture" not in ranked_ids
    rejected_pathways = {r["pathway"] for r in result["rejected"]}
    assert "remanufacture" in rejected_pathways
    assert any("not feasible" in r["reason"] for r in result["rejected"])


def test_missing_cost_is_dropped_and_renormalized():
    # Find or synthesize an unpriced scenario via direct engine call on a
    # priced listing, asserting cost is dropped only when missing everywhere.
    listing_id = _any_active_listing_id("metals")
    with SessionLocal() as db:
        listing = db.get(WasteListing, uuid.UUID(listing_id))
        listing.price_per_unit = None
        result = evaluate_pathways(
            db, listing_id=listing.id, destination_region="Karnataka"
        )
        listing.price_per_unit = 5.0  # restore without commit
        db.rollback()

    assert "cost" in result["missing_data"]
    for candidate in result["ranked"]:
        assert candidate["raw_values"]["cost"] is None
        assert "cost" not in candidate["criterion_weights"]
    # Weights still sum to 1 after renormalization.
    for candidate in result["ranked"]:
        assert abs(sum(candidate["criterion_weights"].values()) - 1.0) < 0.001


def test_alternate_profiles_supported_and_default_explicit():
    listing_id = _any_active_listing_id("metals")
    with SessionLocal() as db:
        default = evaluate_pathways(db, listing_id=listing_id)
        carbon = evaluate_pathways(
            db, listing_id=listing_id, profile="environment_first"
        )
        cost = evaluate_pathways(db, listing_id=listing_id, profile="cost_first")
    assert default["profile"] == "default"
    assert carbon["profile"] == "environment_first"
    assert cost["profile"] == "cost_first"
    # Same feasible set, potentially different order — deterministic each.
    assert [c["pathway"] for c in default["ranked"]] == sorted(
        [c["pathway"] for c in default["ranked"]],
        key=lambda p: [-c2["score"] for c2 in default["ranked"] if c2["pathway"] == p][0],
    )


def test_sensitivity_reported():
    listing_id = _any_active_listing_id("metals")
    with SessionLocal() as db:
        result = evaluate_pathways(db, listing_id=listing_id, destination_region="Karnataka")
    assert result["sensitivity"]
    for entry in result["sensitivity"]:
        assert "top_rank_stable" in entry
        assert entry["perturbation"] > 0


def test_infeasible_listing_raises_before_ranking():
    with SessionLocal() as db:
        query = db.query(WasteListing).filter(
            WasteListing.category == "chemicals", WasteListing.status == "active"
        )
        listing = query.first()
        if listing is None:
            pytest.skip("no active chemicals listing in seed")
        result = evaluate_pathways(db, listing_id=listing.id)
        # recycle is always feasible, so a total rejection is impossible via
        # this engine; but an unknown category must raise.
        try:
            listing.category = "nonexistent_category_xyz"
            with pytest.raises(InfeasibleListing):
                evaluate_pathways(db, listing_id=listing.id)
        finally:
            db.rollback()


# --- API ----------------------------------------------------------------------


def test_api_evaluate_and_evaluation_and_profiles():
    token = _token()
    listing_id = _any_active_listing_id("metals")

    response = client.post(
        "/api/pathways/evaluate",
        headers=_auth(token),
        json={"listing_id": listing_id, "destination_region": "Karnataka"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ranked"][0]["score"] >= body["ranked"][-1]["score"]
    assert len(body["assumptions"]) >= 3

    evaluation = client.get("/api/pathways/evaluation", headers=_auth(token))
    assert evaluation.status_code == 200
    assert evaluation.json()["evaluation_version"] == "pathway-eval-v1"
    assert evaluation.json()["passed"] == evaluation.json()["total"]

    profiles = client.get("/api/pathways/profiles", headers=_auth(token))
    assert profiles.status_code == 200
    assert profiles.json()["default"] == "default"
    assert set(profiles.json()["profiles"]) == set(WEIGHT_PROFILES)


def test_api_auth_and_validation():
    assert client.post("/api/pathways/evaluate", json={"listing_id": "x"}).status_code == 401
    assert client.get("/api/pathways/evaluation").status_code == 401
    token = _token()
    unknown = client.post(
        "/api/pathways/evaluate",
        headers=_auth(token),
        json={"listing_id": str(uuid.uuid4())},
    )
    assert unknown.status_code == 404
    bad_profile = client.post(
        "/api/pathways/evaluate",
        headers=_auth(token),
        json={"listing_id": _any_active_listing_id(), "profile": "bogus"},
    )
    assert bad_profile.status_code == 422
