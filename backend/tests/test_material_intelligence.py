"""Material Intelligence Engine tests (blueprint Phase 4).

The engine is deterministic and fully offline; SBERT is opt-in and its
unavailability must be graceful. No network access happens in these tests.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.seed import seed
from app.main import app
from app.services.material_intelligence import suggest_material_attributes
from app.services.material_intelligence.engine import ENGINE_VERSION
from app.services.material_intelligence.similarity import rank_types
from app.services.material_intelligence.taxonomy import TAXONOMY_VERSION

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "ReCircleDemo123!"}
    )
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_suggestions_include_provenance_evidence_and_versions():
    result = suggest_material_attributes("Clean copper wire scrap from motor rewinding")
    assert result["model_version"] == ENGINE_VERSION
    assert result["taxonomy_version"] == TAXONOMY_VERSION
    assert result["needs_review"] is True

    material = result["suggestions"]["material_type"]
    assert material["provenance"] == "ai_inferred"
    assert material["value"]["type_id"] == "metals.copper"
    assert material["evidence"]["source"] == "taxonomy_alias"
    # original user label is always preserved
    assert material["evidence"]["original_label"] == "clean copper wire scrap from motor rewinding"
    assert "not laboratory-verified" in result["disclaimer"]


def test_unknown_material_degrades_safely():
    result = suggest_material_attributes("Zorblax intergalactic flux capacitor plates")
    material = result["suggestions"]["material_type"]
    assert material["value"] is None
    assert material["provenance"] == "unverified"
    assert result["suggestions"]["category"]["value"] is None
    assert "material category" in result["missing_information"]
    # pathways without a category are empty, not invented
    assert result["suggestions"]["candidate_pathways"]["value"] == []


def test_tfidf_ranking_is_deterministic_and_bounded():
    first = rank_types("washed clear PET bottle flakes for extrusion")
    second = rank_types("washed clear PET bottle flakes for extrusion")
    assert first == second
    for _entry, score in first:
        assert 0.0 <= score <= 1.0 + 1e-9
    assert first[0][1] >= first[-1][1]  # sorted descending


def test_sbert_unavailable_falls_back_to_tfidf(monkeypatch):
    from app.services.material_intelligence import engine, sbert

    monkeypatch.setattr(sbert, "is_available", lambda: False)
    result = suggest_material_attributes("brass turnings from machining shop")
    assert result["method"] == "alias+tfidf"  # alias path dominates; fallback reported
    assert result["suggestions"]["material_type"]["value"]["type_id"] == "metals.brass"

    # A description without an exact alias must still rank via TF-IDF.
    result = suggest_material_attributes("windings and winding scrap from electric motors copper")
    assert result["suggestions"]["material_type"]["value"]["type_id"] == "metals.copper"


def test_suggestions_endpoint_requires_auth():
    response = client.post("/api/ai/material-suggestions", json={"description": "copper wire"})
    assert response.status_code == 401


def test_accept_flow_stores_provenance_and_marks_reviewed():
    generator = _login("generator@recircle.local")
    headers = _auth(generator)

    listing = client.post(
        "/api/listings",
        json={
            "title": "AI Accept Copper Coils",
            "description": "Copper coils from motor rewind shop",
            "category": "metals",
            "quantity": "120.000",
            "unit": "kg",
            "city": "Pune",
        },
        headers=headers,
    )
    assert listing.status_code == 201
    listing_id = listing.json()["id"]

    accepted = client.post(
        f"/api/ai/listings/{listing_id}/material-suggestions/accept",
        json={
            "material_name": "Copper winding scrap",
            "possible_applications": ["Cable manufacturing", "Conductive fillers"],
            "suitable_industries": ["Electrical equipment"],
        },
        headers=headers,
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["material_name"] == "Copper winding scrap"
    assert body["ai_reviewed"] is True

    provenance = body["ai_suggestions"]
    assert provenance["material_name"]["provenance"] == "ai_inferred"
    assert provenance["material_name"]["model_version"] == ENGINE_VERSION
    assert provenance["material_name"]["accepted_by"]
    assert provenance["possible_applications"]["value"] == [
        "Cable manufacturing",
        "Conductive fillers",
    ]


def test_accept_rejects_unsupported_category_and_empty_payload():
    generator = _login("generator@recircle.local")
    headers = _auth(generator)
    listing = client.post(
        "/api/listings",
        json={
            "title": "AI Validation Listing",
            "description": "Mixed shop scrap",
            "category": "metals",
            "quantity": "10.000",
            "unit": "kg",
            "city": "Pune",
        },
        headers=headers,
    )
    listing_id = listing.json()["id"]

    bad_category = client.post(
        f"/api/ai/listings/{listing_id}/material-suggestions/accept",
        json={"category": "unobtanium"},
        headers=headers,
    )
    assert bad_category.status_code == 422

    empty = client.post(
        f"/api/ai/listings/{listing_id}/material-suggestions/accept",
        json={},
        headers=headers,
    )
    assert empty.status_code == 422


def test_accept_requires_ownership():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")
    listing = client.post(
        "/api/listings",
        json={
            "title": "AI Ownership Listing",
            "description": "Scrap for ownership check",
            "category": "metals",
            "quantity": "10.000",
            "unit": "kg",
            "city": "Pune",
        },
        headers=_auth(generator),
    )
    listing_id = listing.json()["id"]
    response = client.post(
        f"/api/ai/listings/{listing_id}/material-suggestions/accept",
        json={"material_name": "Hijacked name"},
        headers=_auth(buyer),
    )
    assert response.status_code == 403


def test_evaluation_reports_smoke_metrics_with_disclaimer():
    token = _login("generator@recircle.local")
    response = client.get("/api/ai/evaluation", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["eval_set"] == "material-eval-smoke-v1"
    assert body["size"] == 12
    assert 0.0 <= body["metrics"]["top1_accuracy"] <= 1.0
    assert body["metrics"]["precision_recall_on_real_data"] is None
    assert "not a measure of real-world accuracy" in body["disclaimer"]

    assert client.get("/api/ai/evaluation").status_code == 401
