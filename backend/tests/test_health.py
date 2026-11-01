from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_db_returns_ok_or_unavailable():
    response = client.get("/api/health/db")
    if response.status_code == 200:
        assert response.json()["database"] == "connected"
    else:
        assert response.status_code == 503
        assert response.json()["database"] == "unavailable"
