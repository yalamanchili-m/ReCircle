"""ERP integration boundary engine (blueprint Phase 16).

Preview/confirm import of validated CSV rows into staged ``erp_records``
(idempotent via external ids, supersede lifecycle on change) and authorized
CSV exports of live platform data. Governance rules enforced here:

- imports never write to live marketplace/trade-chain tables;
- run bookkeeping records every attempt (including failures) with redacted
  errors and no payload contents — only counts, hashes, and reasons;
- repeat imports of identical files are recorded as ``skipped`` unless
  ``force=True`` reprocesses them safely through dedup;
- referenced parent external ids (e.g. transaction rows referencing
  organization rows) must resolve against the same file or previously
  staged active rows; unresolved references are rejected with reasons.

The engine validates entity schemas by construction, rejects unknown file
types, and caps file size/row count per settings.
"""

import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ErpRecord, ErpRun, User
from app.services import audit
from app.services.erp import adapters as adapters_module
from app.services.erp import schemas
from app.services.erp.schemas import ENTITY_SCHEMAS, ENTITY_TYPES

ERP_VERSION = "erp-boundary-v1"

MAX_WARN_INLINE = 50
MAX_REJECT_INLINE = 50
ERROR_SNIPPET_CHARS = 500
ALLOWED_SUFFIXES = {".csv", ".txt"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(error: Exception) -> str:
    text = re.sub(r"\s+", " ", str(error))[:ERROR_SNIPPET_CHARS]
    return text or error.__class__.__name__


def _row_hash(row_data: dict) -> str:
    encoded = json.dumps(row_data, sort_keys=True, default=str).encode("utf-8")
    return _sha256(encoded)


def _load_input_bytes(
    upload_data: bytes | None,
    upload_name: str | None,
    local_path: str | None,
    max_bytes: int,
) -> tuple[bytes, str]:
    if upload_data is not None:
        if not upload_data:
            raise ValueError("uploaded file is empty")
        if len(upload_data) > max_bytes:
            raise ValueError(
                f"file is {len(upload_data)} bytes; import cap is {max_bytes} bytes"
            )
        name = Path(upload_name or "import.csv").name
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"file type '{Path(name).suffix or '<none>'}' not allowed; "
                f"only {', '.join(sorted(ALLOWED_SUFFIXES))} files are accepted"
            )
        return upload_data, name
    if local_path:
        path = Path(local_path)
        if not (path.is_file() and path.exists()):
            raise ValueError(
                f"local_path does not point to a readable file: {local_path!r}"
            )
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"file type '{path.suffix or '<none>'}' not allowed; "
                f"only {', '.join(sorted(ALLOWED_SUFFIXES))} files are accepted"
            )
        size = path.stat().st_size
        if size > max_bytes:
            raise ValueError(f"file is {size} bytes; import cap is {max_bytes} bytes")
        return path.read_bytes(), path.name
    raise ValueError("no file provided (upload a CSV or pass local_path)")


def _read_csv(data: bytes, max_rows: int) -> tuple[list[dict], list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"file must be UTF-8 CSV text ({_safe_error(error)})"
        ) from error
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    if not fieldnames:
        raise ValueError("CSV has no header row")
    rows: list[dict] = []
    for row in reader:
        rows.append(row)
        if len(rows) > max_rows:
            raise ValueError(f"file exceeds the {max_rows}-row import cap")
    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows, fieldnames


def _resolve_adapter(adapter_key: str) -> dict:
    adapter = next(
        (a for a in adapters_module.ERP_ADAPTERS if a["key"] == adapter_key), None
    )
    if adapter is None:
        raise ValueError(f"Unknown ERP adapter '{adapter_key}'")
    if adapter["adapter_status"] != "implemented":
        raise ValueError(
            f"ERP adapter '{adapter_key}' is {adapter['adapter_status']} — "
            "no vendor contract/credentials exist yet, so it cannot be used"
        )
    if adapter["produces_or_consumes"] not in ("both", "produces"):
        raise ValueError(f"ERP adapter '{adapter_key}' cannot import records")
    return adapter


def _record_failed_run(
    db: Session,
    actor: User | None,
    adapter_key: str,
    entity_type: str,
    mode: str,
    params: dict,
    error: Exception,
) -> ErpRun:
    run = ErpRun(
        adapter_key=adapter_key,
        entity_type=entity_type,
        status="failed",
        mode=mode,
        error=_safe_error(error),
        params=params,
        stats={"error": _safe_error(error)},
        triggered_by=actor.id if actor is not None else None,
        started_at=_now(),
        finished_at=_now(),
    )
    db.add(run)
    db.flush()
    return run


def preview_import(
    db: Session,
    actor: User,
    adapter_key: str,
    entity_type: str,
    *,
    upload_data: bytes | None = None,
    upload_name: str | None = None,
    local_path: str | None = None,
) -> dict:
    """Validate a sample and report row outcomes; never stages rows."""
    return _run_import(
        db,
        actor,
        adapter_key,
        entity_type,
        mode="preview",
        upload_data=upload_data,
        upload_name=upload_name,
        local_path=local_path,
        force=False,
    )


def confirm_import(
    db: Session,
    actor: User,
    adapter_key: str,
    entity_type: str,
    *,
    upload_data: bytes | None = None,
    upload_name: str | None = None,
    local_path: str | None = None,
    force: bool = False,
) -> dict:
    """Validate and stage rows idempotently; changed content supersedes."""
    return _run_import(
        db,
        actor,
        adapter_key,
        entity_type,
        mode="confirm",
        upload_data=upload_data,
        upload_name=upload_name,
        local_path=local_path,
        force=force,
    )


def _resolve_references(
    db: Session,
    adapter_key: str,
    entity_type: str,
    accepted_rows: list[dict],
    rejected: list[dict],
) -> list[dict]:
    """Reject rows whose external references are unavailable, keep the rest.

    A referenced key resolves when it (a) appears in this file's accepted
    rows, or (b) exists as a staged active row for the referenced entity
    under the same adapter. Self-references (entity referencing rows of its
    own type, e.g. quantities -> materials staged together) resolve only
    via the same file.
    """
    references = ENTITY_SCHEMAS[entity_type].get("references", {})
    if not references:
        return accepted_rows

    staged_keys: dict[str, set[str]] = {}
    for ref_entity in set(references.values()):
        if ref_entity == entity_type:
            continue
        staged_keys[ref_entity] = set(
            db.scalars(
                select(ErpRecord.external_key).where(
                    ErpRecord.adapter_key == adapter_key,
                    ErpRecord.entity_type == ref_entity,
                    ErpRecord.status == "active",
                )
            ).all()
        )

    file_keys: dict[str, set[str]] = {
        ref_entity: {row["external_id"] for row in accepted_rows}
        for ref_entity in set(references.values())
    }

    keep: list[dict] = []
    for row_index, row in enumerate(accepted_rows):
        for ref_field, ref_entity in references.items():
            value = row[ref_field]
            if value in file_keys.get(ref_entity, set()) or value in staged_keys.get(
                ref_entity, set()
            ):
                continue
            rejected.append(
                {
                    "row_index": row_index + 2,
                    "reason": (
                        f"row {row_index + 2}: '{ref_field}'='{value}' does not "
                        f"reference any known '{ref_entity}' record (resolved "
                        "from the same file or prior staged imports for "
                        f"adapter '{adapter_key}')"
                    ),
                }
            )
            break
        else:
            keep.append(row)
    return keep


def _run_import(
    db: Session,
    actor: User,
    adapter_key: str,
    entity_type: str,
    *,
    mode: str,
    upload_data: bytes | None,
    upload_name: str | None,
    local_path: str | None,
    force: bool,
) -> dict:
    from app.core.config import get_settings

    settings = get_settings()
    started_at = time.perf_counter()
    run_started = _now()
    params = {
        "adapter_key": adapter_key,
        "entity_type": entity_type,
        "force": bool(force),
        "origin": "upload" if upload_data is not None else "local_path",
    }
    try:
        adapter = _resolve_adapter(adapter_key)
        if entity_type not in ENTITY_SCHEMAS:
            raise ValueError(
                f"unknown entity_type '{entity_type}' (supported: "
                f"{', '.join(ENTITY_TYPES)})"
            )
        max_bytes = settings.erp_max_file_mb * 1024 * 1024
        data, filename = _load_input_bytes(
            upload_data, upload_name, local_path, max_bytes
        )
        file_hash = _sha256(data)

        if mode == "confirm":
            last_success = db.scalar(
                select(ErpRun)
                .where(
                    ErpRun.adapter_key == adapter_key,
                    ErpRun.entity_type == entity_type,
                    ErpRun.mode == "confirm",
                    ErpRun.status == "success",
                    ErpRun.file_hash == file_hash,
                )
                .order_by(ErpRun.started_at.desc())
            )
            if last_success is not None and not force:
                run = ErpRun(
                    adapter_key=adapter_key,
                    entity_type=entity_type,
                    status="skipped",
                    mode="confirm",
                    params=params,
                    stats={
                        "reason": (
                            f"identical file (sha256 {file_hash[:16]}...) "
                            "already confirmed for this adapter/entity; "
                            "repeat imports are safe"
                        ),
                        "previous_run_id": str(last_success.id),
                    },
                    file_hash=file_hash,
                    triggered_by=actor.id,
                    started_at=run_started,
                    finished_at=_now(),
                )
                db.add(run)
                db.flush()
                return {"run_id": str(run.id), "status": "skipped", "stats": run.stats}

        rows, fieldnames = _read_csv(data, settings.erp_max_rows)
        validated = schemas.validate_rows(entity_type, rows, fieldnames)
        rejected: list[dict] = list(validated["rejected"])
        warnings: list[str] = []
        if validated["unknown_columns"]:
            warnings.append(
                "unrecognized column(s) ignored: "
                + ", ".join(sorted(validated["unknown_columns"])[:10])
            )

        rows_to_stage = _resolve_references(
            db, adapter_key, entity_type, validated["accepted"], rejected
        )

        stats: dict = {
            "erp_version": ERP_VERSION,
            "adapter": adapter["key"],
            "adapter_status": adapter["adapter_status"],
            "rows_total": len(rows),
            "file_name": filename,
            "file_hash": file_hash,
            "accepted": len(rows_to_stage),
            "updated": 0,
            "unchanged": 0,
            "rejected": len(rejected),
            "warnings": warnings[:MAX_WARN_INLINE],
            "warnings_total": len(warnings),
            "rejected_rows": rejected[:MAX_REJECT_INLINE],
        }
        if len(rejected) > MAX_REJECT_INLINE:
            stats["rejected_rows_truncated"] = True
        if len(warnings) > MAX_WARN_INLINE:
            stats["warnings_truncated"] = True

        if mode == "preview":
            stats["note"] = (
                "Preview only: no rows were staged; confirm this import to persist."
            )
            run = ErpRun(
                adapter_key=adapter_key,
                entity_type=entity_type,
                status="previewed",
                mode="preview",
                params=params,
                stats=stats,
                file_hash=file_hash,
                runtime_ms=int((time.perf_counter() - started_at) * 1000),
                triggered_by=actor.id,
                started_at=run_started,
                finished_at=_now(),
            )
            db.add(run)
            db.flush()
            return {"run_id": str(run.id), "status": "previewed", "stats": stats}

        run = ErpRun(
            adapter_key=adapter_key,
            entity_type=entity_type,
            status="success",
            mode="confirm",
            params=params,
            file_hash=file_hash,
            triggered_by=actor.id,
            started_at=run_started,
        )
        db.add(run)
        db.flush()

        accepted, updated, unchanged = _persist_rows(
            db,
            adapter_key,
            entity_type,
            rows_to_stage,
            run_id=run.id,
            file_hash=file_hash,
        )
        stats.update(
            {
                "accepted": accepted,
                "updated": updated,
                "unchanged": unchanged,
            }
        )
        run.stats = {key: value for key, value in stats.items() if value is not None}
        run.runtime_ms = int((time.perf_counter() - started_at) * 1000)
        run.finished_at = _now()
        db.flush()
        audit.record_audit(
            db,
            actor=actor,
            action="erp.import_confirm",
            entity_type="erp_import",
            details={
                "adapter_key": adapter_key,
                "entity_type": entity_type,
                "run_id": str(run.id),
                "totals": {
                    key: stats.get(key)
                    for key in ("accepted", "updated", "unchanged", "rejected")
                },
            },
        )
        return {"run_id": str(run.id), "status": "success", "stats": stats}
    except (ValueError, OSError) as error:
        _record_failed_run(db, actor, adapter_key, entity_type, mode, params, error)
        raise ValueError(_safe_error(error)) from error


def _persist_rows(
    db: Session,
    adapter_key: str,
    entity_type: str,
    rows_to_stage: list[dict],
    *,
    run_id,
    file_hash: str,
) -> tuple[int, int, int]:
    """Idempotent upsert with supersede lifecycle and chunked reads.

    Every stored row object is db.add()-tracked; the object list is only a
    grouping device for the same-file supersede pass below.
    """
    accepted = updated = unchanged = 0
    keys = [row["external_id"] for row in rows_to_stage]
    found: dict[str, list[ErpRecord]] = {}
    for chunk_start in range(0, len(keys), 500):
        chunk = keys[chunk_start : chunk_start + 500]
        for record in db.scalars(
            select(ErpRecord).where(
                ErpRecord.adapter_key == adapter_key,
                ErpRecord.entity_type == entity_type,
                ErpRecord.external_key.in_(chunk),
            )
        ).all():
            found.setdefault(record.external_key, []).append(record)

    inserts: list[ErpRecord] = []

    def insert_row(key: str, content_hash: str, row: dict) -> None:
        record = ErpRecord(
            adapter_key=adapter_key,
            entity_type=entity_type,
            external_key=key,
            content_hash=content_hash,
            status="active",
            row_data=row,
            provenance={
                "file_hash": file_hash,
                "adapter_key": adapter_key,
                "entity_type": entity_type,
                "row_schema": f"erp_{entity_type}_v1",
            },
            run_id=run_id,
        )
        inserts.append(record)
        db.add(record)

    for row in rows_to_stage:
        key = row["external_id"]
        content_hash = _row_hash(row)
        existing = found.get(key, [])
        if existing:
            same_active = next(
                (
                    r
                    for r in existing
                    if r.status == "active" and r.content_hash == content_hash
                ),
                None,
            )
            if same_active is not None:
                unchanged += 1
                continue
            reactivate = next(
                (r for r in existing if r.content_hash == content_hash), None
            )
            if reactivate is not None:
                reactivate.status = "active"
                reactivate.run_id = run_id
                updated += 1
                continue
            for r in existing:
                if r.status == "active":
                    r.status = "superseded"
        insert_row(key, content_hash, row)
        accepted += 1

    if inserts:
        db.flush()
    return accepted, updated, unchanged


def run_payload(run: ErpRun) -> dict:
    return {
        "id": str(run.id),
        "adapter_key": run.adapter_key,
        "entity_type": run.entity_type,
        "status": run.status,
        "mode": run.mode,
        "error": run.error,
        "params": run.params,
        "stats": run.stats,
        "file_hash": run.file_hash,
        "runtime_ms": run.runtime_ms,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
    }
