"""Tests for external data ingestion (blueprint Phase 15).

Covers: curated source registry + idempotent sync; WARM factor CSV
end-to-end import (upload) that activates a DB-backed factor catalog
consumed by carbon estimates; validation reports with rejected rows;
quarantine of route rows lacking a landfill baseline; missing-value honesty
(NA/NE/blank never zero-filled); idempotent reruns (skipped + forced);
tabular material-flow import with supersede/dedupe lifecycle; failure
recording; admin gating.

All fixture datasets here are SYNTHETIC (marked in the notes column); they
exercise the pipeline only. Real factors arrive via admin imports of
upstream extracts.
"""

import csv
import io
import re
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import ExternalDataRecord, ExternalDataSource, ExternalWarmFactor
from app.models.data_ingestion import IngestionRun, RawIngestionFile
from app.services import carbon
from app.services.data_ingestion import ingest, sources

client = TestClient(app)

# NOTE: SYNTHETIC values. Not EPA-hosted numbers.
WARM_CSV = (
    "material_category,management_pathway,quantity_kg_co2e_per_tonne,uncertainty_ratio,note\n"
    "paper_cardboard,landfill,670,0.5,SYNTHETIC baseline\n"
    "paper_cardboard,recycle,-900,0.3,SYNTHETIC credit\n"
    "metals,landfill,12,0.4,SYNTHETIC baseline\n"
    "metals,reuse,-1600,,synthetic; uncertainty ratio defaulted\n"
    "glass,landfill,12,0.4,SYNTHETIC baseline\n"
    "plastics,recycle,-1250,0.3,SYNTHETIC credit (no plastics baseline -> quarantine)\n"
    "plastics,compost,NA,0.3,SYNTHETIC missing value -> rejected\n"
    "plastics,recycle,-1250,0.3,SYNTHETIC duplicate row -> rejected\n"
    "wood,recycle,-350,0.3,SYNTHETIC route without baseline -> quarantine\n"
)


def _warm_bytes() -> bytes:
    return WARM_CSV.encode("utf-8")


@pytest.fixture(scope="module", autouse=True)
def _dataset():
    seed()
    yield
    _cleanup()


def _cleanup() -> None:
    with SessionLocal() as db:
        db.execute(delete(ExternalWarmFactor))
        db.execute(delete(ExternalDataRecord))
        db.execute(delete(RawIngestionFile))
        db.execute(delete(IngestionRun))
        for row in db.scalars(select(ExternalDataSource)).all():
            row.latest_file_hash = None
            row.latest_run_at = None
            if row.key == "oecd_mfa":
                row.declared_version = None
        db.commit()
    staged_root = ingest.STAGED_ROOT
    if staged_root.exists():
        for child in sorted(staged_root.iterdir(), reverse=True):
            for grandchild in child.iterdir():
                grandchild.unlink()
            child.rmdir()


def _deactivate_and_clear_warm() -> None:
    with SessionLocal() as db:
        db.execute(delete(ExternalWarmFactor))
        db.commit()


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin() -> str:
    return _login("admin@recircle.local")


def _warm_import(token, **params):
    return client.post(
        "/api/data-ingestion/import",
        params={
            "source_key": "epa_warm_v15",
            "declared_version": "15.2-synthetic",
            **params,
        },
        files={"file": ("warm_factors_synthetic.csv", _warm_bytes(), "text/csv")},
        headers=_auth(token),
    )


# --------------------------------------------------------- registry + gating


def test_registry_curates_sources_with_terms_and_capability():
    for entry in sources.DATA_SOURCE_REGISTRY:
        assert sources._KEY_PATTERN.match(entry["key"])
        assert entry["terms_note"]
        assert entry["homepage_url"].startswith("https://")
        assert entry["update_cadence"]
        assert entry["family"] and entry["jurisdiction"]
    implemented = [
        entry for entry in sources.DATA_SOURCE_REGISTRY if entry["adapter_status"] == "implemented"
    ]
    planned = [
        entry for entry in sources.DATA_SOURCE_REGISTRY if entry["adapter_status"] == "planned"
    ]
    assert {entry["key"] for entry in implemented} == {"epa_warm_v15", "oecd_mfa"}
    assert {entry["key"] for entry in planned} == {"cpcb_india", "us_epa_biennial"}
    # Blueprint priority: WARM first
    assert (
        next(e for e in implemented if e["key"] == "epa_warm_v15")["family"]
        == "factor_catalog"
    )


def test_sources_endpoint_and_idempotent_ensure():
    token = _admin()
    payload = client.get("/api/data-ingestion/sources", headers=_auth(token)).json()
    keys = {source["key"] for source in payload["sources"]}
    assert {"epa_warm_v15", "oecd_mfa", "cpcb_india", "us_epa_biennial"} <= keys
    assert payload["registry_version"].startswith("data-source-registry-")

    with SessionLocal() as db:
        first = sources.ensure_sources(db)
        second = sources.ensure_sources(db)
        assert first["created"] + first["updated"] >= 1
        assert second["created"] == 0 and second["updated"] >= 1
        db.commit()
    assert client.get("/api/data-ingestion/sources").status_code == 401


def test_import_requires_admin_and_records_failures():
    buyer = _login("buyer@recircle.local")
    assert _warm_import(buyer).status_code == 403
    assert client.post(
        "/api/data-ingestion/import",
        params={"source_key": "epa_warm_v15"},
        files={"file": ("x.csv", b"a,b\n1,2")},
    ).status_code == 401

    admin = _admin()

    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "cpcb_india"},
        files={"file": ("x.csv", b"a,b\n1,2")},
        headers=_auth(admin),
    )
    assert response.status_code == 422
    assert "enabled" in response.json()["detail"]

    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "not_a_source"},
        files={"file": ("x.csv", b"a,b\n1,2")},
        headers=_auth(admin),
    )
    assert response.status_code == 422

    with SessionLocal() as db:
        failed = db.scalars(
            select(IngestionRun).where(IngestionRun.status == "failed")
        ).all()
        assert failed, "failed attempts must be recorded as runs"
        assert any(run.error for run in failed)


def test_import_refuses_empty_and_wrong_type_files():
    admin = _admin()
    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "epa_warm_v15"},
        files={"file": ("empty.csv", b"", "text/csv")},
        headers=_auth(admin),
    )
    assert response.status_code == 422
    assert "empty" in response.json()["detail"]

    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "epa_warm_v15"},
        files={"file": ("binary.bin", b"\x00\x01\x02garbage", "application/octet-stream")},
        headers=_auth(admin),
    )
    assert response.status_code == 422
    assert "allow" in response.json()["detail"].lower()


# ------------------------------------------------------- WARM end-to-end flow


def test_warm_import_runs_end_to_end_with_validation_and_quarantine():
    admin = _admin()
    _deactivate_and_clear_warm()
    response = _warm_import(admin)
    assert response.status_code == 200, response.text
    payload = response.json()
    stats = payload["stats"]
    assert payload["status"] == "success"

    # 9 rows: 5 accepted (active), 2 quarantined (plastics+wood routes lack
    # baselines in-file), 2 rejected (NA value, duplicate).
    assert stats["accepted"] == 5
    assert stats["quarantined"] == 2
    assert stats["rejected"] == 2
    assert stats["missing_baseline_categories"] == ["plastics", "wood"]
    rejected_reasons = [row["reason"] for row in stats["rejected_rows"]]
    assert any("NA/NE/blank" in reason for reason in rejected_reasons)
    assert any("duplicate" in reason for reason in rejected_reasons)
    assert stats["factor_catalog_version"].startswith("factor-catalog-epa_warm_v15-v15.2-synthetic-")
    assert len(stats["factor_catalog_version"]) <= 60
    assert re.fullmatch(r"[A-Za-z0-9._+-]+", stats["factor_catalog_version"])
    assert "WARM" in stats["factor_source"].upper() or "US EPA" in stats["factor_source"]
    assert stats["warnings_total"] >= 1
    assert any("uncertainty" in warning for warning in stats["warnings"])

    with SessionLocal() as db:
        active = db.scalars(
            select(ExternalWarmFactor).where(ExternalWarmFactor.is_active.is_(True))
        ).all()
        assert len(active) == 5
        assert {row.category for row in active} == {
            "paper_cardboard",
            "metals",
            "glass",
        }
        assert {row.pathway for row in active} == {"landfill", "recycle", "reuse"}
        assert all(row.run_id is not None for row in active)
        assert not db.scalars(
            select(ExternalWarmFactor).where(ExternalWarmFactor.is_active.is_(False))
        ).all()
        raw = db.scalar(select(RawIngestionFile))
        assert raw.file_hash and len(raw.file_hash) == 64
        assert raw.import_count == 1
        assert "staged" in raw.stored_path

    # Rerunning the SAME file without force is skipped and adds nothing
    response = _warm_import(admin)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    with SessionLocal() as db:
        assert (
            db.scalar(select(func.count()).select_from(ExternalWarmFactor)) == 5
        )
        raw = db.scalar(select(RawIngestionFile))
        assert raw.import_count == 1

    # Forced rerun is safe: same set active, history shows one full set
    response = _warm_import(admin, force=True)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    with SessionLocal() as db:
        raw = db.scalar(select(RawIngestionFile))
        assert raw.import_count == 2
        actives = db.scalars(
            select(ExternalWarmFactor).where(ExternalWarmFactor.is_active.is_(True))
        ).all()
        assert len(actives) == 5
        assert len({row.catalog_version for row in actives}) == 1
        inactive = db.scalars(
            select(ExternalWarmFactor).where(ExternalWarmFactor.is_active.is_(False))
        ).all()
        assert len(inactive) == 5

    admin_runs = client.get(
        "/api/data-ingestion/runs",
        params={"source_key": "epa_warm_v15"},
        headers=_auth(admin),
    ).json()
    statuses = [run["status"] for run in admin_runs["runs"][:3]]
    assert statuses == ["success", "skipped", "success"]

    _deactivate_and_clear_warm()


def test_active_ingested_catalog_drives_carbon_estimates_then_reverts():
    admin = _admin()
    _deactivate_and_clear_warm()
    response = _warm_import(admin, force=True)
    assert response.status_code == 200, response.text

    try:
        with SessionLocal() as db:
            active = carbon.active_catalog(db)
            assert active["origin"] == "ingested_external"
            assert active["catalog_version"] == response.json()["stats"]["factor_catalog_version"]

            # synthetic paper_cardboard: baseline 670, recycle -900 =>
            # (670 - (-900)) * 0.5 t = 785 kg for a 500 kg recovery
            row = active["catalog"][("paper_cardboard", "recycle")]
            assert row.value == pytest.approx(-900.0)
            assert row.uncertainty_ratio == pytest.approx(0.3)

            computed = carbon.compute_estimate(
                "paper_cardboard", "recycle", Decimal("500.000"), "kg",
                catalog=active["catalog"],
                factor_source=active["factor_source"],
            )
            assert computed["supported"] is True
            assert computed["avoided_co2e_kg"] == Decimal("785.000")
            assert computed["formula_terms"][0]["source"] == active["factor_source"]

            # metals reuse row had no uncertainty in the file -> documented
            # default applied (never silent)
            metals_row = active["catalog"][("metals", "reuse")]
            assert metals_row.uncertainty_ratio == pytest.approx(0.35)

            # plastics/recycle was quarantined -> honest unsupported estimate
            plastics = carbon.compute_estimate(
                "plastics", "recycle", Decimal("100.000"), "kg",
                catalog=active["catalog"],
            )
            assert plastics["supported"] is False
            assert plastics["avoided_co2e_kg"] is None
    finally:
        _deactivate_and_clear_warm()

    with SessionLocal() as db:
        fallback = carbon.active_catalog(db)
        assert fallback["origin"] == "curated_approximation"
        assert fallback["catalog_version"] == carbon.FACTOR_CATALOG_VERSION
        assert fallback["factor_source"] == carbon.FACTOR_SOURCE


def test_factor_catalog_endpoint_reports_active_origin_and_impact_route_agrees():
    # Precondition: the endpoint reports the curated fallback only when no
    # ingested set is active; dev databases may hold a real-data set, so the
    # test establishes its own precondition explicitly.
    _deactivate_and_clear_warm()
    token = _login("buyer@recircle.local")
    body = client.get("/api/data-ingestion/factor-catalog", headers=_auth(token)).json()
    assert body["origin"] == "curated_approximation"
    assert "must not be presented as EPA-verified" in body["disclaimer"]
    assert body["rows"]
    assert {row["key"] for row in body["sources"]} >= {
        "epa_warm_v15",
        "oecd_mfa",
        "cpcb_india",
    }

    impact_body = client.get("/api/impact/factors", headers=_auth(token)).json()
    assert impact_body["factor_origin"] == "curated_approximation"
    assert impact_body["factor_catalog_version"] == carbon.FACTOR_CATALOG_VERSION
    assert impact_body["limitations"] == carbon.LIMITATIONS
    assert client.get("/api/data-ingestion/factor-catalog").status_code == 401


# ---------------------------------------------------------------- tabular flow


def _flow_csv(version_marker: str) -> bytes:
    """OECD-SDMX-like CSV. SYNTHETIC numbers; value changes between versions."""
    rows = [
        ["jurisdiction", "year", "material_category", "measure", "unit", "value", "notes"],
        ["DE", "2023", "biomass", "domestic_extraction", "thousand_tonnes", "432210.2", f"SYNTHETIC {version_marker}"],
        ["DE", "2023", "metal_ores", "domestic_extraction", "thousand_tonnes", "NA", "SYNTHETIC missing value"],
        ["FR", "2023", "biomass", "domestic_extraction", "thousand_tonnes", "310500.0", "SYNTHETIC"],
        ["FR", "2023", "biomass", "domestic_extraction", "thousand_tonnes", "310500.0", "SYNTHETIC"],
    ]
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("utf-8")


def test_tabular_import_lifecycle_and_missing_value_honesty(tmp_path):
    admin = _admin()
    path = tmp_path / "oecd_mfa_synthetic.csv"
    path.write_bytes(_flow_csv("v1"))

    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "oecd_mfa"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
        headers=_auth(admin),
    )
    assert response.status_code == 200, response.text
    stats = response.json()["stats"]
    assert stats["accepted"] == 3  # DE biomass, DE ores (missing value), FR biomass
    assert stats["unchanged"] == 1  # identical FR duplicate key row
    assert stats["missing_value_rows"] == 1
    assert stats["rejected"] == 0

    with SessionLocal() as db:
        source = db.scalar(select(ExternalDataSource).where(ExternalDataSource.key == "oecd_mfa"))
        records = db.scalars(
            select(ExternalDataRecord).where(ExternalDataRecord.source_id == source.id)
        ).all()
        assert len(records) == 3
        missing = [row for row in records if row.note and "never zero-filled" in row.note]
        assert len(missing) == 1
        assert missing[0].row_data["value"] is None  # NA stays null — never zero
        assert missing[0].row_data["unit"] == "thousand_tonnes"  # units kept explicitly
        for row in records:
            assert row.provenance["file_hash"]
            assert row.provenance["row_schema"] == "material_flow_v1"

    # Rerun of identical file -> skipped, zero changes
    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "oecd_mfa"},
        files={"file": (path.name, _flow_csv("v1"), "text/csv")},
        headers=_auth(admin),
    )
    assert response.json()["status"] == "skipped"

    # Changed value for DE -> supersede lifecycle, history preserved
    path.write_bytes(_flow_csv("v2"))
    response = client.post(
        "/api/data-ingestion/import",
        params={"source_key": "oecd_mfa", "force": "true"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
        headers=_auth(admin),
    )
    assert response.status_code == 200
    stats = response.json()["stats"]
    # 4 parsed rows: DE biomass changed (accepted anew), DE ores + both FR
    # rows unchanged
    assert stats["accepted"] == 1
    assert stats["unchanged"] == 3

    with SessionLocal() as db:
        source = db.scalar(select(ExternalDataSource).where(ExternalDataSource.key == "oecd_mfa"))
        de_rows = db.scalars(
            select(ExternalDataRecord).where(
                ExternalDataRecord.source_id == source.id,
                ExternalDataRecord.natural_key.like("DE|2023|biomass%"),
            )
        ).all()
        statuses = sorted(row.status for row in de_rows)
        assert statuses == ["active", "superseded"]
        active_row = next(row for row in de_rows if row.status == "active")
        superseded = next(row for row in de_rows if row.status == "superseded")
        assert active_row.id != superseded.id
        assert "v2" in (active_row.row_data["notes"] or "")
        assert "v1" in (superseded.row_data["notes"] or "")

    response = client.get(
        "/api/data-ingestion/runs",
        params={"source_key": "oecd_mfa"},
        headers=_auth(admin),
    )
    assert response.status_code == 200
    statuses = {run["status"] for run in response.json()["runs"]}
    assert {"success", "skipped"} <= statuses


def test_records_browsing_is_admin_gated_and_filtered():
    admin = _admin()
    buyer = _login("buyer@recircle.local")
    assert client.get(
        "/api/data-ingestion/records", params={"source_key": "oecd_mfa"}, headers=_auth(buyer)
    ).status_code == 403
    response = client.get(
        "/api/data-ingestion/records",
        params={"source_key": "oecd_mfa", "status": "active"},
        headers=_auth(admin),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert all(record["status"] == "active" for record in body["records"])
    assert all(record["natural_key"] for record in body["records"])


def test_run_detail_returns_validation_report(tmp_path):
    admin = _admin()
    _cleanup()
    created = _warm_import(admin)
    run_id = created.json()["run_id"]
    payload = client.get(
        f"/api/data-ingestion/runs/{run_id}", headers=_auth(admin)
    ).json()
    assert payload["status"] == "success"
    assert payload["params"]["source_key"] == "epa_warm_v15"
    assert len(payload["file_hash"]) == 64
    rejected_reasons = [row["reason"] for row in payload["stats"]["rejected_rows"]]
    assert any("NA/NE/blank" in reason for reason in rejected_reasons)
    assert any("duplicate" in reason for reason in rejected_reasons)
    assert payload["stats"]["quarantine_examples"][0]["reason"].startswith(
        "category has no landfill baseline"
    )

    assert client.get(
        f"/api/data-ingestion/runs/{uuid4()}", headers=_auth(admin)
    ).status_code == 404
    _cleanup()
