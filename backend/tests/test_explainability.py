"""Explainable AI Engine tests (blueprint Phase 10)."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Match
from app.services import carbon, explainability
from app.services.explainability import EXPLANATION_SCHEMA_VERSION

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


# ------------------------------------------------------------- unit builders


def test_schema_version_is_single_and_documented():
    assert EXPLANATION_SCHEMA_VERSION == "explanation-schema-v1"


def test_explain_match_contributions_sum_to_signal():
    candidate = {
        "explanation": "cardboard matches the Requirement",
        "score_breakdown": {
            "components": {
                "category": 40.0,
                "quantity": 25.0,
                "quality": 20.0,
                "location": 10.0,
                "price": 5.0,
            },
            "max_applicable": 100.0,
            "material_fit": 0.92,
            "knn_score": 0.88,
            "algorithm_version": "circular-match-v2",
            "warnings": ["Unit mismatch tolerated"],
        },
    }
    explanation = explainability.explain_match(candidate)
    assert explanation["explanation_schema_version"] == EXPLANATION_SCHEMA_VERSION
    assert explanation["subject_type"] == "match"
    assert explanation["subject_version"] == "circular-match-v2"
    features = {c["feature"] for c in explanation["contributions"]}
    assert {
        "category",
        "quantity",
        "quality",
        "location",
        "price",
        "material_fit",
        "knn_score",
    } <= features
    shares = [c["share_of_signal"] for c in explanation["contributions"]]
    assert abs(sum(shares) - 1.0) < 0.001
    assert explanation["causation_note"].startswith("Contributions describe")
    assert any("no trained model" in caveat for caveat in explanation["caveats"])
    # warnings are surfaced, never swallowed
    assert any("Unit mismatch tolerated" in c for c in explanation["caveats"])
    assert explanation["data_coverage"]["warnings_count"] == 1


def test_explain_pathway_contributions_replay_the_wsm():
    candidate = {
        "pathway": "reuse",
        "score": 0.7,
        "weighted_contributions": {"environment": 0.4, "cost": 0.3},
        "raw_values": {"environment": 2.0},
        "normalized_values": {"environment": 0.8},
        "criterion_weights": {"environment": 0.5, "cost": 0.5},
        "missing_criteria": ["cost"],
    }
    explanation = explainability.explain_pathway(candidate, "default")
    assert explanation["subject_type"] == "pathway"
    assert explanation["method"] == "native_weighted_sum_contributions"
    contributions = {c["feature"]: c["value"] for c in explanation["contributions"]}
    assert contributions["environment"] == 0.4
    assert contributions["cost"] == 0.3
    # contributions replay the score, not replace it silently
    assert abs(sum(contributions.values()) - candidate["score"]) < 1e-9
    assert explanation["inputs"]["criterion_weights"] == candidate["criterion_weights"]
    assert explanation["data_coverage"]["missing_criteria"] == ["cost"]


def test_explain_impact_terms_sum_to_estimate_displays_band():
    estimate = SimpleNamespace(
        supported=True,
        method=carbon.METHOD,
        factor_catalog_version=carbon.FACTOR_CATALOG_VERSION,
        factor_source=carbon.FACTOR_SOURCE,
        baseline_reference=carbon.BASELINE_REFERENCE,
        recovery_record_id=uuid.uuid4(),
        recovery_route="recycle",
        quantity=500.0,
        unit="kg",
        quantity_tonnes=0.5,
        avoided_co2e_kg=785.0,
        landfill_diverted_kg=500.0,
        id=uuid.uuid4(),
        assumptions={
            "items": carbon.ASSUMPTIONS,
            "formula_terms": carbon.compute_estimate(
                "paper_cardboard", "recycle", 500, "kg"
            )["formula_terms"],
            "avoided_co2e_kg_low": 460.0,
            "avoided_co2e_kg_high": 1110.0,
            "uncertainty_basis": "worst-case interval over row-level uncertainty ratios",
        },
    )
    explanation = explainability.explain_impact(estimate, "paper_cardboard")
    assert explanation["subject_type"] == "impact_estimate"
    # contributions replay the estimate exactly
    total = sum(c["value"] for c in explanation["contributions"])
    assert abs(total - float(estimate.avoided_co2e_kg)) < 0.01
    band = explanation["data_coverage"]["uncertainty_band"]
    assert band == {
        "low_kg": 460.0,
        "high_kg": 1110.0,
        "basis": "worst-case interval over row-level uncertainty ratios",
    }
    # no-causation caveat is always attached
    assert any(
        "do not prove causation" in caveat for caveat in explanation["caveats"]
    )
    assert explanation["sources"][0]["version"] == carbon.FACTOR_CATALOG_VERSION


def test_explain_impact_unsupported_estimate_never_fabricates_numbers():
    estimate = SimpleNamespace(
        supported=False,
        method=carbon.METHOD,
        factor_catalog_version=carbon.FACTOR_CATALOG_VERSION,
        factor_source=carbon.FACTOR_SOURCE,
        baseline_reference=carbon.BASELINE_REFERENCE,
        recovery_record_id=uuid.uuid4(),
        recovery_route="recycle",
        quantity=10.0,
        unit="litre",
        quantity_tonnes=None,
        avoided_co2e_kg=None,
        landfill_diverted_kg=None,
        id=uuid.uuid4(),
        assumptions={},
        unsupported_reason="Unit 'litre' is not convertible to mass",
    )
    explanation = explainability.explain_impact(estimate, "plastics")
    contributions = explanation["contributions"]
    assert len(contributions) == 1
    assert contributions[0]["feature"] == "estimate_unavailable"
    assert contributions[0]["value"] == 0.0
    assert explanation["data_coverage"]["supported"] is False
    assert "Unit 'litre'" in contributions[0]["detail"]


def test_shap_and_lime_are_governance_reported_unavailable():
    status = explainability.explain_subject_status()
    assert status["predictive_models_deployed"] is False
    assert status["shap"]["status"] in ("unavailable", "not_applicable")
    assert "synthetic" in status["shap"]["reason"].lower()
    assert status["lime"]["status"] in ("unavailable", "not_applicable")
    assert any("causation" in note for note in status["limitations"])


# -------------------------------------------------------------------- API UI


def test_status_endpoint_requires_auth_and_reports_governance():
    assert client.get("/api/explain/status").status_code == 401
    buyer = _login("buyer@recircle.local")
    body = client.get("/api/explain/status", headers=_auth(buyer)).json()
    assert body["explanation_schema_version"] == EXPLANATION_SCHEMA_VERSION
    assert body["predictive_models_deployed"] is False


def _create_listing_and_requirement(generator, buyer, title):
    created_listing = client.post(
        "/api/listings",
        json={
            "title": title,
            "description": "Synthetic listing for explain tests.",
            "category": "metals",
            "quantity": "500.000",
            "unit": "kg",
            "price_per_unit": "20.00",
            "city": "Pune",
            "region": "Maharashtra",
            "grade": "Low carbon steel",
        },
        headers=_auth(generator),
    )
    assert created_listing.status_code == 201, created_listing.text
    listing_id = created_listing.json()["id"]
    activated = client.post(
        f"/api/listings/{listing_id}/activate", headers=_auth(generator)
    )
    assert activated.status_code == 200

    created_requirement = client.post(
        "/api/requirements",
        json={
            "title": f"{title} requirement",
            "category": "metals",
            "min_quantity": "500.000",
            "unit": "kg",
            "required_grade": "Low carbon steel",
            "max_price_per_unit": "22.00",
            "preferred_city": "Pune",
            "preferred_region": "Maharashtra",
        },
        headers=_auth(buyer),
    )
    assert created_requirement.status_code == 201, created_requirement.text
    return listing_id, created_requirement.json()["id"]


def test_explain_match_endpoint_returns_native_contributions():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")
    listing_id, requirement_id = _create_listing_and_requirement(
        generator, buyer, "Explain Match Probe Steel"
    )
    run = client.post(
        f"/api/requirements/{requirement_id}/matches?persist=true",
        headers=_auth(buyer),
    ).json()
    stored = client.get(
        f"/api/requirements/{requirement_id}/matches", headers=_auth(buyer)
    ).json()
    match = next(s for s in stored if s["listing_id"] == listing_id)
    assert run["persisted"] is True

    response = client.get(
        f"/api/explain/match/{match['id']}", headers=_auth(buyer)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation_schema_version"] == EXPLANATION_SCHEMA_VERSION
    assert body["subject_type"] == "match"
    assert body["subject_version"] == "circular-match-v2"
    features = {c["feature"] for c in body["contributions"]}
    assert "material_fit" in features and "knn_score" in features
    assert body["inputs"]["listing_id"] == listing_id
    assert body["inputs"]["title"] == "Explain Match Probe Steel"

    # 404 for a random match id
    missing = client.get(f"/api/explain/match/{uuid.uuid4()}", headers=_auth(buyer))
    assert missing.status_code == 404


def test_explain_pathway_endpoint_replays_engine_deterministically():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")
    listing_id, _ = _create_listing_and_requirement(
        generator, buyer, "Explain Pathway Probe Metals"
    )

    first = client.get(
        f"/api/explain/pathway?listing_id={listing_id}&pathway=recycle",
        headers=_auth(buyer),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["subject_type"] == "pathway"
    assert body["inputs"]["pathway"] == "recycle"
    features = {c["feature"] for c in body["contributions"]}
    assert features, "weighted contributions must be explained"
    assert any("Weighted Sum Model" in caveat for caveat in body["caveats"])

    # determinism: same inputs -> same contributions
    second = client.get(
        f"/api/explain/pathway?listing_id={listing_id}&pathway=recycle",
        headers=_auth(buyer),
    ).json()
    assert [c["feature"] for c in body["contributions"]] == [
        c["feature"] for c in second["contributions"]
    ]
    assert [c["value"] for c in body["contributions"]] == [
        c["value"] for c in second["contributions"]
    ]

    # default profile without explicit pathway explains the ranked winner
    top = client.get(
        f"/api/explain/pathway?listing_id={listing_id}", headers=_auth(buyer)
    )
    assert top.status_code == 200

    # invalid pathway id → 422 with the supported list
    invalid = client.get(
        f"/api/explain/pathway?listing_id={listing_id}&pathway=teleportation",
        headers=_auth(buyer),
    )
    assert invalid.status_code == 422
    assert "supported" in invalid.json()["detail"]

    # infeasible pathway (remanufacture is hard-gated for metals) →
    # rejection explanation, feasibility gate — never a fabricated score
    rejected = client.get(
        f"/api/explain/pathway?listing_id={listing_id}&pathway=remanufacture",
        headers=_auth(buyer),
    )
    assert rejected.status_code == 200, rejected.text
    rbody = rejected.json()
    assert rbody["data_coverage"]["rejected"] is True
    assert rbody["contributions"][0]["feature"] == "feasibility_gate"
    assert any(
        "excluded BEFORE ranking" in caveat for caveat in rbody["caveats"]
    )


def test_explain_impact_endpoint_replays_factor_arithmetic():
    generator = _login("generator@recircle.local")
    buyer = _login("buyer@recircle.local")
    listing_id, requirement_id = _create_listing_and_requirement(
        generator, buyer, "Explain Impact Probe Metals"
    )

    offer = client.post(
        "/api/offers",
        json={
            "listing_id": listing_id,
            "requirement_id": requirement_id,
            "quantity": "500.000",
            "price_per_unit": "20.00",
        },
        headers=_auth(buyer),
    )
    assert offer.status_code == 201, offer.text
    offer_id = offer.json()["id"]
    accepted = client.post(
        f"/api/offers/{offer_id}/accept", headers=_auth(generator)
    )
    assert accepted.status_code == 200, accepted.text
    transaction_id = accepted.json()["id"]
    recovery = client.post(
        f"/api/transactions/{transaction_id}/recovery",
        json={
            "recovered_quantity": "500.000",
            "unit": "kg",
            "recovery_route": "recycle",
            "calculation_notes": "Explain impact test recovery",
        },
        headers=_auth(buyer),
    )
    assert recovery.status_code == 201, recovery.text
    recovery_id = recovery.json()["id"]

    body = client.get(
        f"/api/explain/impact/{recovery_id}", headers=_auth(buyer)
    ).json()
    assert body["subject_type"] == "impact_estimate"
    assert carbon.METHOD in body["subject_version"]
    assert carbon.FACTOR_CATALOG_VERSION in body["subject_version"]
    total = sum(c["value"] for c in body["contributions"])
    assert abs(total - body["inputs"]["estimated_value"]) < 0.01
    assert body["inputs"]["estimated_value"] == expected_for_metals_recycle_500kg()
    band = body["data_coverage"]["uncertainty_band"]
    assert band["low_kg"] <= body["inputs"]["estimated_value"] <= band["high_kg"]

    # Non-party access is scoped: other-org users cannot load it
    missing = client.get(
        f"/api/explain/impact/{uuid.uuid4()}", headers=_auth(buyer)
    )
    assert missing.status_code == 404
    assert client.get(f"/api/explain/impact/{recovery_id}").status_code == 401


def expected_for_metals_recycle_500kg() -> float:
    from decimal import Decimal

    return float(
        carbon.compute_estimate("metals", "recycle", Decimal("500.000"), "kg")[
            "avoided_co2e_kg"
        ]
    )
