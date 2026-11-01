import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.seed import DEMO_PASSWORD, seed
from app.main import app
from app.services import ai_enrichment

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


DESCRIPTION = "Clean offcuts of mild steel from a fabrication line, around 800 kg."


def test_route_requires_auth():
    response = client.post("/api/ai/enrich-description", json={"description": DESCRIPTION})
    assert response.status_code == 401


def test_offline_ollama_falls_back_gracefully(monkeypatch):
    def unavailable(description: str) -> dict:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ai_enrichment, "_call_ollama", unavailable)
    response = ai_enrichment.enrich_description(DESCRIPTION)

    assert response.available is False
    assert response.source == "fallback"
    assert response.needs_review is True
    # deterministic fallback still extracts what is literally present
    assert response.suggestions.category == "metals"
    assert response.suggestions.quantity == 800.0
    assert response.suggestions.unit == "kg"
    assert response.suggestions.grade is None
    assert any("grade" in item or "composition" in item for item in response.suggestions.missing_information)


def test_timeout_falls_back_gracefully(monkeypatch):
    def timeout(description: str) -> dict:
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(ai_enrichment, "_call_ollama", timeout)
    response = ai_enrichment.enrich_description(DESCRIPTION)
    assert response.available is False
    assert response.source == "fallback"


def test_malformed_model_output_falls_back(monkeypatch):
    def malformed(description: str) -> dict:
        return "not-json-at-all"  # json.loads will fail

    monkeypatch.setattr(ai_enrichment, "_call_ollama", malformed)
    response = ai_enrichment.enrich_description(DESCRIPTION)
    assert response.source == "fallback"
    assert response.suggestions.category == "metals"


def test_valid_model_output_is_validated_and_merged(monkeypatch):
    def model(description: str) -> dict:
        return {
            "category": "metals",
            "material_name": "Mild steel offcuts",
            "composition": None,
            "grade": None,
            "quantity": 800,
            "unit": "kg",
            "missing_information": ["location", "price"],
            "notes": "Derived from the description text.",
        }

    monkeypatch.setattr(ai_enrichment, "_call_ollama", model)
    response = ai_enrichment.enrich_description(DESCRIPTION)

    assert response.available is True
    assert response.source == "ollama"
    assert response.suggestions.category == "metals"
    assert response.suggestions.material_name == "Mild steel offcuts"
    assert response.suggestions.quantity == 800
    assert response.suggestions.unit == "kg"
    assert response.suggestions.grade is None  # model did not state one; never invented


def test_invalid_model_values_are_dropped_not_trusted(monkeypatch):
    def model(description: str) -> dict:
        return {
            "category": "nuclear_waste",  # not an allowed category
            "quantity": -5,  # invalid
            "unit": "barrels",  # not allowed
            "grade": "certified safe",  # invented grade must not be trusted
        }

    monkeypatch.setattr(ai_enrichment, "_call_ollama", model)
    response = ai_enrichment.enrich_description(DESCRIPTION)

    # invalid values are dropped -> fall back deterministically for usable data
    assert response.source == "fallback"
    assert response.suggestions.category == "metals"
    assert response.suggestions.grade is None


def test_route_returns_suggestions_with_needs_review(monkeypatch):
    def unavailable(description: str) -> dict:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(ai_enrichment, "_call_ollama", unavailable)
    token = _login("generator@recircle.local")

    response = client.post(
        "/api/ai/enrich-description",
        json={"description": DESCRIPTION},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_review"] is True
    assert body["available"] is False
    assert "suggestions" in body
