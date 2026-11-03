"""Authorized ERP exports (blueprint Phase 16).

Each export maps one of the six entity schemas to the *live* platform
tables and returns a bounded, fixed-column row set. Exports are
admin-gated, audited, and deliberately minimize personal contact data
(org names + region only — no user emails/phones here). Row order is
deterministic (primary key asc) so repeated exports are comparable.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ImpactEstimate,
    Organization,
    RecoveryRecord,
    Transaction,
    WasteListing,
)

EXPORT_VERSION = "erp-export-v1"


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _rows_organizations(db: Session) -> tuple[list[str], list[dict]]:
    columns = [
        "organization_id",
        "name",
        "organization_type",
        "city",
        "region",
        "country",
        "industry",
    ]
    rows = [
        {
            "organization_id": org.id,
            "name": org.name,
            "organization_type": org.organization_type,
            "city": org.city,
            "region": org.region,
            "country": org.country,
            "industry": org.industry,
        }
        for org in db.scalars(
            select(Organization).order_by(Organization.id)
        ).all()
    ]
    return columns, rows


def _rows_materials(db: Session) -> tuple[list[str], list[dict]]:
    columns = [
        "listing_id",
        "seller_organization",
        "title",
        "category",
        "material_name",
        "quantity",
        "unit",
        "status",
        "city",
        "region",
        "country",
        "created_at",
    ]
    rows = [
        {
            "listing_id": listing.id,
            "seller_organization": listing.organization.name,
            "title": listing.title,
            "category": listing.category,
            "material_name": listing.material_name,
            "quantity": listing.quantity,
            "unit": listing.unit,
            "status": listing.status,
            "city": listing.city,
            "region": listing.region,
            "country": listing.country,
            "created_at": listing.created_at,
        }
        for listing in db.scalars(
            select(WasteListing).order_by(WasteListing.id)
        ).all()
    ]
    return columns, rows


def _rows_quantities(db: Session) -> tuple[list[str], list[dict]]:
    columns = [
        "listing_id",
        "seller_organization",
        "quantity",
        "unit",
        "category",
        "status",
    ]
    rows = [
        {
            "listing_id": listing.id,
            "seller_organization": listing.organization.name,
            "quantity": listing.quantity,
            "unit": listing.unit,
            "category": listing.category,
            "status": listing.status,
        }
        for listing in db.scalars(
            select(WasteListing).order_by(WasteListing.id)
        ).all()
    ]
    return columns, rows


def _rows_locations(db: Session) -> tuple[list[str], list[dict]]:
    columns = ["city", "region", "country", "source_table", "record_count"]
    listings = db.execute(
        select(
            WasteListing.city,
            WasteListing.region,
            WasteListing.country,
            func.count(WasteListing.id),
        )
        .group_by(WasteListing.city, WasteListing.region, WasteListing.country)
        .order_by(WasteListing.city, WasteListing.region, WasteListing.country)
    ).all()
    orgs = db.execute(
        select(
            Organization.city,
            Organization.region,
            Organization.country,
            func.count(Organization.id),
        )
        .group_by(Organization.city, Organization.region, Organization.country)
        .order_by(Organization.city, Organization.region, Organization.country)
    ).all()
    rows = [
        {
            "city": city,
            "region": region,
            "country": country,
            "source_table": "waste_listings",
            "record_count": count,
        }
        for city, region, country, count in listings
    ] + [
        {
            "city": city,
            "region": region,
            "country": country,
            "source_table": "organizations",
            "record_count": count,
        }
        for city, region, country, count in orgs
    ]
    return columns, rows


def _rows_transactions(db: Session) -> tuple[list[str], list[dict]]:
    columns = [
        "transaction_id",
        "status",
        "agreed_quantity",
        "agreed_price_per_unit",
        "collection_date",
        "completed_at",
        "listing_title",
        "seller_organization",
        "buyer_organization",
        "created_at",
    ]
    rows = []
    transactions = db.scalars(select(Transaction).order_by(Transaction.id)).all()
    for txn in transactions:
        offer = txn.offer
        listing = offer.listing
        requirement = offer.requirement
        rows.append(
            {
                "transaction_id": txn.id,
                "status": txn.status,
                "agreed_quantity": txn.agreed_quantity,
                "agreed_price_per_unit": txn.agreed_price_per_unit,
                "collection_date": txn.collection_date,
                "completed_at": txn.completed_at,
                "listing_title": listing.title if listing else None,
                "seller_organization": (
                    listing.organization.name if listing else None
                ),
                "buyer_organization": (
                    requirement.organization.name if requirement else None
                ),
                "created_at": txn.created_at,
            }
        )
    return columns, rows


def _rows_recovery_records(db: Session) -> tuple[list[str], list[dict]]:
    columns = [
        "recovery_record_id",
        "transaction_id",
        "recovered_quantity",
        "unit",
        "recovery_route",
        "verification_status",
        "verified_at",
        "recorded_at",
        "current_avoided_co2e_kg",
        "factor_catalog_version",
        "estimate_supported",
    ]
    current_estimates = {
        est.recovery_record_id: est
        for est in db.scalars(
            select(ImpactEstimate).where(ImpactEstimate.is_current.is_(True))
        ).all()
    }
    rows = []
    for record in db.scalars(
        select(RecoveryRecord).order_by(RecoveryRecord.id)
    ).all():
        estimate = current_estimates.get(record.id)
        rows.append(
            {
                "recovery_record_id": record.id,
                "transaction_id": record.transaction_id,
                "recovered_quantity": record.recovered_quantity,
                "unit": record.unit,
                "recovery_route": record.recovery_route,
                "verification_status": record.verification_status,
                "verified_at": record.verified_at,
                "recorded_at": record.recorded_at,
                "current_avoided_co2e_kg": (
                    estimate.avoided_co2e_kg if estimate else None
                ),
                "factor_catalog_version": (
                    estimate.factor_catalog_version if estimate else None
                ),
                "estimate_supported": (
                    bool(estimate.supported) if estimate else None
                ),
            }
        )
    return columns, rows


_EXPORT_BUILDERS = {
    "organizations": _rows_organizations,
    "materials": _rows_materials,
    "quantities": _rows_quantities,
    "locations": _rows_locations,
    "transactions": _rows_transactions,
    "recovery_records": _rows_recovery_records,
}

EXPORT_ENTITIES: tuple[str, ...] = tuple(_EXPORT_BUILDERS)


def _stringify_row(row: dict, columns: list[str]) -> dict:
    return {column: _stringify(row.get(column)) for column in columns}


def export_entity(db: Session, entity_type: str, max_rows: int) -> dict:
    """Build a bounded export for one entity (deterministic ordering)."""
    builder = _EXPORT_BUILDERS.get(entity_type)
    if builder is None:
        raise ValueError(
            f"unknown export entity '{entity_type}' (supported: "
            f"{', '.join(sorted(EXPORT_ENTITIES))})"
        )
    columns, raw_rows = builder(db)
    truncated = len(raw_rows) > max_rows
    rows = [
        _stringify_row(row, columns) for row in raw_rows[:max_rows]
    ]
    return {
        "export_version": EXPORT_VERSION,
        "entity_type": entity_type,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
