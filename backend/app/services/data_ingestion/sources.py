"""Curated external-data source registry (blueprint Phase 15).

Each registry entry records source description, jurisdiction, terms/licence
notes, URLs, dataset version, expected format, and update cadence. Adapters
are implemented one at a time per the blueprint priority: EPA WARM for
impact factors first, then a structured (CSV) material-flow source; the
remaining families stay listed and clearly labelled ``planned`` so the
registry is honest about capability.

``ensure_sources`` is an idempotent upsert: registry metadata is refreshed
from code, while runtime state (enabled, latest file/run) and localhost
changes are preserved. It never invents URLs.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExternalDataSource

DATA_INGESTION_REGISTRY_VERSION = "data-source-registry-v1"

_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")

DATA_SOURCE_REGISTRY: list[dict] = [
    {
        "key": "epa_warm_v15",
        "name": "US EPA Waste Reduction Model (WARM)",
        "family": "factor_catalog",
        "jurisdiction": "US",
        "description": (
            "Greenhouse gas emission and energy factors by material category "
            "and management pathway (landfilling, recycling, composting, "
            "combustion, source reduction), used as the reference catalog for "
            "platform carbon-impact estimates. Each import carries the "
            "ingested version label; v16 (Dec 2023) documented factors are "
            "the current published set."
        ),
        "homepage_url": "https://www.epa.gov/warm",
        "source_url": "https://www.epa.gov/smm/waste-reduction-model-warm",
        "terms_note": (
            "U.S. EPA material (public domain). Cite the ingested WARM "
            "version explicitly whenever its values are used; factors must "
            "be traceable to an ingestion run record."
        ),
        "access_note": (
            "The warm_v15.2.xls workbook is password-protected by EPA and "
            "cannot be parsed programmatically; factor rows must come from "
            "the published WARM documentation (e.g. EPA-530-R-23-018 v16 "
            "Exhibit 1-1/1-2) or manual extraction, staged as "
            "warm_factor_csv (schema in services/data_ingestion/ingest.py)."
        ),
        "expected_format": "warm_factor_csv",
        "adapter": "warm_factor_csv",
        "adapter_status": "implemented",
        "declared_version": None,
        "update_cadence": "episodic model revisions (check EPA site for updates)",
        "enabled": True,
    },
    {
        "key": "oecd_mfa",
        "name": "OECD Environment - Material Flow Accounts (SDMX CSV export)",
        "family": "material_flow",
        "jurisdiction": "GLOBAL",
        "description": (
            "Country/area, year, material group, measure, unit, and value "
            "time series exported from the OECD data explorer in SDMX-like "
            "CSV, feeding material-flow analytics on the platform."
        ),
        "homepage_url": "https://www.oecd.org/en/data/datasets/material-flow-accounts.html",
        "source_url": "https://data-explorer.oecd.org/",
        "terms_note": (
            "OECD data are published for analysis with attribution; confirm "
            "the current OECD terms-of-use page before any redistribution."
        ),
        "access_note": (
            "Download the SDMX-CSV export from the OECD public REST API, e.g. "
            "https://sdmx.oecd.org/public/rest/data/OECD.ENV.EPI,"
            "DSD_MATERIAL_RESOURCES@DF_MATERIAL_RESOURCES,1.0/all?format="
            "csvfilewithlabels (no API key required), trim to the desired "
            "period/units, and stage it via the import endpoint."
        ),
        "expected_format": "tabular_csv",
        "adapter": "tabular_csv",
        "adapter_status": "implemented",
        "declared_version": None,
        "update_cadence": "annual refresh of published series",
        "enabled": True,
    },
    {
        "key": "cpcb_india",
        "name": "CPCB India - state/district-wise waste inventory",
        "family": "national_inventory",
        "jurisdiction": "IN",
        "description": (
            "State, district, waste type/category, and generated/recycled/"
            "utilized/landfilled/incinerated quantities published by the "
            "Central Pollution Control Board."
        ),
        "homepage_url": "https://cpcb.nic.in/",
        "source_url": None,
        "terms_note": (
            "Government of India publication; check CPCB terms for reuse and "
            "attribution before redistribution."
        ),
        "access_note": (
            "PDF/structured tables require a dedicated parser; adapter is "
            "planned (blueprint allows one adapter at a time)."
        ),
        "expected_format": "tabular_csv",
        "adapter": None,
        "adapter_status": "planned",
        "declared_version": None,
        "update_cadence": "annual inventory publications",
        "enabled": False,
    },
    {
        "key": "us_epa_biennial",
        "name": "US EPA Biennial Hazardous Waste Report",
        "family": "hazardous_waste",
        "jurisdiction": "US",
        "description": (
            "Facility, location, waste type, quantity, year, management "
            "method, and industry classification from EPA's Biennial "
            "Hazardous Waste Report."
        ),
        "homepage_url": "https://www.epa.gov/hw/biennial-hazardous-waste-report-system-brs",
        "source_url": None,
        "terms_note": (
            "U.S. EPA open data (public domain); cite the reporting cycle "
            "used, e.g. 2021 BHR."
        ),
        "access_note": (
            "Facility-level schema needs its own adapter; planned (one "
            "adapter at a time per blueprint)."
        ),
        "expected_format": "tabular_csv",
        "adapter": None,
        "adapter_status": "planned",
        "declared_version": None,
        "update_cadence": "biennial reporting cycle",
        "enabled": False,
    },
]


def ensure_sources(db: Session) -> dict:
    """Idempotent registry sync; preserves runtime + admin state on update."""
    created = 0
    updated = 0
    for entry in DATA_SOURCE_REGISTRY:
        row = db.scalar(select(ExternalDataSource).where(ExternalDataSource.key == entry["key"]))
        if row is None:
            row = ExternalDataSource(
                key=entry["key"],
                name=entry["name"],
                family=entry["family"],
                jurisdiction=entry["jurisdiction"],
                description=entry["description"],
                homepage_url=entry["homepage_url"],
                source_url=entry.get("source_url"),
                terms_note=entry["terms_note"],
                access_note=entry.get("access_note"),
                expected_format=entry["expected_format"],
                adapter=entry.get("adapter"),
                adapter_status=entry.get("adapter_status", "planned"),
                declared_version=entry.get("declared_version"),
                update_cadence=entry["update_cadence"],
                enabled=entry.get("enabled", False),
            )
            db.add(row)
            created += 1
        else:
            row.name = entry["name"]
            row.family = entry["family"]
            row.jurisdiction = entry["jurisdiction"]
            row.description = entry["description"]
            row.homepage_url = entry["homepage_url"]
            row.source_url = entry.get("source_url")
            row.terms_note = entry["terms_note"]
            row.access_note = entry.get("access_note")
            row.expected_format = entry["expected_format"]
            row.adapter = entry.get("adapter")
            row.adapter_status = entry.get("adapter_status", "planned")
            row.update_cadence = entry["update_cadence"]
            if row.declared_version is None and entry.get("declared_version") is not None:
                row.declared_version = entry["declared_version"]
            updated += 1
    db.flush()
    return {
        "created": created,
        "updated": updated,
        "registry_version": DATA_INGESTION_REGISTRY_VERSION,
    }


def sources_payload(db: Session) -> dict:
    """Registry payload with runtime state for the API."""
    rows = {
        row.key: row
        for row in db.scalars(select(ExternalDataSource)).all()
    }
    sources = []
    for entry in DATA_SOURCE_REGISTRY:
        row = rows.get(entry["key"])
        source = dict(entry)
        source["db_row_present"] = row is not None
        if row is not None:
            source["enabled"] = row.enabled
            source["id"] = str(row.id)
            source["latest_file_hash"] = row.latest_file_hash
            source["latest_run_at"] = (
                row.latest_run_at.isoformat() if row.latest_run_at else None
            )
            source["declared_version"] = row.declared_version
            source["enabled"] = row.enabled
            source["id"] = str(row.id)
            source["latest_file_hash"] = row.latest_file_hash
            source["latest_run_at"] = (
                row.latest_run_at.isoformat() if row.latest_run_at else None
            )
            source["declared_version"] = row.declared_version
        else:
            source["enabled"] = entry.get("enabled", False)
            source["id"] = None
            source["latest_file_hash"] = None
            source["latest_run_at"] = None
        sources.append(source)
    return {
        "registry_version": DATA_INGESTION_REGISTRY_VERSION,
        "sources": sources,
    }
