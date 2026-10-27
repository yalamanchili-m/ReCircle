import csv
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditLog, ImpactEstimate, Organization, RecoveryRecord
from app.services import carbon

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


def _scoped_db_records(db, org_id):
    """Recovery records where the given org is seller or buyer (mirrors API scope)."""
    from app.models import MaterialRequirement, Offer, Transaction, WasteListing

    return db.scalars(
        select(RecoveryRecord)
        .join(Transaction, RecoveryRecord.transaction_id == Transaction.id)
        .join(Offer, Transaction.offer_id == Offer.id)
        .join(WasteListing, Offer.listing_id == WasteListing.id)
        .join(MaterialRequirement, Offer.requirement_id == MaterialRequirement.id)
        .where(
            (WasteListing.organization_id == org_id)
            | (MaterialRequirement.organization_id == org_id)
        )
    ).all()


def test_dashboard_metrics_reconcile_to_source_records():
    token = _login("buyer@recircle.local")
    body = client.get("/api/esg/dashboard", headers=_auth(token)).json()

    with SessionLocal() as db:
        buyer_org = db.scalar(
            select(Organization).where(Organization.name == "GreenPack Industries")
        )
        records = _scoped_db_records(db, buyer_org.id)
        current_estimates = [
            db.scalar(
                select(ImpactEstimate).where(
                    ImpactEstimate.recovery_record_id == record.id,
                    ImpactEstimate.is_current.is_(True),
                )
            )
            for record in records
        ]

    coverage = body["coverage"]
    assert coverage["recovery_record_count"] == len(records)

    # Recovered quantities reconcile to source records, grouped per unit
    unit_rows = body["metrics"]["recovered_by_unit"]
    per_unit: dict[str, float] = {}
    for record in records:
        unit_rows_expected_value = per_unit.setdefault(str(record.unit), 0.0)
        per_unit[str(record.unit)] = unit_rows_expected_value + float(
            record.recovered_quantity
        )
    for row in unit_rows:
        assert row["basis"] == "user_reported"
        assert row["record_count"] == sum(
            1 for r in records if str(r.unit) == row["unit"]
        )
        assert abs(row["total"] - per_unit[row["unit"]]) < 0.001

    # Impact metrics are estimates with explicit provenance, summed over
    # the single current estimate of each source record (never duplicated)
    avoided = body["metrics"]["avoided_emissions"]
    supported = [est for est in current_estimates if est is not None and est.supported]
    expected_co2 = sum(float(est.avoided_co2e_kg or 0) for est in supported)
    expected_kg = sum(float(est.landfill_diverted_kg or 0) for est in supported)
    assert avoided["basis"] == "estimated (factor-based)"
    assert avoided["factor_catalog_version"] == carbon.FACTOR_CATALOG_VERSION
    assert abs(avoided["kg_co2e_estimate"] - expected_co2) < 0.001
    assert body["metrics"]["landfill_diverted"]["basis"] == "estimated (factor-based)"
    assert abs(body["metrics"]["landfill_diverted"]["kg_estimate"] - expected_kg) < 0.001
    assert coverage["records_with_supported_estimate"] == len(supported)

    # Metric states distinguish estimated / user-reported / verified
    assert "estimated" in body["metric_states"]
    assert "user_reported" in body["metric_states"]


def test_dashboard_requires_auth():
    assert client.get("/api/esg/dashboard").status_code == 401


def test_period_filters():
    token = _login("buyer@recircle.local")
    empty = client.get(
        "/api/esg/dashboard?period_from=2999-01-01", headers=_auth(token)
    ).json()
    assert empty["coverage"]["recovery_record_count"] == 0
    assert empty["metrics"]["avoided_emissions"]["kg_co2e_estimate"] == 0.0
    assert empty["records"] == []

    all_time = client.get(
        "/api/esg/dashboard?period_from=2000-01-01", headers=_auth(token)
    ).json()
    assert all_time["coverage"]["recovery_record_count"] >= 1

    invalid = client.get(
        "/api/esg/dashboard?period_from=2999-01-01&period_to=2998-01-01",
        headers=_auth(token),
    )
    assert invalid.status_code == 422


def test_superseded_estimates_never_double_count():
    token = _login("buyer@recircle.local")
    baseline = client.get("/api/esg/dashboard", headers=_auth(token)).json()
    co2_before = baseline["metrics"]["avoided_emissions"]["kg_co2e_estimate"]

    with SessionLocal() as db:
        record = db.scalar(select(RecoveryRecord))
        # Simulate a factor-catalog update: a fresh estimate recomputation
        # must demote the previous current row and never add to totals.
        estimate = carbon.estimate_and_persist(db, record, "paper_cardboard")
        db.commit()
        assert estimate.is_current is True
        count_current = db.scalar(
            select(func.count())
            .select_from(ImpactEstimate)
            .where(
                ImpactEstimate.recovery_record_id == record.id,
                ImpactEstimate.is_current.is_(True),
            )
        )
        assert count_current == 1

    after = client.get("/api/esg/dashboard", headers=_auth(token)).json()
    assert (
        after["metrics"]["avoided_emissions"]["kg_co2e_estimate"] == co2_before
    )
    assert (
        after["metrics"]["landfill_diverted"]["kg_estimate"]
        == baseline["metrics"]["landfill_diverted"]["kg_estimate"]
    )
    # Older row remains as history but only one row is ever current
    with SessionLocal() as db:
        total = db.scalar(
            select(func.count())
            .select_from(ImpactEstimate)
            .where(ImpactEstimate.recovery_record_id == record.id)
        )
        assert total >= 2


def test_one_current_estimate_per_record_enforced_by_database():
    with SessionLocal() as db:
        record = db.scalar(select(RecoveryRecord))
        db.add(
            ImpactEstimate(
                recovery_record_id=record.id,
                recovery_route="recycle",
                supported=True,
                method=carbon.METHOD,
                factor_catalog_version="corrupt-row",
                factor_source="test",
                baseline_reference="test",
                is_current=True,
            )
        )
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_csv_export_shape_and_audit():
    token = _login("buyer@recircle.local")
    with SessionLocal() as db:
        before = db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "esg.export")
        )

    response = client.get("/api/esg/export", headers=_auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text.strip())))
    assert rows and rows[0][0] == "recovery_record_id"
    header = rows[0]
    # Header plus one reconcilable data row for the demo record
    assert len(rows) >= 2
    data_row = rows[1]
    uncertainty = data_row[header.index("uncertainty")]
    assert uncertainty.startswith("[") and ";" in uncertainty

    with SessionLocal() as db:
        after = db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "esg.export")
        )
    assert after == before + 1

    # Export requires authentication
    assert client.get("/api/esg/export").status_code == 401


def test_cross_organization_scoping():
    # Each organization only sees records it is a party to; the admin demo
    # organization is not part of the demo trade nor the test trades.
    with SessionLocal() as db:
        admin_org = db.scalar(
            select(Organization).where(
                Organization.name == "ReCircle Demo Administration"
            )
        )
        admin_expected = len(_scoped_db_records(db, admin_org.id))

    token = _login("admin@recircle.local")
    admin_body = client.get("/api/esg/dashboard", headers=_auth(token)).json()
    assert admin_body["coverage"]["recovery_record_count"] == admin_expected

    buyer_token = _login("buyer@recircle.local")
    buyer_body = client.get("/api/esg/dashboard", headers=_auth(buyer_token)).json()
    assert (
        buyer_body["coverage"]["recovery_record_count"]
        > admin_body["coverage"]["recovery_record_count"]
    )
