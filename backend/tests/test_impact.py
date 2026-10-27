"""Tests for differential factor impact estimation (v2, blueprint Phase 9)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import ImpactEstimate, RecoveryRecord
from app.services import carbon

client = TestClient(app)


# ---------------------------------------------------------------- pure math


def test_mass_conversion_and_differential_arithmetic_cardboard_recycle():
    result = carbon.compute_estimate(
        "paper_cardboard", "recycle", Decimal("500.000"), "kg"
    )
    assert result["supported"] is True
    assert result["quantity_tonnes"] == Decimal("0.500000")
    # Differential: (670 - (-900)) kg/t * 0.5 t = 785 kg
    assert result["avoided_co2e_kg"] == Decimal("785.000")
    assert result["landfill_diverted_kg"] == Decimal("500.000")
    # Worst-case interval: 335*0.50 + 450*0.35 = 325 band around 785
    assert result["avoided_co2e_kg_low"] == Decimal("460.000")
    assert result["avoided_co2e_kg_high"] == Decimal("1110.000")
    terms = result["formula_terms"]
    assert terms[0]["term"] == "baseline (landfill) intensity"
    assert terms[0]["factor"] == 670.0
    assert terms[0]["signed_contribution_kg"] == 335.0
    assert terms[0]["unit"] == carbon.FACTOR_UNIT
    assert terms[0]["source"] == carbon.FACTOR_SOURCE
    assert terms[1]["term"] == "route (recycle) intensity"
    assert terms[1]["factor"] == -900.0
    # Substitution credit: contributes +450 to avoided (negative emissions)
    assert terms[1]["signed_contribution_kg"] == 450.0


def test_kg_to_tonne_conversion_is_centralized():
    kg = carbon.compute_estimate("metals", "recycle", Decimal("2500.000"), "kg")
    tonne = carbon.compute_estimate("metals", "recycle", Decimal("2.500"), "tonne")
    # (12 - (-1850)) * 2.5 t = 4655 kg regardless of input unit
    assert kg["avoided_co2e_kg"] == tonne["avoided_co2e_kg"] == Decimal("4655.000")
    assert kg["quantity_tonnes"] == tonne["quantity_tonnes"] == Decimal("2.500000")


def test_landfill_route_equals_baseline_zero_by_construction():
    result = carbon.compute_estimate("plastics", "landfill", Decimal("100.000"), "kg")
    assert result["supported"] is True
    assert result["avoided_co2e_kg"] == Decimal("0.000")
    assert result["landfill_diverted_kg"] == Decimal("0.000")
    assert result["formula_terms"] == []
    assert "baseline" in result["reason"].lower()


def test_non_mass_units_are_unsupported_not_zero():
    result = carbon.compute_estimate("plastics", "recycle", Decimal("10.000"), "litre")
    assert result["supported"] is False
    assert result["avoided_co2e_kg"] is None
    assert result["quantity_tonnes"] is None
    assert "convertible" in result["unsupported_reason"]


def test_route_combinations_without_curated_factors_are_unsupported():
    # chemicals/other have a landfill baseline but no recovery-route factors
    for category in ("chemicals", "other", "organics"):
        result = carbon.compute_estimate(category, "recycle", Decimal("10.000"), "kg")
        assert result["supported"] is False
        assert result["avoided_co2e_kg"] is None
        assert "No curated factor" in result["unsupported_reason"]


def test_route_other_has_no_pathway():
    result = carbon.compute_estimate("plastics", "other", Decimal("10.000"), "kg")
    assert result["supported"] is False
    assert result["avoided_co2e_kg"] is None
    assert "impact pathway" in result["unsupported_reason"]


def test_missing_landfill_baseline_is_explicitly_unsupported():
    # Simulate a category with a route factor but no baseline (ingestion gap)
    merged = dict(carbon.CATALOG)
    del merged[("glass", carbon.BASELINE_PATHWAY)]
    saved = carbon.CATALOG
    try:
        carbon.CATALOG = merged
        result = carbon.compute_estimate("glass", "recycle", Decimal("10.000"), "kg")
    finally:
        carbon.CATALOG = saved
    assert result["supported"] is False
    assert "landfill baseline" in result["unsupported_reason"]


def test_every_curated_route_is_deterministic_and_profile_perfect():
    categories = {category for category, _ in carbon.CATALOG}
    for category in categories:
        baseline = carbon._row(category, carbon.BASELINE_PATHWAY)
        assert baseline is not None, f"{category} lacks a landfill baseline"
        assert baseline.value >= 0
    for (category, route), row in carbon.CATALOG.items():
        result = carbon.compute_estimate(
            category, route, Decimal("123456.000"), "kg"
        )
        assert result["supported"] is True, (category, route)
        assert result == carbon.compute_estimate(
            category, route, Decimal("123456.000"), "kg"
        )
        if route == carbon.BASELINE_PATHWAY:
            assert result["avoided_co2e_kg"] == Decimal("0.000")
        else:
            baseline = carbon._row(category, carbon.BASELINE_PATHWAY)
            expected = (
                (Decimal(str(baseline.value)) - Decimal(str(row.value)))
                * Decimal("123.456")
            ).quantize(Decimal("0.001"))
            assert result["avoided_co2e_kg"] == expected
            # Interval band must contain the central estimate
            assert result["avoided_co2e_kg_low"] <= result["avoided_co2e_kg"]
            assert result["avoided_co2e_kg_high"] >= result["avoided_co2e_kg"]


def test_uncertainty_is_v1_worst_case_on_widest_row():
    # plastics/energy_recovery: 35 vs -40; band = 35*0.5 + 40*0.35 = 31.5 per
    # tonne; with 2 tonnes: avoided = 150, band = 63
    result = carbon.compute_estimate(
        "plastics", "energy_recovery", Decimal("2"), "tonne"
    )
    assert result["avoided_co2e_kg"] == Decimal("150.000")
    assert result["avoided_co2e_kg_low"] == Decimal("87.000")
    assert result["avoided_co2e_kg_high"] == Decimal("213.000")


# ------------------------------------------------------- catalog validation


def _valid_row(category, pathway, value, uncertainty=0.35):
    return {
        "category": category,
        "pathway": pathway,
        "quantity_kg_co2e_per_tonne": value,
        "uncertainty_ratio": uncertainty,
    }


def test_validate_factor_catalog_accepts_a_clean_ingest():
    report = carbon.validate_factor_catalog(
        [_valid_row("paper_cardboard", "landfill", 700), _valid_row("paper_cardboard", "recycle", -1000)]
    )
    assert report["accepted_count"] == 2
    assert report["rejected_count"] == 0
    assert report["missing_baseline_categories"] == []
    assert report["factor_unit"] == carbon.FACTOR_UNIT


def test_validate_factor_catalog_rejects_bad_input_with_reasons():
    report = carbon.validate_factor_catalog(
        [
            _valid_row("glass", "landfill", 12.0),  # accepted
            _valid_row("glass", "recycle", "nope"),  # invalid value type
            _valid_row("glass", "reuse", -90.0, uncertainty=1.5),  # out of [0,1]
            {"category": "wood", "pathway": "recycle", "quantity_kg_co2e_per_tonne": -350},  # missing uncertainty is defaulted
            _valid_row("", "recycle", 1.0),  # empty category
            _valid_row("metals", "landfill", 12.0),  # duplicate below
            _valid_row("metals", "landfill", 12.0),
        ]
    )
    assert report["accepted_count"] == 3
    assert report["rejected_count"] == 4
    reasons = [entry["reason"] for entry in report["rejected"]]
    assert sum("invalid value" in r for r in reasons) == 1
    assert sum("uncertainty_ratio" in r for r in reasons) == 1
    assert sum("duplicate row" in r for r in reasons) == 1
    assert sum("category" in r for r in reasons) == 1
    # The wood recycle row is accepted, but wood has no baseline in this set
    assert report["missing_baseline_categories"] == ["wood"]


# ----------------------------------------------------- persistence and APIs


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed()


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _category_for_record(db, record):
    from app.models import MaterialRequirement, Offer, Transaction, WasteListing

    return db.scalar(
        select(WasteListing.category)
        .join(Offer, Offer.listing_id == WasteListing.id)
        .join(Transaction, Transaction.offer_id == Offer.id)
        .join(MaterialRequirement, Offer.requirement_id == MaterialRequirement.id)
        .where(Transaction.id == record.transaction_id)
    )


def test_estimate_and_persist_persists_provenance_and_band():
    with SessionLocal() as db:
        record = db.scalar(select(RecoveryRecord))
        category = _category_for_record(db, record)
        estimate = carbon.estimate_and_persist(db, record, category)
        db.commit()
        estimate_id = estimate.id
        record_route = record.recovery_route or "other"
        record_qty = record.recovered_quantity
        record_unit = record.unit

    with SessionLocal() as db:
        estimate = db.get(ImpactEstimate, estimate_id)
        assert estimate.supported
        assert estimate.method == carbon.METHOD
        assert estimate.factor_catalog_version == carbon.FACTOR_CATALOG_VERSION
        assert estimate.landfill_diverted_kg is not None
        expected = carbon.compute_estimate(
            category or "other",
            record_route,
            record_qty,
            record_unit,
        )
        assert estimate.avoided_co2e_kg == expected["avoided_co2e_kg"]
        assumptions = estimate.assumptions
        assert assumptions["avoided_co2e_kg_low"] == float(
            expected["avoided_co2e_kg_low"]
        )
        assert assumptions["avoided_co2e_kg_high"] == float(
            expected["avoided_co2e_kg_high"]
        )
        assert assumptions["uncertainty_basis"].startswith("worst-case")
        assert assumptions["formula_terms"] == expected["formula_terms"]
        assert len(assumptions["items"]) == len(carbon.ASSUMPTIONS)
        assert assumptions["limitations"] == carbon.LIMITATIONS


def test_recompute_all_estimates_regenerates_with_current_catalog():
    with SessionLocal() as db:
        stats = carbon.recompute_all_estimates(db)
        db.commit()

    assert stats["failed"] == 0
    assert stats["catalog_version"] == carbon.FACTOR_CATALOG_VERSION
    assert stats["method"] == carbon.METHOD
    assert stats["total_recovery_records"] >= stats["recomputed"]

    with SessionLocal() as db:
        for estimate in db.scalars(
            select(ImpactEstimate).where(ImpactEstimate.is_current.is_(True))
        ):
            assert estimate.method == carbon.METHOD
            assert estimate.factor_catalog_version == carbon.FACTOR_CATALOG_VERSION
            if estimate.supported:
                assert estimate.assumptions["avoided_co2e_kg_low"] is not None


def test_impact_factor_visibility_endpoint():
    token = _login("buyer@recircle.local")
    body = client.get("/api/impact/factors", headers=_auth(token)).json()
    assert body["factor_catalog_version"] == carbon.FACTOR_CATALOG_VERSION
    assert body["factor_source"] == carbon.FACTOR_SOURCE
    assert body["method"] == carbon.METHOD
    assert sorted(body["supported_units"]) == ["kg", "tonne"]
    rows = body["rows"]
    assert {r["pathway"] for r in rows} >= {carbon.BASELINE_PATHWAY}
    assert all("value" in row and "uncertainty_ratio" in row for row in rows)
    assert client.get("/api/impact/factors").status_code == 401


def test_impact_recompute_endpoint_is_admin_gated_and_audited():
    buyer = _login("buyer@recircle.local")
    assert client.post("/api/impact/recompute", headers=_auth(buyer)).status_code == 403

    admin = _login("admin@recircle.local")
    body = client.post("/api/impact/recompute", headers=_auth(admin))
    assert body.status_code == 200
    stats = body.json()
    assert stats["failed"] == 0
    assert stats["catalog_version"] == carbon.FACTOR_CATALOG_VERSION


# ----------------------------------------------------------- credit proxying


def test_green_credit_formula_is_documented_and_deterministic():
    assert carbon.CREDIT_DISCLAIMERS, "disclaimers are mandatory"
    assert carbon.green_credit_points(None, None) == 0
    # Indicative: 1 point per kg material diverted + 1 point per kg CO2e avoided
    assert carbon.green_credit_points(500.0, 450.0) == 950
    assert carbon.green_credit_points(785.0, 0.0) == 785
