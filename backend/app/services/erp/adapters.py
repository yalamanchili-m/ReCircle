"""Curated ERP adapter registry (blueprint Phase 16).

One file-transfer adapter is implemented today (manual CSV export/import
through this API); vendor API connectors are listed honestly as ``planned``
with the credential configuration names they would use — credentials are
only ever read from environment/secret configuration, never stored in code
or logs, and no vendor endpoint URLs are invented ahead of a real
integration contract.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ErpRun
from app.services.erp import schemas

ERP_REGISTRY_VERSION = "erp-adapter-registry-v1"

_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")

ERP_ADAPTERS: list[dict] = [
    {
        "key": "csv_generic",
        "name": "Generic CSV import/export (manual file transfer)",
        "family": "file_transfer",
        "vendor": "ReCircle platform",
        "produces_or_consumes": "both",
        "description": (
            "Preview/confirm import of CSV samples for the six supported "
            "entity schemas (organizations, materials, quantities, "
            "locations, transactions, recovery_records) and authorized CSV "
            "export of live platform data. This is the boundary every "
            "future vendor connector shares: the same schemas, the same "
            "idempotency keys, the same run bookkeeping."
        ),
        "adapter_status": "implemented",
        "credential_env_vars": [],
        "notes": (
            "Files enter through the admin API (multipart upload or "
            "local_path). Content is never executed; rows are validated "
            "against the entity schemas before staging."
        ),
    },
    {
        "key": "sap_s4hana_odata",
        "name": "SAP S/4HANA OData pull adapter",
        "family": "erp_api",
        "vendor": "SAP",
        "produces_or_consumes": "produces",
        "description": (
            "Would pull organization/material/transaction/recovery master "
            "data from an S/4HANA OData service and normalize it into the "
            "six entity schemas."
        ),
        "adapter_status": "planned",
        "credential_env_vars": [
            "ERP_SAP_ODATA_URL",
            "ERP_SAP_ODATA_USER",
            "ERP_SAP_ODATA_SECRET",
        ],
        "notes": (
            "Not implemented — no vendor contract/endpoint exists for this "
            "project, so no URL is configured or guessed. To activate, "
            "provide the OData service contract, register credentials in "
            "the secret store, and implement the schema mapping; the "
            "generic CSV path documents the expected row semantics in the "
            "meantime (docs/ERP_CONNECTOR.md)."
        ),
    },
    {
        "key": "oracle_fusion_cloud",
        "name": "Oracle Fusion Cloud ERP REST adapter",
        "family": "erp_api",
        "vendor": "Oracle",
        "produces_or_consumes": "produces",
        "description": (
            "Would pull inventory/transaction records from Oracle Fusion "
            "Cloud ERP REST endpoints into the six entity schemas."
        ),
        "adapter_status": "planned",
        "credential_env_vars": [
            "ERP_ORACLE_REST_URL",
            "ERP_ORACLE_REST_SECRET",
        ],
        "notes": (
            "Not implemented — same governance rule: no live integration is "
            "claimed until a vendor contract, credentials, and an "
            "integration test exist."
        ),
    },
]


def ensure_registry_consistent() -> dict:
    for entry in ERP_ADAPTERS:
        if not _KEY_PATTERN.match(entry["key"]):
            raise ValueError(f"invalid ERP adapter key {entry['key']!r}")
    for entity_key in schemas.ENTITY_SCHEMAS:
        assert entity_key, "entity schema key required"
    return {
        "registry_version": ERP_REGISTRY_VERSION,
        "adapters": len(ERP_ADAPTERS),
        "entities": len(schemas.ENTITY_SCHEMAS),
    }


def adapters_payload(db: Session) -> dict:
    """Registry payload for the API (runtime counts + last run per adapter)."""
    rows = db.execute(
        select(
            ErpRun.adapter_key,
            ErpRun.status,
            ErpRun.started_at,
            ErpRun.id,
        ).order_by(ErpRun.started_at.desc())
    ).all()
    status_count: dict[str, dict[str, int]] = {}
    last_run_at: dict[str, str] = {}
    for adapter_key, status, started_at, _run_id in rows:
        counters = status_count.setdefault(adapter_key, {})
        counters[status] = counters.get(status, 0) + 1
        if adapter_key not in last_run_at and started_at is not None:
            last_run_at[adapter_key] = started_at.isoformat()
    adapters = []
    for entry in ERP_ADAPTERS:
        adapter = dict(entry)
        adapter["entities"] = sorted(schemas.ENTITY_SCHEMAS)
        adapter["run_history"] = last_run_at.get(entry["key"])
        adapter["run_counts"] = status_count.get(entry["key"], {})
        adapters.append(adapter)
    return {
        "registry_version": ERP_REGISTRY_VERSION,
        "entities": schemas.entities_payload(),
        "adapters": adapters,
    }
