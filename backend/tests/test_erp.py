"""ERP integration boundary tests (blueprint Phase 16).

Covers: adapter registry curation (implemented CSV adapter + honest
``planned`` vendor connectors), the six entity schemas, preview/confirm
semantics, idempotency (identical rerun skipped, content change superseded
with history preserved), row validation incl. referential gating against
same-file/parent entities, run bookkeeping (failures recorded, errors
redacted), role gating, and authorized audited exports.
"""

import csv
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditLog, ErpRecord, ErpRun
from app.services.erp import adapters as erp_adapters
from app.services.erp import schemas as erp_schemas

client = TestClient(app)

MATERIALS_CSV_V1 = (
    "external_id,title,category,typical_unit,grade,notes\n"
    "ERP-M-001,Scrap copper ore,metals,tonne,M1,SYNTHETIC ERP demo row\n"
    "ERP-M-002,Corrugated trimmings,paper_cardboard,kg,,SYNTHETIC ERP demo row\n"
    "ERP-M-003,LDPE film scrap,plastics,kg,,SYNTHETIC ERP demo row\n"
)
MATERIALS_CSV_V2 = (
    "external_id,title,category,typical_unit,grade,notes\n"
    "ERP-M-001,Scrap copper ore (revised),metals,tonne,M1,SYNTHETIC ERP demo row v2\n"
    "ERP-M-002,Corrugated trimmings,paper_cardboard,kg,,SYNTHETIC ERP demo row\n"
    "ERP-M-003,LDPE film scrap,plastics,kg,,SYNTHETIC ERP demo row\n"
)
ORGS_CSV = (
    "external_id,name,org_type,region,country,industry\n"
    "ERP-O-001,Buyer Corp SYNS,buyer,Maharashtra,India,manufacturing\n"
    "ERP-O-002,Generator Corp SYNS,generator,Delhi,India,recycling\n"
)
MATERIALS_BAD_CSV = (
    "external_id,title,category,typical_unit,grade,notes\n"
    "ERP-M-010,Bad category,folio,kg,,SYNTHETIC\n"
    "ERP-M-011,Missing unit row,paper_cardboard,,,SYNTHETIC\n"
    "ERP-M-012,%s,metals,tonne,,SYNTHETIC\n" % ("x" * 300)
)
TX_CSV = (
    "external_id,buyer_external_id,seller_external_id,material_external_id,"
    "quantity,unit,value,currency,occurred_on,status_external\n"
    "ERP-T-901,ERP-O-001,ERP-O-002,ERP-M-002,120,kg,44.5,INR,2026-01-15,posted\n"
    "ERP-T-902,ERP-O-404,ERP-O-002,ERP-M-001,2,tonne,,INR,2026-01-20,\n"
)
TX_BAD_CSV = (
    "external_id,buyer_external_id,seller_external_id,material_external_id,"
    "quantity,unit,value,currency,occurred_on,status_external\n"
    "ERP-T-900,ERP-O-404,ERP-O-404,ERP-M-404,120,kg,44.5,INR,2026-01-15,posted\n"
)


@pytest.fixture(scope="module", autouse=True)
def _dataset():
    seed()
    yield
    _cleanup()


def _cleanup() -> None:
    with SessionLocal() as db:
        db.execute(delete(ErpRecord))
        db.execute(delete(ErpRun))
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


def _preview(adapter_key: str, entity_type: str, payload: bytes, name="sample.csv", **params):
    token = params.pop("token")
    return client.post(
        "/api/erp/import/preview",
        params={"adapter_key": adapter_key, "entity_type": entity_type, **params},
        files={"file": (name, payload, "text/csv")},
        headers=_auth(token),
    )


def _confirm(token, entity_type: str, payload: bytes, name="sample.csv", **params):
    return client.post(
        "/api/erp/import/confirm",
        params={"adapter_key": "csv_generic", "entity_type": entity_type, **params},
        files={"file": (name, payload, "text/csv")},
        headers=_auth(token),
    )


# --------------------------------------------------------- registry + gating


def test_registry_curates_adapters_and_entity_schemas():
    report = erp_adapters.ensure_registry_consistent()
    assert report["registry_version"] == "erp-adapter-registry-v1"
    implemented = [a for a in erp_adapters.ERP_ADAPTERS if a["adapter_status"] == "implemented"]
    planned = [a for a in erp_adapters.ERP_ADAPTERS if a["adapter_status"] == "planned"]
    assert [a["key"] for a in implemented] == ["csv_generic"]
    assert len(planned) >= 1
    for entry in planned:
        assert entry["credential_env_vars"], "vendor adapter must name its credential config"
        for env_name in entry["credential_env_vars"]:
            assert env_name.startswith("ERP_")
    tokens = " ".join(
        (entry.get("notes", "") + entry.get("description", "")).lower()
        for entry in erp_adapters.ERP_ADAPTERS
    )
    assert "http" not in tokens
    assert "not implemented" in tokens

    assert set(erp_schemas.ENTITY_TYPES) == {
        "organizations",
        "materials",
        "quantities",
        "locations",
        "transactions",
        "recovery_records",
    }
    for entity_key, schema in erp_schemas.ENTITY_SCHEMAS.items():
        names = [field.name for field in schema["fields"]]
        assert names[0] == "external_id", entity_key
        assert schema["maps_to"]


def test_import_and_runs_are_admin_gated():
    buyer = _login("buyer@recircle.local")
    assert client.post(
        "/api/erp/import/preview",
        params={"adapter_key": "csv_generic", "entity_type": "materials"},
        files={"file": ("m.csv", MATERIALS_CSV_V1.encode())},
        headers=_auth(buyer),
    ).status_code == 403
    assert client.post(
        "/api/erp/import/confirm",
        params={"adapter_key": "csv_generic", "entity_type": "materials"},
        files={"file": ("m.csv", MATERIALS_CSV_V1.encode())},
        headers=_auth(buyer),
    ).status_code == 403
    assert client.get("/api/erp/runs", headers=_auth(buyer)).status_code == 403
    assert client.get("/api/erp/export/materials", headers=_auth(buyer)).status_code == 403
    generator = _login("generator@recircle.local")
    assert client.get("/api/erp/adapters", headers=_auth(generator)).status_code == 200
    assert client.get("/api/erp/runs", headers=_auth(generator)).status_code == 403


def test_adapters_endpoint_reports_registry_and_entities():
    token = _admin()
    response = client.get("/api/erp/adapters", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["registry_version"] == "erp-adapter-registry-v1"
    entity_keys = [entity["entity_type"] for entity in body["entities"]]
    assert entity_keys == list(erp_schemas.ENTITY_TYPES)
    planned = [a for a in body["adapters"] if a["adapter_status"] == "planned"]
    assert planned
    for adapter in planned:
        assert adapter["run_counts"] == {}


# ------------------------------------------------------------------ preview


def test_preview_reports_row_outcomes_without_staging():
    token = _admin()
    before = client.get("/api/erp/runs", headers=_auth(token)).json()["total"]
    response = _preview("csv_generic", "materials", MATERIALS_CSV_V1.encode(), "materials_v1.csv", token=token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "previewed"
    stats = body["stats"]
    assert stats["accepted"] == 3
    assert stats["rejected"] == 0
    assert "confirm this import to persist" in stats["note"]
    after = client.get("/api/erp/runs", headers=_auth(token)).json()["total"]
    assert after == before + 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ErpRecord)) == 0
        run = db.get(ErpRun, uuid.UUID(body["run_id"]))
        assert run is not None
        assert run.mode == "preview"
        assert run.stats["accepted"] == 3


def test_preview_validates_and_reports_rejected_rows():
    token = _admin()
    response = _preview("csv_generic", "materials", MATERIALS_BAD_CSV.encode(), "bad.csv", token=token)
    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["accepted"] == 1  # missing optional columns is not a rejection
    assert stats["rejected"] == 2
    reasons = [row["reason"] for row in stats["rejected_rows"]]
    assert any("not one of" in reason for reason in reasons)
    assert any("longer than" in reason for reason in reasons)


def test_failures_are_recorded_without_payload_leaks():
    token = _admin()
    response = _preview("csv_generic", "not_an_entity", MATERIALS_CSV_V1.encode(), token=token)
    assert response.status_code == 422
    assert "unknown entity_type" in response.json()["detail"]
    bad_utf8 = b"\xff\xfe\x00\x81 binary junk"
    response = _preview("csv_generic", "materials", bad_utf8, "weird.csv", token=token)
    assert response.status_code == 422
    assert "utf-8" in response.json()["detail"].lower()
    wrong_type = client.post(
        "/api/erp/import/preview",
        params={"adapter_key": "csv_generic", "entity_type": "materials"},
        files={"file": ("file.exe", b"MZ", "application/octet-stream")},
        headers=_auth(token),
    )
    assert wrong_type.status_code == 422
    assert "not allowed" in wrong_type.json()["detail"]
    runs = client.get("/api/erp/runs", headers=_auth(token)).json()["runs"]
    failed = [run for run in runs if run["status"] == "failed"]
    assert failed, "every attempt must be recorded"
    assert all(run["error"] for run in failed)
    joined = " ".join(json.dumps(run["stats"]) for run in failed)
    assert "ERP-" not in joined, "no row data may leak into run bookkeeping"


# ------------------------------------------------------------------ confirm


def test_confirm_stages_rows_and_reruns_are_skipped():
    token = _admin()
    with SessionLocal() as db:
        db.execute(delete(ErpRecord))
        db.execute(delete(ErpRun))
        db.commit()
    first = _confirm(token, "materials", MATERIALS_CSV_V1.encode(), "materials_v1.csv")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "success"
    assert body["stats"]["accepted"] == 3
    assert body["stats"]["unchanged"] == 0
    with SessionLocal() as db:
        rows = db.scalars(
            select(ErpRecord).where(ErpRecord.entity_type == "materials")
        ).all()
        assert len(rows) == 3
        assert {row.external_key for row in rows} == {"ERP-M-001", "ERP-M-002", "ERP-M-003"}
        assert all(row.status == "active" for row in rows)
        assert all(row.run_id for row in rows)

    rerun = _confirm(token, "materials", MATERIALS_CSV_V1.encode(), "materials_v1.csv")
    assert rerun.status_code == 200
    rerun_body = rerun.json()
    assert rerun_body["status"] == "skipped"
    assert "already confirmed" in rerun_body["stats"]["reason"]

    forced = _confirm(
        token, "materials", MATERIALS_CSV_V1.encode(), "materials_v1.csv", force="true"
    )
    assert forced.status_code == 200
    body = forced.json()
    assert body["status"] == "success"
    assert body["stats"]["accepted"] == 0
    assert body["stats"]["unchanged"] == 3
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(ErpRecord).where(
                ErpRecord.entity_type == "materials", ErpRecord.status == "active"
            )
        ) == 3


def test_changed_content_supersedes_with_history():
    token = _admin()
    _confirm(token, "materials", MATERIALS_CSV_V1.encode())  # no-op skip if present
    changed = _confirm(
        token, "materials", MATERIALS_CSV_V2.encode(), "materials_v2.csv", force="true"
    )
    assert changed.status_code == 200
    stats = changed.json()["stats"]
    assert stats["accepted"] == 1
    assert stats["unchanged"] == 2
    with SessionLocal() as db:
        m001 = db.scalars(
            select(ErpRecord)
            .where(
                ErpRecord.entity_type == "materials",
                ErpRecord.external_key == "ERP-M-001",
            )
            .order_by(ErpRecord.created_at)
        ).all()
        assert {row.status for row in m001} == {"active", "superseded"}
        active = next(row for row in m001 if row.status == "active")
        superseded = next(row for row in m001 if row.status == "superseded")
        assert active.id != superseded.id
        assert "v2" in active.row_data["notes"]
        assert "v1" not in superseded.row_data["notes"]
        active_rows = db.scalars(
            select(ErpRecord).where(
                ErpRecord.entity_type == "materials", ErpRecord.status == "active"
            )
        ).all()
        assert len(active_rows) == 3


# ----------------------------------------------------- referential integrity


def test_transaction_references_reject_then_resolve_with_staged_parents():
    token = _admin()
    with SessionLocal() as db:
        db.execute(delete(ErpRecord))
        db.execute(delete(ErpRun))
        db.commit()

    preview_bad = _preview("csv_generic", "transactions", TX_BAD_CSV.encode(), token=token)
    assert preview_bad.status_code == 200
    stats = preview_bad.json()["stats"]
    assert stats["accepted"] == 0
    assert stats["rejected"] == 1
    reason = stats["rejected_rows"][0]["reason"]
    assert "does not reference" in reason

    confirmed_orgs = _confirm(token, "organizations", ORGS_CSV.encode())
    assert confirmed_orgs.status_code == 200, confirmed_orgs.text
    assert confirmed_orgs.json()["stats"]["accepted"] == 2
    confirmed_materials = _confirm(token, "materials", MATERIALS_CSV_V1.encode())
    assert confirmed_materials.status_code == 200

    tx = _preview("csv_generic", "transactions", TX_CSV.encode(), token=token)
    assert tx.status_code == 200
    tx_stats = tx.json()["stats"]
    assert tx_stats["accepted"] == 1, "staged buyer resolves, unknown is rejected"
    assert tx_stats["rejected"] == 1
    assert "ERP-O-404" in tx_stats["rejected_rows"][0]["reason"]

    staged = _confirm(token, "transactions", TX_CSV.encode())
    assert staged.status_code == 200, staged.text
    with SessionLocal() as db:
        tx_rows = db.scalars(
            select(ErpRecord).where(
                ErpRecord.entity_type == "transactions", ErpRecord.status == "active"
            )
        ).all()
        assert len(tx_rows) == 1
        row = tx_rows[0]
        assert row.external_key == "ERP-T-901"
        assert row.row_data["value"] == 44.5
        assert row.provenance["row_schema"] == "erp_transactions_v1"


# ------------------------------------------------------------------- export


def test_export_is_authorized_audited_and_covers_entities():
    token = _admin()
    response = client.get("/api/erp/export/materials", headers=_auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "recircle_materials_export.csv" in response.headers["content-disposition"]
    reader = csv.DictReader(io.StringIO(response.text))
    assert "seller_organization" in reader.fieldnames
    assert "title" in reader.fieldnames

    recovery = client.get("/api/erp/export/recovery_records", headers=_auth(token))
    assert recovery.status_code == 200
    rec_reader = csv.DictReader(io.StringIO(recovery.text))
    assert "factor_catalog_version" in rec_reader.fieldnames
    assert "verification_status" in rec_reader.fieldnames

    unknown = client.get("/api/erp/export/not_an_entity", headers=_auth(token))
    assert unknown.status_code == 422

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "erp.export")
            .order_by(AuditLog.created_at.desc())
        ).all()
        kinds = {event.details.get("entity_type") for event in events}
        assert "materials" in kinds and "recovery_records" in kinds


def test_runs_listing_and_payload_bounds():
    token = _admin()
    response = client.get("/api/erp/runs", params={"limit": 5}, headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["total"] >= len(body["runs"])
    for run in body["runs"]:
        assert run["status"] in ("previewed", "success", "failed", "skipped")
        assert run["mode"] in ("preview", "confirm")
        assert run["entity_type"] in erp_schemas.ENTITY_TYPES

    detail = client.get(
        f"/api/erp/runs/{body['runs'][0]['id']}", headers=_auth(token)
    )
    assert detail.status_code == 200
    missing = client.get("/api/erp/runs/" + str(uuid.uuid4()), headers=_auth(token))
    assert missing.status_code == 404
    invalid = client.get("/api/erp/runs/not-a-uuid", headers=_auth(token))
    assert invalid.status_code == 422
