"""Knowledge graph tests (blueprint Phase 6).

Neo4j may not be running: these tests verify the projection logic against a
fake driver, and verify that graph outages never break PostgreSQL workflows
and never leak driver errors into responses.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.seed import DEMO_PASSWORD, seed
from app.main import app
from app.models import GraphSyncRun, MaterialRequirement, WasteListing
from app.services.graph import sync as graph_sync
from app.services.graph.driver import reset_driver_cache

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    seed()


class FakeResult:
    def __init__(self, records=None):
        self._records = records or []

    def single(self, strict: bool = True):
        if strict:
            assert len(self._records) == 1, "expected exactly one record"
            return self._records[0]
        return self._records[0] if self._records else None

    def __iter__(self):
        return iter(self._records)


class FakeSession:
    """Records Cypher statements; MERGE statements are deduplicated."""

    def __init__(self, store: dict):
        self.store = store

    def run(self, query, **parameters):
        self.store.setdefault("statements", []).append((query.strip(), parameters))
        if "RETURN count(n) AS c" in query:
            label = query.split("MATCH (n:")[1].split(")")[0]
            return FakeResult([{"c": self.store.get("counts", {}).get(label, 0)}])
        if query.startswith("MATCH (n {id: $id}) RETURN labels"):
            node = self.store["nodes"].get(parameters["id"])
            return FakeResult([{"labels": ["Node"], "props": node}] if node else [])
        if query.startswith("MATCH (n {id: $id})-[r]-(m)"):
            return FakeResult(self.store.get("relationships", []))
        # MERGE / CREATE statements: record idempotently
        if "MERGE" in query:
            key = (query.strip(), dict(sorted(parameters.items())))
            self.store.setdefault("merges", []).append(key)
        return FakeResult()

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDriver:
    def __init__(self):
        self.store = {"nodes": {}, "statements": [], "merges": []}

    def session(self):
        return FakeSession(self.store)


@pytest.fixture()
def fake_driver(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        "app.services.graph.sync.require_driver", lambda: driver, raising=True
    )
    monkeypatch.setattr(
        "app.services.graph.sync.ensure_graph_schema", lambda driver=None: 10, raising=True
    )
    # Routes resolve the driver lazily; point them at the same fake.
    monkeypatch.setattr("app.api.routes.graph.get_driver", lambda: driver, raising=True)
    reset_driver_cache()
    yield driver
    reset_driver_cache()


def _admin_token() -> str:
    response = client.post(
        "/api/auth/login", json={"email": "admin@recircle.local", "password": DEMO_PASSWORD}
    )
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_sync_via_fake_driver_is_idempotent(fake_driver):
    token = _admin_token()

    first = client.post("/api/graph/sync", headers=_auth(token))
    assert first.status_code == 200
    assert first.json()["status"] == "success"

    # Re-run: same MERGE statements again — no duplicates by construction
    # (MERGE keyed on stable ids) and identical counts.
    second = client.post("/api/graph/sync", headers=_auth(token))
    assert second.status_code == 200
    assert second.json()["stats"] == first.json()["stats"]

    # MERGE keys are stable ids (org:/listing:/requirement:/material:)
    merged_ids = {params.get("id") for _query, params in fake_driver.store["merges"] if "id" in params}
    assert any(key.startswith("org:") for key in merged_ids)
    assert any(key.startswith("listing:") for key in merged_ids)

    with SessionLocal() as db:
        runs = db.scalars(select(GraphSyncRun).order_by(GraphSyncRun.started_at)).all()
        assert len(runs) >= 2
        assert all(run.status == "success" for run in runs[-2:])


def test_sync_failure_is_recorded_and_api_degrades(monkeypatch):
    from app.services.graph.driver import GraphUnavailable

    token = _admin_token()

    def raise_unavailable():
        raise GraphUnavailable("Neo4j is disabled or unreachable")

    monkeypatch.setattr("app.services.graph.sync.require_driver", raise_unavailable)

    response = client.post("/api/graph/sync", headers=_auth(token))
    assert response.status_code == 503
    assert "PostgreSQL data is unaffected" in response.json()["detail"]

    with SessionLocal() as db:
        latest = db.scalars(
            select(GraphSyncRun).order_by(GraphSyncRun.started_at.desc())
        ).first()
        assert latest is not None
        assert latest.status == "failed"
        assert "unreachable" in latest.error


def test_graph_status_reports_unavailability(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.graph.get_driver", lambda: None, raising=True
    )
    monkeypatch.setattr(
        "app.api.routes.graph.get_settings_neo4j_enabled", lambda: True, raising=True
    )
    token = _admin_token()
    response = client.get("/api/graph/status", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["counts"] is None


def test_graph_explore_degrades_when_unavailable(monkeypatch):
    monkeypatch.setattr("app.api.routes.graph.get_driver", lambda: None, raising=True)
    token = _admin_token()
    response = client.get(
        "/api/graph/explore", params={"node_id": "org:some-uuid"}, headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "unaffected" in body["note"]


def test_graph_explore_404_for_missing_node(fake_driver):
    token = _admin_token()
    response = client.get(
        "/api/graph/explore", params={"node_id": "org:missing-uuid"}, headers=_auth(token)
    )
    assert response.status_code == 404


def test_graph_auth_guards():
    # unauthenticated
    assert client.get("/api/graph/status").status_code == 401
    assert client.post("/api/graph/sync").status_code == 401
    # non-admin cannot sync (403), but can view status/explore
    buyer = client.post(
        "/api/auth/login", json={"email": "buyer@recircle.local", "password": DEMO_PASSWORD}
    ).json()["access_token"]
    assert client.post("/api/graph/sync", headers=_auth(buyer)).status_code == 403
    assert client.get("/api/graph/status", headers=_auth(buyer)).status_code == 200


def test_postgres_workflows_unaffected_by_graph_outage(monkeypatch):
    """Core PostgreSQL flows keep working while the graph is down."""
    from app.services.graph.driver import GraphUnavailable

    def raise_unavailable():
        raise GraphUnavailable("down")

    monkeypatch.setattr("app.services.graph.sync.require_driver", raise_unavailable)
    monkeypatch.setattr("app.api.routes.graph.get_driver", lambda: None, raising=True)

    token = _admin_token()
    health = client.get("/api/health/db")
    assert health.status_code == 200

    listings = client.get("/api/listings", headers=_auth(token))
    assert listings.status_code == 200

    with SessionLocal() as db:
        count = len(db.scalars(select(WasteListing)).all())
        assert count > 0
        requirement_count = len(db.scalars(select(MaterialRequirement)).all())
        assert requirement_count > 0
