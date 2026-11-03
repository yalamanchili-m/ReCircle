"""External-data staged-file import engine (blueprint Phase 15).

Documented import schemas
-------------------------
``warm_factor_csv`` (source ``epa_warm_v15``)::

    material_category,management_pathway,quantity_kg_co2e_per_tonne[,uncertainty_ratio][,note]

* category/pathway are lowercase slugs; pathway must be one of the platform
  recovery pathways (``reuse/recycle/compost/energy_recovery/landfill``).
* Every category carrying recovery routes must also carry a landfill
  baseline (route rows without one are quarantined with an explicit reason).
* Missing-value tokens (``NA``, ``NE``, blank) are REJECTED with explicit
  reasons: a factor value can never default to zero.
* On success the validated rows replace the active ingested factor set
  (previous versions stay persisted as history) so carbon estimates
  consume them through ``app.services.carbon.active_catalog``.

``tabular_csv`` (material-flow sources such as ``oecd_mfa``)::

    jurisdiction,year,material_category,measure,unit,value[,notes]

* Missing-value tokens normalize to JSON null plus a quarantine-style
  note: rows are retained with a warning and are never zero-filled.
* Rows deduplicate on the natural key
  ``(jurisdiction, year, material_category, measure, unit)``; a changed
  value supersedes the previous row (history preserved, no overwrites).

Safety/properties
-----------------
* Files are hashed (SHA-256) and stored verbatim under
  ``data/external/staged/<source_key>/``; parsing uses the stdlib ``csv``
  module only — imported content is never executed.
* Size/type validation blocks non-CSV/text files and oversized uploads.
* Every attempt (success, skipped, or failure) records an ``IngestionRun``
  with accepted/rejected/quarantined counts, warnings, hashes, and bounded
  redacted error text.
* Reruns of an identical file are recorded as ``skipped`` (use
  ``force=True`` for repeat imports; per-row dedup makes them safe).
"""

import csv
import hashlib
import io
import json
import re
import time
import uuid as uuid_module
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import MATERIAL_CATEGORIES, RECOVERY_ROUTES
from app.models import ExternalDataRecord, ExternalDataSource, ExternalWarmFactor, User
from app.models.data_ingestion import IngestionRun, RawIngestionFile
from app.services import audit
from app.services.data_ingestion import sources as sources_service

INGESTION_VERSION = "data-ingestion-v1"

MAX_ROWS = 100_000
MAX_WARN_INLINE = 50
MAX_REJECT_INLINE = 50
ERROR_SNIPPET_CHARS = 500

MISSING_TOKENS = {"", "na", "n/a", "ne", "null", "none"}
ALLOWED_SUFFIXES = {".csv", ".txt"}
DEFAULT_UNCERTAINTY = 0.35

WARM_HEADER_ALIASES = {
    "material_category": {"material_category", "category", "material"},
    "management_pathway": {"management_pathway", "pathway", "recovery_route"},
    "quantity_kg_co2e_per_tonne": {
        "quantity_kg_co2e_per_tonne",
        "kg_co2e_per_metric_tonne",
        "value",
    },
    "uncertainty_ratio": {"uncertainty_ratio"},
    "note": {"note", "notes"},
}

FLOW_HEADER_ALIASES = {
    "jurisdiction": {"jurisdiction", "country", "area", "state"},
    "year": {"year"},
    "material_category": {"material_category", "category", "material_group"},
    "measure": {"measure", "indicator", "flow"},
    "unit": {"unit", "units"},
    "value": {"value", "quantity"},
    "notes": {"notes", "note"},
}

BACKEND_ROOT = Path(__file__).resolve().parents[3]
STAGED_ROOT = BACKEND_ROOT / "data" / "external" / "staged"

_NAME_SANITIZE = re.compile(r"[^A-Za-z0-9._+-]+")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(error: Exception) -> str:
    """Redacted, bounded error for run records (no secrets/payload echo)."""
    text = re.sub(r"\s+", " ", str(error))[:ERROR_SNIPPET_CHARS]
    if not text:
        text = error.__class__.__name__
    return text or error.__class__.__name__


def _missing(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in MISSING_TOKENS


def _canonical_headers(fieldnames: list[str], aliases: dict[str, set[str]]) -> tuple[dict[str, str], list[str]]:
    """Map raw headers to canonical names; returns (mapping, unknown)."""
    mapping: dict[str, str] = {}
    unknown: list[str] = []
    for raw in fieldnames:
        clean = (raw or "").strip().lower()
        matched = None
        for canonical, names in aliases.items():
            if clean in names and canonical not in mapping.values():
                matched = canonical
                break
        if matched is None:
            unknown.append(clean or "<blank>")
        else:
            mapping[matched] = clean
    return mapping, unknown


def _read_delimited(data: bytes) -> tuple[list[dict], list[str], list[str], str]:
    """Decode + parse CSV text; raises ValueError for unreadable input."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"file must be UTF-8 CSV text ({_safe_error(error)})") from error
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    if not fieldnames:
        raise ValueError("CSV has no header row")
    rows: list[dict] = []
    row_count = 0
    for row in reader:
        row_count += 1
        if row_count > MAX_ROWS:
            raise ValueError(f"file exceeds the {MAX_ROWS}-row import cap")
        rows.append(row)
    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows, fieldnames, [f"detected delimiter {'TAB' if delimiter == chr(9) else delimiter}"], delimiter


# ------------------------------------------------------------------ adapters


def parse_warm_factors(rows: list[dict], fieldnames: list[str]) -> dict:
    """Adapter ``warm_factor_csv``: validated factor rows via carbon rules."""
    from app.services import carbon

    mapping, unknown = _canonical_headers(fieldnames, WARM_HEADER_ALIASES)
    warnings: list[str] = []
    if unknown:
        warnings.append(f"unrecognized column(s) ignored: {', '.join(sorted(unknown)[:10])}")
    required = ("material_category", "management_pathway", "quantity_kg_co2e_per_tonne")
    missing_columns = [name for name in required if name not in mapping]
    if missing_columns:
        raise ValueError(
            "missing required column(s) for warm_factor_csv: "
            f"{', '.join(missing_columns)} (documented schema: "
            "material_category,management_pathway,quantity_kg_co2e_per_tonne)"
        )

    factor_rows: list[dict] = []
    rejected: list[dict] = []
    defaulted_uncertainty = 0
    off_vocabulary = 0
    for index, raw_row in enumerate(rows):
        def cell(canonical: str):
            return (raw_row.get(mapping[canonical]) or "").strip()

        row_index = index + 2  # +1 header, +1 one-based rows

        def reject(reason: str) -> None:
            rejected.append({"row_index": row_index, "reason": reason})

        category_raw = cell("material_category")
        pathway_raw = cell("management_pathway")
        value_raw = cell("quantity_kg_co2e_per_tonne")
        uncertainty_raw = cell("uncertainty_ratio")
        note_raw = cell("note")

        category = category_raw.strip().lower().replace(" ", "_")
        pathway = pathway_raw.strip().lower()
        note = note_raw or None

        if _missing(category_raw):
            reject("category missing or blank — no zero-fill is allowed")
            continue
        if _missing(pathway_raw):
            reject("pathway missing (NA/NE/blank) — explicit value required")
            continue
        if pathway not in RECOVERY_ROUTES or pathway == "other":
            reject(
                f"pathway '{pathway}' is not a managed platform pathway "
                "(expected one of: landfill, reuse, recycle, compost, energy_recovery)"
            )
            continue
        if _missing(value_raw):
            reject(
                f"factor value missing for ({category}, {pathway}) "
                "(NA/NE/blank) — never defaulted to zero"
            )
            continue
        try:
            value = Decimal(value_raw)
        except InvalidOperation:
            reject(f"invalid numeric factor value {value_raw!r} for ({category}, {pathway})")
            continue
        uncertainty = None
        if not _missing(uncertainty_raw):
            try:
                uncertainty = Decimal(uncertainty_raw)
                if not (Decimal("0") <= uncertainty <= Decimal("1")):
                    reject(f"uncertainty_ratio {uncertainty_raw!r} outside [0, 1]")
                    continue
            except InvalidOperation:
                reject(f"invalid uncertainty_ratio {uncertainty_raw!r}")
                continue

        if category not in MATERIAL_CATEGORIES:
            off_vocabulary += 1
        if uncertainty is None:
            defaulted_uncertainty += 1

        factor_rows.append(
            {
                "category": category,
                "pathway": pathway,
                "quantity_kg_co2e_per_tonne": float(value),
                "uncertainty_ratio": (
                    float(uncertainty) if uncertainty is not None else DEFAULT_UNCERTAINTY
                ),
                "note": note,
            }
        )

    if defaulted_uncertainty:
        warnings.append(
            f"{defaulted_uncertainty} row(s) omitted uncertainty_ratio; defaulted "
            f"to the documented {DEFAULT_UNCERTAINTY} worst-case ratio"
        )
    if off_vocabulary:
        warnings.append(
            f"{off_vocabulary} row(s) use categories outside the platform "
            "vocabulary; estimates for those categories will remain "
            "unsupported until upstream mappings exist"
        )
    return {
        "adapter": "warm_factor_csv",
        "factor_rows": factor_rows,
        "rejected": rejected,
        "warnings": warnings,
    }


def parse_tabular_rows(rows: list[dict], fieldnames: list[str]) -> dict:
    """Adapter ``tabular_csv``: normalized material-flow rows."""
    mapping, unknown = _canonical_headers(fieldnames, FLOW_HEADER_ALIASES)
    warnings: list[str] = []
    if unknown:
        warnings.append(f"unrecognized column(s) ignored: {', '.join(sorted(unknown)[:10])}")
    required = ("jurisdiction", "year", "material_category", "measure", "unit", "value")
    missing_columns = [name for name in required if name not in mapping]
    if missing_columns:
        raise ValueError(
            "missing required column(s) for tabular_csv: "
            f"{', '.join(missing_columns)} (documented schema: "
            "jurisdiction,year,material_category,measure,unit,value)"
        )

    records: list[dict] = []
    rejected: list[dict] = []
    missing_values = 0
    for index, raw_row in enumerate(rows):
        row_index = index + 2

        def reject(reason: str) -> None:
            rejected.append({"row_index": row_index, "reason": reason})

        def cell(canonical: str) -> str:
            return (raw_row.get(mapping[canonical]) or "").strip()

        jurisdiction = cell("jurisdiction").upper()
        year_raw = cell("year")
        category = cell("material_category").strip().lower().replace(" ", "_")
        measure = cell("measure").strip().lower().replace(" ", "_")
        unit = cell("unit").strip().lower()
        value_raw = cell("value")
        notes = cell("notes") or None

        if _missing(jurisdiction):
            reject("jurisdiction missing — row cannot be geographically scoped")
            continue
        if _missing(year_raw):
            reject("year missing — row cannot be time-scoped")
            continue
        try:
            year = int(year_raw)
            if not (1900 <= year <= 2100):
                reject(f"year {year_raw!r} outside plausible range [1900, 2100]")
                continue
        except ValueError:
            reject(f"invalid year {year_raw!r}")
            continue
        if _missing(category):
            reject("material_category missing")
            continue
        if _missing(measure):
            reject("measure missing")
            continue
        if _missing(unit):
            reject("unit missing — units are never silently assumed")
            continue

        missing_token = None
        if _missing(value_raw):
            value = None
            token_raw = (value_raw or "").strip()
            missing_token = (
                token_raw.upper()
                if token_raw.strip().lower() in MISSING_TOKENS and token_raw.strip()
                else "blank"
            )
        else:
            try:
                value = float(Decimal(value_raw))
            except InvalidOperation:
                reject(f"invalid numeric value {value_raw!r} for ({jurisdiction}, {year}, {category}, {measure})")
                continue

        row_data = {
            "jurisdiction": jurisdiction,
            "year": year,
            "material_category": category,
            "measure": measure,
            "unit": unit,
            "value": value,
            "notes": notes,
        }
        natural_key = "|".join(
            [jurisdiction, str(year), category, measure, unit]
        )
        note = None
        if value is None:
            missing_values += 1
            note = (
                f"value missing (token {missing_token!r}) — normalized to null, "
                "never zero-filled"
            )
        content_hash = _sha256(
            json.dumps(row_data, sort_keys=True, default=str).encode("utf-8")
        )
        records.append(
            {
                "natural_key": natural_key,
                "content_hash": content_hash,
                "row_data": row_data,
                "note": note,
                "missing_value": value is None,
            }
        )

    return {
        "adapter": "tabular_csv",
        "records": records,
        "rejected": rejected,
        "warnings": warnings,
        "missing_value_rows": missing_values,
    }


_ADAPTERS = {
    "warm_factor_csv": parse_warm_factors,
    "tabular_csv": parse_tabular_rows,
}


# --------------------------------------------------------------- file staging


def _sanitize_name(name: str) -> str:
    cleaned = _NAME_SANITIZE.sub("_", (name or "").strip())[:120]
    return cleaned or "import.csv"


def _load_input_bytes(
    upload_data: bytes | None,
    upload_name: str | None,
    local_path: str | None,
    max_file_bytes: int,
) -> tuple[bytes, str, str | None]:
    if upload_data is not None:
        if not upload_data:
            raise ValueError("uploaded file is empty")
        if len(upload_data) > max_file_bytes:
            raise ValueError(
                f"file is {len(upload_data)} bytes; import cap is {max_file_bytes} bytes"
            )
        name = _sanitize_name(upload_name or "upload.csv")
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"file type '{Path(name).suffix or '<none>'}' not allowed; import only "
                f"accepts {', '.join(sorted(ALLOWED_SUFFIXES))}"
            )
        return upload_data, name, None
    if local_path:
        path = Path(local_path)
        if not (path.is_file() and path.exists()):
            raise ValueError(f"local_path does not point to a readable file: {local_path!r}")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError(
                f"file type '{path.suffix or '<none>'}' not allowed; import only "
                f"accepts {', '.join(sorted(ALLOWED_SUFFIXES))}"
            )
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ValueError(
                f"file is {size} bytes; import cap is {max_file_bytes} bytes"
            )
        return path.read_bytes(), path.name, str(path.resolve())
    raise ValueError("no file provided (upload a CSV or pass local_path)")


# ----------------------------------------------------------------- persistence

_FLOW_KEY_CHUNK = 500


def _persist_flow_records(
    db: Session,
    source: ExternalDataSource,
    records: list[dict],
    run_id: uuid_module.UUID,
    file_hash: str,
) -> tuple[int, int, int]:
    """Batched flow-record persistence.

    Same semantics as the original per-row promote/upsert (insert-new /
    reactivate-same-hash / unchanged / supersede; intra-file duplicates
    resolved with the last occurrence winning and history preserved) but
    the DB is consulted once per key-chunk for the whole file instead of
    once per row: per-row flushes on the ``autoflush=False`` session made
    large imports pathological.
    """
    accepted = updated = unchanged = 0

    unique_keys = list(dict.fromkeys(record["natural_key"] for record in records))
    found: dict[str, list[ExternalDataRecord]] = {}
    db.flush()
    for chunk_start in range(0, len(unique_keys), _FLOW_KEY_CHUNK):
        chunk = unique_keys[chunk_start:chunk_start + _FLOW_KEY_CHUNK]
        for row in db.scalars(
            select(ExternalDataRecord).where(
                ExternalDataRecord.source_id == source.id,
                ExternalDataRecord.natural_key.in_(chunk),
            )
        ).all():
            found.setdefault(row.natural_key, []).append(row)

    pending: dict[str, tuple[str, str]] = {}  # natural_key -> (hash, "active"|"inactive")
    inserts: list[ExternalDataRecord] = []

    def insert_record(key: str, content_hash: str, record: dict) -> None:
        row = ExternalDataRecord(
            source_id=source.id,
            natural_key=key,
            content_hash=content_hash,
            status="active",
            row_data=record["row_data"],
            provenance={
                "file_hash": file_hash,
                "source_key": source.key,
                "row_schema": "material_flow_v1",
            },
            note=record.get("note"),
            run_id=run_id,
        )
        inserts.append(row)
        db.add(row)

    for record in records:
        key = record["natural_key"]
        content_hash = record["content_hash"]
        state = pending.get(key)
        if state is not None:
            prev_hash, prev_state = state
            if prev_hash == content_hash:
                if prev_state == "active":
                    unchanged += 1
                else:
                    updated += 1
                    pending[key] = (content_hash, "active")
                continue
            # different content for the same natural key: the earlier
            # pending insert becomes superseded, this one becomes active
            pending[key] = (content_hash, "active")
            for obj in inserts:
                if obj.natural_key == key and obj.status == "active":
                    obj.status = "superseded"
            insert_record(key, content_hash, record)
            continue

        existing = found.get(key, [])
        if any(row.status == "active" and row.content_hash == content_hash for row in existing):
            unchanged += 1
            pending[key] = (content_hash, "active")
            continue
        reactivated = next(
            (row for row in existing if row.content_hash == content_hash), None
        )
        if reactivated is not None:
            reactivated.status = "active"
            reactivated.run_id = run_id
            updated += 1
            pending[key] = (content_hash, "active")
            continue
        for row in existing:
            if row.status == "active":
                row.status = "superseded"
        pending[key] = (content_hash, "active")
        insert_record(key, content_hash, record)
        accepted += 1

    if inserts or any(row.status != "active" for rows in found.values() for row in rows):
        db.flush()
    return accepted, updated, unchanged


def _promote_or_upsert_record(
    db: Session,
    source: ExternalDataSource,
    record: dict,
    run_id: uuid_module.UUID,
    file_hash: str,
    accepted: int,
    updated: int,
    unchanged: int,
) -> tuple[int, int, int]:
    # autoflush=False session: publish pending writes before the dedup query
    # so intra-file duplicate keys are detected, not just cross-run ones.
    db.flush()
    existing = db.scalars(
        select(ExternalDataRecord).where(
            ExternalDataRecord.source_id == source.id,
            ExternalDataRecord.natural_key == record["natural_key"],
        )
    ).all()
    same_hash_active = next(
        (row for row in existing if row.status == "active" and row.content_hash == record["content_hash"]),
        None,
    )
    if same_hash_active is not None:
        return accepted, updated, unchanged + 1
    same_hash_any = next(
        (row for row in existing if row.content_hash == record["content_hash"]),
        None,
    )
    if same_hash_any is not None:
        same_hash_any.status = "active"
        same_hash_any.run_id = run_id
        return accepted, updated + 1, unchanged
    for row in existing:
        if row.status == "active":
            row.status = "superseded"
    db.add(
        ExternalDataRecord(
            source_id=source.id,
            natural_key=record["natural_key"],
            content_hash=record["content_hash"],
            status="active",
            row_data=record["row_data"],
            provenance={
                "file_hash": file_hash,
                "source_key": source.key,
                "row_schema": "material_flow_v1",
            },
            note=record.get("note"),
            run_id=run_id,
        )
    )
    return accepted + 1, updated, unchanged


def _record_failed_run(
    db: Session,
    actor: User | None,
    source_key: str,
    source: ExternalDataSource | None,
    params: dict,
    error: Exception,
) -> IngestionRun:
    run = IngestionRun(
        source_id=source.id if source is not None else None,
        source_key=source_key,
        status="failed",
        mode="manual",
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


def import_staged_file(
    db: Session,
    actor: User,
    source_key: str,
    *,
    upload_data: bytes | None = None,
    upload_name: str | None = None,
    local_path: str | None = None,
    declared_version: str | None = None,
    force: bool = False,
    max_file_bytes: int | None = None,
) -> dict:
    """End-to-end staged-file import: stage, parse, validate, persist, record.

    Raises ``ValueError`` for domain-refusable situations (400/422 territory)
    after recording a failed run so every attempt stays auditable.
    """
    from app.core.config import get_settings

    max_file_bytes = (
        max_file_bytes
        if max_file_bytes is not None
        else get_settings().data_ingestion_max_file_mb * 1024 * 1024
    )

    sources_service.ensure_sources(db)
    source = db.scalar(select(ExternalDataSource).where(ExternalDataSource.key == source_key))
    params = {
        "source_key": source_key,
        "declared_version": declared_version,
        "force": bool(force),
        "origin": "upload" if upload_data is not None else "local_path",
    }
    if source is None:
        _record_failed_run(db, actor, source_key, None, params, ValueError(f"unknown source key '{source_key}'"))
        raise ValueError(f"Unknown source key '{source_key}'")
    if not source.enabled:
        _record_failed_run(db, actor, source_key, source, params, ValueError("source is not enabled for import"))
        raise ValueError(f"Source '{source_key}' is not enabled for import")
    adapter = _ADAPTERS.get(source.adapter or "")
    if adapter is None:
        _record_failed_run(db, actor, source_key, source, params, ValueError("adapter not implemented yet"))
        raise ValueError(
            f"Source '{source_key}' has no implemented adapter yet "
            f"(adapter_status={source.adapter_status})"
        )

    started_at = time.perf_counter()
    run_started = _now()
    try:
        data, filename, origin_path = _load_input_bytes(upload_data, upload_name, local_path, max_file_bytes)
        file_hash = _sha256(data)

        last_success = db.scalar(
            select(IngestionRun)
            .where(
                IngestionRun.source_id == source.id,
                IngestionRun.file_hash == file_hash,
                IngestionRun.status == "success",
            )
            .order_by(IngestionRun.started_at.desc())
        )
        if last_success is not None and not force:
            run = IngestionRun(
                source_id=source.id,
                source_key=source.key,
                status="skipped",
                mode="manual",
                params=params,
                stats={
                    "reason": (
                        f"identical file (sha256 {file_hash[:16]}…) already "
                        "ingested for this source; repeat imports are safe"
                    ),
                    "previous_run_id": str(last_success.id),
                },
                file_hash=file_hash,
                runtime_ms=int((time.perf_counter() - started_at) * 1000),
                triggered_by=actor.id,
                started_at=run_started,
                finished_at=_now(),
            )
            db.add(run)
            source.latest_run_at = run.finished_at
            db.flush()
            return {"run_id": str(run.id), "status": "skipped", "stats": run.stats}

        rows, fieldnames, parse_warnings, _delimiter = _read_delimited(data)
        parsed = adapter(rows, fieldnames)
        warnings = list(parse_warnings) + list(parsed["warnings"])

        # Stage raw copy + raw-file row BEFORE touching normalized data.
        staged_dir = STAGED_ROOT / source.key
        staged_dir.mkdir(parents=True, exist_ok=True)
        dest = staged_dir / f"{file_hash[:12]}_{_sanitize_name(filename)}"
        if not dest.exists():
            dest.write_bytes(data)
        stored_path = str(dest.relative_to(BACKEND_ROOT))

        raw = db.scalar(
            select(RawIngestionFile).where(
                RawIngestionFile.source_id == source.id,
                RawIngestionFile.file_hash == file_hash,
            )
        )
        if raw is None:
            raw = RawIngestionFile(
                source_id=source.id,
                file_hash=file_hash,
                original_name=filename,
                stored_path=stored_path,
                size_bytes=len(data),
                declared_version=declared_version,
            )
            db.add(raw)
            db.flush()
        else:
            raw.last_imported_at = _now()
            raw.import_count = (raw.import_count or 1) + 1
            if declared_version:
                raw.declared_version = declared_version

        run = IngestionRun(
            source_id=source.id,
            source_key=source.key,
            status="success",
            mode="manual",
            params=params,
            stats={},
            file_hash=file_hash,
            triggered_by=actor.id,
            started_at=run_started,
        )
        db.add(run)
        db.flush()

        declared_version = declared_version or source.declared_version
        stats: dict = {
            "ingestion_version": INGESTION_VERSION,
            "adapter": parsed["adapter"],
            "rows_total": len(rows),
            "file_name": filename,
            "file_hash": file_hash,
            "file_size_bytes": len(data),
            "stored_path": stored_path,
            "declared_version": declared_version,
            "origin_path": origin_path,
            "accepted": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": 0,
            "quarantined": 0,
            "warnings": warnings[:MAX_WARN_INLINE],
            "warnings_total": len(warnings),
            "rejected_rows": parsed["rejected"][:MAX_REJECT_INLINE],
        }
        if len(parsed["rejected"]) > MAX_REJECT_INLINE:
            stats["rejected_rows_truncated"] = True
        if len(warnings) > MAX_WARN_INLINE:
            stats["warnings_truncated"] = True

        factor_catalog_version: str | None = None

        if parsed["adapter"] == "warm_factor_csv":
            validation = _persist_warm_factors(
                db, source, parsed, run, file_hash, filename, declared_version
            )
            factor_catalog_version = validation["factor_catalog_version"]
            combined_rejected = validation["rejected"]
            stats.update(
                {
                    "accepted": validation["accepted"],
                    "quarantined": validation["quarantined"],
                    "activated_factor_rows": validation["activated"],
                    "deactivated_factor_rows": validation["deactivated"],
                    "factor_catalog_version": factor_catalog_version,
                    "factor_source": validation["factor_source"],
                    "missing_baseline_categories": validation["missing_baselines"],
                    "quarantine_examples": validation["quarantine_examples"],
                    "rejected_rows": combined_rejected[:MAX_REJECT_INLINE],
                    "rejected_rows_truncated": len(combined_rejected) > MAX_REJECT_INLINE or None,
                    "rejected": len(combined_rejected),
                }
            )
        else:
            accepted = updated = unchanged = 0
            accepted, updated, unchanged = _persist_flow_records(
                db, source, parsed["records"], run.id, file_hash
            )
            stats.update(
                {
                    "accepted": accepted,
                    "updated": updated,
                    "unchanged": unchanged,
                    "missing_value_rows": parsed["missing_value_rows"],
                    "rejected": len(parsed["rejected"]),
                }
            )

        db.flush()
        run.stats = {
            key: value for key, value in stats.items() if value is not None
        }
        run.finished_at = _now()
        run.runtime_ms = int((time.perf_counter() - started_at) * 1000)

        source.latest_file_hash = file_hash
        source.latest_run_at = run.finished_at
        if declared_version:
            source.declared_version = declared_version

        db.flush()
        return {
            "run_id": str(run.id),
            "status": "success",
            "stats": run.stats,
            "factor_catalog_version": factor_catalog_version,
        }
    except (ValueError, OSError) as error:
        _record_failed_run(db, actor, source_key, source, params, error)
        raise ValueError(_safe_error(error)) from error


def _persist_warm_factors(
    db: Session,
    source: ExternalDataSource,
    parsed: dict,
    run: IngestionRun,
    file_hash: str,
    filename: str,
    declared_version: str | None,
) -> dict:
    from app.services import carbon

    validation = carbon.validate_factor_catalog(parsed["factor_rows"])
    accepted_rows = validation["accepted"]
    rejected = list(parsed["rejected"]) + list(validation["rejected"])

    missing_baselines = set(validation["missing_baseline_categories"])
    active_rows: list[dict] = []
    quarantined: list[dict] = []
    for row in accepted_rows:
        if row["pathway"] != carbon.BASELINE_PATHWAY and row["category"] in missing_baselines:
            quarantined.append(
                {
                    **row,
                    "reason": (
                        "category has no landfill baseline in this file — "
                        "route row quarantined instead of activating a "
                        "partial factor set silently"
                    ),
                }
            )
        else:
            active_rows.append(row)

    version_seed = declared_version or "1"
    seed_slug = re.sub(r"[^A-Za-z0-9._+-]+", "-", version_seed).strip("-")[:20] or "1"
    catalog_version = f"factor-catalog-{source.key}-v{seed_slug}-{file_hash[:8]}"[:60]
    factor_source = (
        f"Ingested external factor set from {source.name} "
        f"(sha256 {file_hash[:12]}, run {str(run.id)[:8]})"
    )[:180]

    previous = (
        db.scalars(
            select(ExternalWarmFactor).where(ExternalWarmFactor.is_active.is_(True))
        ).all()
    )
    for row in previous:
        row.is_active = False
    if previous:
        db.flush()

    for row in active_rows:
        db.add(
            ExternalWarmFactor(
                run_id=run.id,
                catalog_version=catalog_version,
                factor_source=factor_source,
                category=row["category"],
                pathway=row["pathway"],
                value=Decimal(str(row["value"])).quantize(Decimal("0.0001")),
                uncertainty_ratio=Decimal(str(row["uncertainty_ratio"])).quantize(
                    Decimal("0.0001")
                ),
                note=row.get("note"),
                provenance={
                    "source_key": source.key,
                    "file_hash": file_hash,
                    "file_name": filename,
                    "adapter": parsed["adapter"],
                    "declared_version": declared_version,
                },
                is_active=True,
            )
        )

    return {
        "accepted": len(active_rows),
        "quarantined": len(quarantined),
        "activated": len(active_rows),
        "deactivated": len(previous),
        "missing_baselines": sorted(missing_baselines),
        "quarantine_examples": quarantined[:MAX_REJECT_INLINE],
        "factor_catalog_version": catalog_version,
        "factor_source": factor_source,
        "rejected_by_validation": [entry["reason"] for entry in validation["rejected"]],
        "rejected": rejected,
    }


def run_payload(run: IngestionRun) -> dict:
    return {
        "id": str(run.id),
        "source_key": run.source_key,
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


def audit_import(db: Session, actor: User, payload: dict, source_key: str) -> None:
    audit.record_audit(
        db,
        actor=actor,
        action="data_ingestion.import",
        entity_type="external_data_source",
        details={
            "source_key": source_key,
            "run_id": payload["run_id"],
            "status": payload["status"],
            "totals": {
                key: payload["stats"].get(key)
                for key in ("accepted", "updated", "unchanged", "rejected", "quarantined")
            },
        },
    )
