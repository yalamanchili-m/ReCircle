"""ERP integration boundary API (blueprint Phase 16).

The adapter registry and entity schemas are member-visible; imports
(preview/confirm), run history, and exports are admin-gated and audited.
Import failures surface as 422 responses after the failed run row is
committed, so every attempt stays in the audit trail. No endpoint claims
live ERP integration: vendor adapters are listed as ``planned`` until a
vendor contract, credentials, and an integration test exist.
"""

import csv
import io
import uuid as uuid_module

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import ErpRun, User
from app.services import audit
from app.services.erp import adapters as adapters_service
from app.services.erp import engine, exports
from app.services.erp.schemas import ERP_BOUNDARY_VERSION

router = APIRouter()


@router.get("/erp/adapters")
def erp_adapters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """ERP adapter registry + entity schemas (Phase 16)."""
    payload = adapters_service.adapters_payload(db)
    payload["boundary_version"] = ERP_BOUNDARY_VERSION
    payload["export_entities"] = sorted(exports.EXPORT_ENTITIES)
    db.commit()
    return payload


@router.post("/erp/import/preview")
def erp_import_preview(
    adapter_key: str = Query(min_length=1, max_length=60),
    entity_type: str = Query(min_length=1, max_length=60),
    local_path: str | None = Query(default=None, max_length=400),
    file: UploadFile | None = File(default=None),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Validate a sample CSV and report row outcomes; stages nothing."""
    upload_data, upload_name = _read_upload(file, db, current_user, adapter_key, entity_type)
    try:
        payload = engine.preview_import(
            db,
            current_user,
            adapter_key,
            entity_type,
            upload_data=upload_data,
            upload_name=upload_name,
            local_path=local_path,
        )
    except ValueError as error:
        db.commit()
        raise HTTPException(status_code=422, detail=str(error))
    audit.record_audit(
        db,
        actor=current_user,
        action="erp.import_preview",
        entity_type="erp_import",
        details={
            "adapter_key": adapter_key,
            "entity_type": entity_type,
            "run_id": payload["run_id"],
            "totals": {
                key: payload["stats"].get(key)
                for key in ("accepted", "rejected")
            },
        },
    )
    db.commit()
    return payload


@router.post("/erp/import/confirm")
def erp_import_confirm(
    adapter_key: str = Query(min_length=1, max_length=60),
    entity_type: str = Query(min_length=1, max_length=60),
    local_path: str | None = Query(default=None, max_length=400),
    force: bool = Query(default=False),
    file: UploadFile | None = File(default=None),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Validate and stage a CSV idempotently (admin, audited)."""
    upload_data, upload_name = _read_upload(file, db, current_user, adapter_key, entity_type, confirmed=True)
    try:
        payload = engine.confirm_import(
            db,
            current_user,
            adapter_key,
            entity_type,
            upload_data=upload_data,
            upload_name=upload_name,
            local_path=local_path,
            force=force,
        )
    except ValueError as error:
        db.commit()
        raise HTTPException(status_code=422, detail=str(error))
    if payload["status"] != "skipped":
        # confirm success already wrote its own audit inside the engine
        db.commit()
    else:
        audit.record_audit(
            db,
            actor=current_user,
            action="erp.import_confirm",
            entity_type="erp_import",
            details={
                "adapter_key": adapter_key,
                "entity_type": entity_type,
                "run_id": payload["run_id"],
                "status": "skipped",
            },
        )
        db.commit()
    return payload


def _read_upload(
    file: UploadFile | None,
    db: Session,
    actor: User,
    adapter_key: str,
    entity_type: str,
    confirmed: bool = False,
) -> tuple[bytes | None, str | None]:
    if file is None:
        return None, None
    data = file.file.read()
    if not data:
        action = "erp.import_confirm" if confirmed else "erp.import_preview"
        audit.record_audit(
            db,
            actor=actor,
            action=action,
            entity_type="erp_import",
            details={"adapter_key": adapter_key, "entity_type": entity_type, "status": "refused_empty_upload"},
        )
        db.commit()
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    return data, file.filename


@router.get("/erp/runs")
def erp_runs(
    adapter_key: str | None = Query(default=None, max_length=60),
    entity_type: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """ERP import-run history including failed/skipped/preview attempts."""
    conditions = []
    if adapter_key:
        conditions.append(ErpRun.adapter_key == adapter_key)
    if entity_type:
        conditions.append(ErpRun.entity_type == entity_type)
    total = db.scalar(
        select(func.count()).select_from(ErpRun).where(*conditions)
    ) or 0
    rows = db.scalars(
        select(ErpRun)
        .where(*conditions)
        .order_by(desc(ErpRun.started_at), ErpRun.id)
        .limit(limit)
    ).all()
    db.commit()
    return {
        "total": int(total),
        "limit": limit,
        "runs": [engine.run_payload(run) for run in rows],
    }


@router.get("/erp/runs/{run_id}")
def erp_run_detail(
    run_id: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Full validation report for one ERP import attempt (admin)."""
    try:
        run_uuid = uuid_module.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid run id")
    run = db.get(ErpRun, run_uuid)
    if run is None:
        raise HTTPException(status_code=404, detail="ERP run not found")
    payload = engine.run_payload(run)
    db.commit()
    return payload


@router.get("/erp/export/{entity_type}")
def erp_export(
    entity_type: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> Response:
    """Authorized CSV export of live platform data for one entity (audited)."""
    from app.core.config import get_settings

    try:
        result = exports.export_entity(
            db, entity_type, get_settings().erp_export_max_rows
        )
    except ValueError as error:
        db.commit()
        raise HTTPException(status_code=422, detail=str(error))
    audit.record_audit(
        db,
        actor=current_user,
        action="erp.export",
        entity_type="erp_export",
        details={
            "entity_type": entity_type,
            "row_count": result["row_count"],
            "truncated": result["truncated"],
        },
    )
    db.commit()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=result["columns"], extrasaction="ignore")
    writer.writeheader()
    for row in result["rows"]:
        writer.writerow(row)
    filename = f"recircle_{entity_type}_export.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
