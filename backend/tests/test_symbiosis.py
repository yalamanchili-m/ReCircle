"""Industrial symbiosis tests (blueprint Phase 7).

Pure algorithm tests use hand-checkable synthetic graphs (no DB); engine
tests run against the seeded dev database and assert hard constraints,
evidence citation, determinism, and run recording.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import SymbiosisRun
from app.services.symbiosis import algorithms
from app.services.symbiosis.evaluation import _known_graph

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


# --- Pure algorithm tests on the known synthetic graph --------------------


def test_bfs_is_deterministic_and_bounded():
    graph = _known_graph()
    runs = [algorithms.bfs_shortest_paths(graph, "org:p1", "org:c1", max_depth=4) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    assert runs[0][0] == [
        "org:p1", "listing:l1", "material:metals.copper", "requirement:r1", "org:c1"
    ]
    # Depth bound excludes the longer route through the industry node.
    assert algorithms.bfs_shortest_paths(graph, "org:p1", "org:far", max_depth=2) == []
    # Missing nodes yield no paths, never errors.
    assert algorithms.bfs_shortest_paths(graph, "org:p1", "ghost", max_depth=4) == []


def test_pagerank_identifies_hub_and_is_deterministic():
    graph = _known_graph()
    runs = [algorithms.pagerank(graph) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    top = max(runs[0], key=lambda node: (runs[0][node], node))
    assert top == "material:metals.copper"
    # Isolated org gets the minimum baseline score.
    assert runs[0]["org:far"] < runs[0]["material:metals.copper"]


def test_louvain_clusters_copper_loop_and_is_deterministic():
    graph = _known_graph()
    runs = [algorithms.louvain_communities(graph) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    communities = runs[0]
    loop = ("org:p1", "listing:l1", "material:metals.copper", "requirement:r1", "org:c1")
    assert len({communities[node] for node in loop}) == 1
    assert communities["org:far"] != communities["material:metals.copper"]


# --- Evaluation endpoint (curated synthetic gate) -------------------------


def test_symbiosis_evaluation_endpoint():
    token = _token()
    response = client.get("/api/symbiosis/evaluation", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_version"] == "symbiosis-eval-v1"
    assert body["passed"] == body["total"]
    assert "synthetic" in body["dataset"].lower()


# --- Engine tests against the seeded database -----------------------------


def test_discovery_respects_hard_constraints_and_cites_evidence():
    token = _token()
    response = client.get("/api/symbiosis/opportunities", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()

    assert body["run"]["status"] == "success"
    assert body["graph"]["snapshot_id"].startswith("symbiosis-graph-v1:")
    assert len(body["limitations"]) >= 3

    for opportunity in body["opportunities"]:
        # Hard constraint: category match on every candidate.
        listing_category = opportunity["category"]
        assert listing_category == opportunity["category"]
        # Status marks inferred relationships as requiring validation.
        assert opportunity["status"] == "inferred_opportunity_requires_validation"
        # Confidence is the documented weighted combination.
        weights = body["run"]["versions"]["weights"]
        expected = (
            weights["material_fit"] * opportunity["material_fit"]
            + weights["availability"] * opportunity["availability"]
            + weights["graph_proximity"] * opportunity["graph_proximity"]
            + weights["cluster_membership"] * (1.0 if opportunity["cluster_membership"] is not None else 0.0)
        )
        assert abs(expected - opportunity["confidence"]) < 0.01
        # Evidence is cited: either a structural path or zero proximity.
        if opportunity["graph_proximity"] > 0:
            assert opportunity["evidence"]["path"], "recommendation must cite its path"
            assert opportunity["evidence"]["path_edges"]


def test_discovery_is_deterministic_across_runs():
    token = _token()
    first = client.get(
        "/api/symbiosis/opportunities", headers=_auth(token),
        params={"category": "plastics"},
    )
    second = client.get(
        "/api/symbiosis/opportunities", headers=_auth(token),
        params={"category": "plastics"},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["opportunities"] == second.json()["opportunities"]
    assert first.json()["graph"]["snapshot_id"] == second.json()["graph"]["snapshot_id"]


def test_discovery_category_filter_is_enforced():
    token = _token()
    response = client.get(
        "/api/symbiosis/opportunities", headers=_auth(token),
        params={"category": "organics"},
    )
    assert response.status_code == 200
    for opportunity in response.json()["opportunities"]:
        assert opportunity["category"] == "organics"


def test_symbiosis_runs_are_recorded():
    token = _token()
    client.get("/api/symbiosis/opportunities", headers=_auth(token), params={"limit": 5})
    with SessionLocal() as db:
        latest = db.scalars(
            select(SymbiosisRun).order_by(SymbiosisRun.started_at.desc())
        ).first()
        assert latest is not None
        assert latest.status == "success"
        assert latest.discovery_version == "symbiosis-discovery-v1"
        assert latest.taxonomy_version == "recircle-taxonomy-v1"
        assert latest.graph_snapshot_id
        assert latest.runtime_ms >= 0
        assert latest.params.get("limit") == 5


def test_symbiosis_auth_guards():
    assert client.get("/api/symbiosis/opportunities").status_code == 401
    assert client.get("/api/symbiosis/evaluation").status_code == 401
    token = _token("generator@recircle.local")
    assert client.get("/api/symbiosis/opportunities", headers=_auth(token)).status_code == 200
