"""External data ingestion API (blueprint Phase 15).

The source registry and the (approximation-vs-ingested) factor catalog
provenance are member-visible; staged imports, run history, and normalized
record browsing are admin-gated and audited. Import failures surface as 422
responses after the failed run record is committed, so every attempt stays
in the audit trail.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import ExternalDataRecord, ExternalDataSource, User
from app.models.data_ingestion import IngestionRun
from app.services import audit, carbon
from app.services.data_ingestion import ingest, sources

router = APIRouter()


@router.get("/data-ingestion/sources")
def data_ingestion_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Curated source registry with runtime state (Phase 15)."""
    payload = sources.sources_payload(db)
    db.commit()
    return payload


@router.post("/data-ingestion/import")
def data_ingestion_import(
    source_key: str = Query(min_length=1, max_length=60),
    declared_version: str | None = Query(default=None, max_length=255),
    local_path: str | None = Query(default=None, max_length=400),
    force: bool = Query(default=False),
    file: UploadFile | None = File(default=None),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Manual staged-file import (admin, audited).

    Provide ``file`` (multipart CSV upload) or ``local_path`` (a file already
    on the server). Provide neither and the request is refused after a failed
    run record is written.
    """
    upload_data: bytes | None = None
    upload_name: str | None = None
    if file is not None:
        upload_data = file.file.read()
        upload_name = file.filename
        if not upload_data:
            db.commit()
            audit.record_audit(
                db,
                actor=current_user,
                action="data_ingestion.import",
                entity_type="external_data_source",
                details={"source_key": source_key, "status": "refused_empty_upload"},
            )
            db.commit()
            raise HTTPException(status_code=422, detail="uploaded file is empty")

    try:
        payload = ingest.import_staged_file(
            db,
            current_user,
            source_key,
            upload_data=upload_data,
            upload_name=upload_name,
            local_path=local_path,
            declared_version=declared_version,
            force=force,
        )
    except ValueError as error:
        db.commit()  # keep the failed run record for auditing
        raise HTTPException(status_code=422, detail=str(error))

    ingest.audit_import(db, current_user, payload, source_key)
    db.commit()
    return payload


@router.get("/data-ingestion/runs")
def data_ingestion_runs(
    source_key: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Recent import-run history (admin), including failed/skipped attempts."""
    conditions = []
    if source_key:
        conditions.append(IngestionRun.source_key == source_key)
    total = db.scalar(
        select(func.count()).select_from(IngestionRun).where(*conditions)
    ) or 0
    rows = db.scalars(
        select(IngestionRun)
        .where(*conditions)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id)
        .limit(limit)
    ).all()
    db.commit()
    return {
        "total": int(total),
        "limit": limit,
        "runs": [ingest.run_payload(run) for run in rows],
    }


@router.get("/data-ingestion/runs/{run_id}")
def data_ingestion_run_detail(
    run_id: uuid.UUID,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Full validation report for one import run (admin)."""
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Import run not found")
    payload = ingest.run_payload(run)
    db.commit()
    return payload


@router.get("/data-ingestion/records")
def data_ingestion_records(
    source_key: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, pattern="^(active|superseded|quarantined)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Normalized records with lifecycle states (admin browsing/audit)."""
    conditions = []
    if source_key:
        conditions.append(ExternalDataSource.key == source_key)
    if status:
        conditions.append(ExternalDataRecord.status == status)

    total = (
        db.scalar(
            select(func.count())
            .select_from(ExternalDataRecord)
            .join(ExternalDataSource, ExternalDataRecord.source_id == ExternalDataSource.id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(ExternalDataRecord, ExternalDataSource.key)
        .join(ExternalDataSource, ExternalDataRecord.source_id == ExternalDataSource.id)
        .where(*conditions)
        .order_by(ExternalDataRecord.natural_key, ExternalDataRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    db.commit()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "records": [
            {
                "id": str(record.id),
                "source_key": key,
                "natural_key": record.natural_key,
                "content_hash": record.content_hash,
                "status": record.status,
                "row_data": record.row_data,
                "provenance": record.provenance,
                "note": record.note,
                "run_id": str(record.run_id) if record.run_id else None,
                "created_at": record.created_at.isoformat(),
            }
            for record, key in rows
        ],
    }


@router.get("/data-ingestion/factor-catalog")
def data_ingestion_factor_catalog(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Active factor set provenance: ingested set or curated approximation.

    This is the single place to see whether carbon estimates currently run
    on the curated approximation fallback or on a validated, externally
    ingested factor set (Phase 15).
    """
    cur = carbon.active_catalog(db)
    rows = sorted(cur["catalog"].values(), key=lambda r: (r.category, r.pathway))
    source_rows = db.scalars(select(ExternalDataSource).order_by(ExternalDataSource.key)).all()
    db.commit()
    return {
        "origin": cur["origin"],
        "factor_catalog_version": cur["catalog_version"],
        "factor_source": cur["factor_source"],
        "baseline_reference": cur["baseline_reference"],
        "factor_unit": carbon.FACTOR_UNIT,
        "ingestion_version": ingest.INGESTION_VERSION,
        "disclaimer": (
            "Ingested external factor set is active; every value traces to an "
            "ingestion run (see /data-ingestion/runs)."
            if cur["origin"] == "ingested_external"
            else "Curated platform approximation values pending EPA WARM v15 "
            "ingestion (Phase 15); they must not be presented as EPA-verified "
            "numbers."
        ),
        "rows": [
            {
                "category": row.category,
                "pathway": row.pathway,
                "value": row.value,
                "uncertainty_ratio": row.uncertainty_ratio,
                "note": row.note,
                "is_baseline": row.pathway == carbon.BASELINE_PATHWAY,
            }
            for row in rows
        ],
        "sources": [
            {
                "key": row.key,
                "name": row.name,
                "enabled": row.enabled,
                "adapter_status": row.adapter_status,
                "declared_version": row.declared_version,
                "latest_run_at": row.latest_run_at.isoformat() if row.latest_run_at else None,
            }
            for row in source_rows
        ],
    }
