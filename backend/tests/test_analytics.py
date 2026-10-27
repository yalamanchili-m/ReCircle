"""Marketplace metrics + K-means analytics tests (blueprint Phase 11)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AnalyticsRun, AuditLog, MaterialRequirement, Transaction, User, WasteListing
from app.services import analytics, kmeans

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


# ------------------------------------------------------------ kmeans engine


def _two_blobs():
    low = [[0.0, 0.0], [0.02, -0.02], [-0.02, 0.02], [0.01, 0.0], [-0.01, 0.01],
           [0.03, 0.01], [0.0, 0.01], [0.02, 0.02], [-0.03, -0.01], [0.01, 0.03]]
    high = [[5.0, 5.0], [5.02, 4.98], [4.98, 5.02], [5.01, 5.0], [4.99, 5.01],
            [5.03, 5.01], [5.0, 5.01], [5.02, 5.02], [4.97, 4.99], [5.01, 5.03]]
    return low + high


def test_kmeans_is_deterministic_and_separates():
    points = _two_blobs()
    first = kmeans.deterministic_kmeans(points, 2)
    second = kmeans.deterministic_kmeans(points, 2)
    assert first == second
    assignments = first["assignments"]
    assert len(set(assignments[:10])) == 1
    assert len(set(assignments[10:])) == 1
    assert assignments[0] != assignments[10]
    assert first["inertia"] < 0.5


def test_kmeans_rejects_invalid_configuration():
    with pytest.raises(kmeans.KMeansError):
        kmeans.deterministic_kmeans(_two_blobs(), 1)
    with pytest.raises(kmeans.KMeansError):
        kmeans.deterministic_kmeans(_two_blobs(), 13)
    with pytest.raises(kmeans.KMeansError):
        kmeans.deterministic_kmeans([[0, 0]], 2)  # n < k


def test_kmeans_handles_degenerate_identical_points():
    points = [[1.0, 2.0]] * 8
    result = kmeans.deterministic_kmeans(points, 2)
    assert len(result["assignments"]) == 8
    assert "centroids" in result


def test_silhouette_is_high_for_clean_configuration():
    points = _two_blobs()
    result = kmeans.deterministic_kmeans(points, 2)
    silhouette = kmeans.silhouette_reduction(points, result["assignments"])
    assert silhouette > 0.9


def test_silhouette_needs_two_clusters():
    points = [[1.0, 1.0]] * 6
    score = kmeans.silhouette_reduction(points, [0, 0, 0, 0, 0, 0])
    assert score == 0.0


# ----------------------------------------------------- clustering API + runs


def _get_admin(db):
    return db.scalar(select(User).where(User.email == "admin@recircle.local"))


def test_kmeans_service_insufficient_data_gate(monkeypatch):
    monkeypatch.setattr(analytics, "MIN_SAMPLE_THRESHOLD", 10_000)
    with SessionLocal() as db:
        admin = _get_admin(db)
        payload = analytics.run_kmeans(db, admin, "listings", None, None)
        db.commit()
    assert payload["insufficient_data"] is True
    assert payload["min_sample_threshold"] == 10_000
    assert payload["result"] is None
    assert "clustering needs at" in payload["empty_state"]


def test_kmeans_endpoint_deterministic_and_run_recorded():
    admin = _login("admin@recircle.local")
    with SessionLocal() as db:
        before = db.scalar(
            select(func.count())
            .select_from(AnalyticsRun)
            .where(AnalyticsRun.run_kind == "kmeans")
        )
    first = client.post(
        "/api/analytics/kmeans?subject=listings", headers=_auth(admin)
    ).json()
    second = client.post(
        "/api/analytics/kmeans?subject=listings", headers=_auth(admin)
    ).json()
    with SessionLocal() as db:
        after = db.scalar(
            select(func.count())
            .select_from(AnalyticsRun)
            .where(AnalyticsRun.run_kind == "kmeans")
        )
    assert after == before + 2
    first_copy = {key: value for key, value in first.items() if key != "run_id"}
    second_copy = {key: value for key, value in second.items() if key != "run_id"}
    assert first_copy == second_copy, (
        "fixed inputs/config must reproduce identical clusters"
    )
    if first["insufficient_data"]:
        # Small fresh datasets must fall back to an honest gate, never a
        # fabricated partition
        assert first["result"] is None
        assert first["sample_count"] < analytics.MIN_SAMPLE_THRESHOLD
        return
    assert first["k"] == min(4, max(2, first["sample_count"] // 10))
    clusters = first["stats"]["clusters"]
    assert sum(c["size"] for c in clusters) == first["sample_count"]
    assert first["result_version"] == kmeans.RESULT_VERSION
    feature_names = [row["feature"] for row in first["feature_schema"]]
    assert "category_metals" in feature_names
    assert all("title" not in f and f != "listing_id" for f in feature_names)
    assert first["versions"]["feature_schema"] == analytics.FEATURE_SCHEMA_VERSION
    assert any(
        "NOT authoritative" in disclaimer
        for disclaimer in first["disclaimers"]
    )


def test_kmeans_invalid_subject_422_run_recorded_as_failed_and_401():
    assert client.post("/api/analytics/kmeans?subject=nonsense").status_code == 401
    admin = _login("admin@recircle.local")
    response = client.post(
        "/api/analytics/kmeans?subject=nonsense", headers=_auth(admin)
    )
    assert response.status_code == 422
    with SessionLocal() as db:
        failed = db.scalars(
            select(AnalyticsRun)
            .where(AnalyticsRun.run_kind == "kmeans", AnalyticsRun.status == "failed")
            .order_by(AnalyticsRun.started_at.desc())
        ).first()
    assert failed is not None and failed.error


def test_kmeans_out_of_range_k_422():
    admin = _login("admin@recircle.local")
    response = client.post(
        "/api/analytics/kmeans?subject=listings&k=50", headers=_auth(admin)
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- metrics API


def test_metrics_reconcile_to_database_records():
    buyer = _login("buyer@recircle.local")
    body = client.get(
        "/api/analytics/marketplace?period_from=2000-01-01", headers=_auth(buyer)
    ).json()

    with SessionLocal() as db:
        expected_status = dict(
            db.execute(
                select(WasteListing.status, func.count()).group_by(WasteListing.status)
            ).all()
        )
        expected_req_active = db.scalar(
            select(func.count())
            .select_from(MaterialRequirement)
            .where(MaterialRequirement.status == "active")
        )
        expected_completed = db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.status == "completed")
        )
        metals_active = db.scalar(
            select(func.count())
            .select_from(WasteListing)
            .where(WasteListing.status == "active", WasteListing.category == "metals")
        )

    listings = body["metrics"]["listings"]
    assert listings == expected_status
    sd_all = {row["category"]: row for row in body["metrics"]["supply_demand_rows"]}
    assert sd_all["metals"]["active_listings"] == metals_active
    assert(
        sum(row["active_requirements"] for row in body["metrics"]["supply_demand_rows"])
        == expected_req_active
    )
    assert body["metrics"]["match_activity"]["transactions_completed"] == expected_completed
    assert body["version"] == analytics.METRICS_VERSION
    assert body["limitations"] == analytics.METRICS_LIMITATIONS


def test_geography_gate_matches_coverage():
    token = _login("admin@recircle.local")
    body = client.get(
        "/api/analytics/marketplace?period_from=2000-01-01", headers=_auth(token)
    ).json()
    geo = body["metrics"]["geography"]
    with SessionLocal() as db:
        active = db.scalars(
            select(WasteListing).where(WasteListing.status == "active")
        ).all()
    coverage = (
        sum(1 for row in active if row.region) / len(active) if active else 0.0
    )
    assert geo["coverage"] == round(coverage, 3)
    if geo["available"]:
        assert coverage >= analytics.REGION_COVERAGE_RELIABLE
        # Rows cover exactly the region-known listings, never more
        region_known = sum(1 for row in active if row.region)
        assert sum(row["active_listings"] for row in geo["rows"]) == region_known
    else:
        assert geo["rows"] == []
        assert geo["reason"]


def test_geography_omitted_when_coverage_threshold_not_met(monkeypatch):
    monkeypatch.setattr(analytics, "REGION_COVERAGE_RELIABLE", 1.01)
    token = _login("admin@recircle.local")
    body = client.get(
        "/api/analytics/marketplace?period_from=2000-01-01", headers=_auth(token)
    ).json()
    geo = body["metrics"]["geography"]
    assert geo["available"] is False
    assert geo["rows"] == []
    assert "reliable" in geo["reason"]


def test_time_series_only_with_multi_month_coverage():
    admin = _login("admin@recircle.local")

    # Default 90-day window on a fresh dataset: gated to available/absent
    default_body = client.get("/api/analytics/marketplace", headers=_auth(admin)).json()
    default_ts = default_body["metrics"]["time_series"]
    if default_ts["available"]:
        assert len(default_ts["rows"]) >= 1
    else:
        assert "coverage" in default_ts["reason"]

    # Age a probe listing back to August so a multi-month series is supported
    response = client.post(
        "/api/listings",
        json={
            "title": "Analytics Probe Aged August",
            "description": "Analytics probe listing (synthetic test).",
            "category": "glass",
            "quantity": "50.000",
            "unit": "kg",
            "city": "Pune",
            "region": "Maharashtra",
        },
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    listing_id = uuid.UUID(response.json()["id"])
    with SessionLocal() as db:
        listing = db.get(WasteListing, listing_id)
        aged = listing.created_at.replace(month=8, day=15)
        listing.created_at = aged
        listing.updated_at = aged
        db.commit()

    wide = client.get(
        "/api/analytics/marketplace?period_from=2026-08-01&period_to=2026-10-27",
        headers=_auth(admin),
    ).json()
    ts = wide["metrics"]["time_series"]
    assert ts["available"] is True
    months = [row["month"] for row in ts["rows"]]
    assert "2026-08" in months
    assert len(months) >= analytics.TIME_SERIES_MIN_MONTHS
    august = next(row for row in ts["rows"] if row["month"] == "2026-08")
    assert august["listings_created"] >= 1


def test_metrics_filters_pathways_and_empty_states():
    buyer = _login("buyer@recircle.local")
    body = client.get(
        "/api/analytics/marketplace?category=chemicals&period_from=2000-01-01",
        headers=_auth(buyer),
    ).json()
    rows = body["metrics"]["supply_demand_rows"]
    assert rows and rows[0]["category"] == "chemicals"
    # Hard safety gate: chemicals only ever ranks recycle
    assert body["metrics"]["pathway_rows"][0]["feasible_pathways"] == ["recycle"]

    inverted = client.get(
        "/api/analytics/marketplace?period_from=2026-10-27&period_to=2026-01-01",
        headers=_auth(buyer),
    )
    assert inverted.status_code == 422

    # A genuinely empty (not inverted) period yields honest empty metrics
    future = client.get(
        "/api/analytics/marketplace?period_from=2999-01-01&period_to=2999-12-31",
        headers=_auth(buyer),
    ).json()
    assert future["metrics"]["listings"].get("active", 0) == 0
    assert any("No active listings" in w for w in future["metrics"]["warnings"])


def test_export_csv_has_no_private_org_data_and_runs_are_audited():
    buyer = _login("buyer@recircle.local")
    with SessionLocal() as db:
        before = db.scalar(
            select(func.count()).select_from(AnalyticsRun).where(AnalyticsRun.run_kind == "marketplace_metrics")
        )
    response = client.get("/api/analytics/marketplace/export", headers=_auth(buyer))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.text
    assert text.startswith("section,key,value")
    for org_name in ("Shakti", "GreenPack", "ReCircle Demo"):
        assert org_name not in text
    for forbidden in ("@recircle.local", "listing_title", "organization"):
        assert forbidden not in text
    with SessionLocal() as db:
        after = db.scalar(
            select(func.count()).select_from(AnalyticsRun).where(AnalyticsRun.run_kind == "marketplace_metrics")
        )
    assert after == before + 1
    # The export action itself is audited
    with SessionLocal() as db:
        audit_rows = db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "analytics.export")
        )
    assert audit_rows >= 1


def test_export_auth_and_recompute_admin_only():
    assert client.get("/api/analytics/marketplace/export").status_code == 401
    buyer = _login("buyer@recircle.local")
    assert client.post("/api/analytics/recompute", headers=_auth(buyer)).status_code == 403
    admin = _login("admin@recircle.local")
    body = client.post("/api/analytics/recompute", headers=_auth(admin))
    assert body.status_code == 200
    payload = body.json()
    assert payload["marketplace_metrics"]["version"] == analytics.METRICS_VERSION
    assert set(payload) == {"listings", "requirements", "marketplace_metrics"}
