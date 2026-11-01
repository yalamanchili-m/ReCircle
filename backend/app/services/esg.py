"""ESG dashboard and export (blueprint Phase 12).

Aggregates recovery records (user-reported outcomes) with their current
factor-based impact estimates into a reconcilable dashboard. Key rules:

- Every KPI is traceable to source recovery records (ids and counts are
  carried in the payload; no static numbers).
- Metric states are always distinguishable: `user_reported` for recovered
  quantities/routes, `estimated` for factor-based impact values,
  `verified` only for records confirmed by a platform admin.
- Aggregation happens per recovery record using only `is_current`
  estimates, so neither listings, matches, transactions, superseded
  estimates, nor repeated previews can double-count.
- Quantities are never summed across incompatible units; mass is
  normalized to tonnes only for units the platform can convert.
- Green credit is an indicative visualization with explicit disclaimers;
  no official credit issuance, tradability, or certification is implied.
"""

import csv
import io
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ImpactEstimate,
    MaterialRequirement,
    Offer,
    RecoveryRecord,
    Transaction,
    User,
    WasteListing,
)
from app.services import carbon

ESG_VERSION = "esg-dashboard-v1"

CSV_COLUMNS = [
    "recovery_record_id",
    "transaction_id",
    "listing_id",
    "listing_title",
    "category",
    "seller_organization",
    "buyer_organization",
    "recovered_quantity",
    "unit",
    "recovery_route",
    "verification_status",
    "recorded_at",
    "estimate_supported",
    "avoided_co2e_kg",
    "landfill_diverted_kg",
    "method",
    "factor_catalog_version",
    "uncertainty",
]


def scoped_recovery_rows(
    db: Session,
    user: User,
    period_from: date_type | None = None,
    period_to: date_type | None = None,
) -> list[dict]:
    """Recovery records the user's organization is a party to, with sources.

    A generator sees records for listings it sells; a buyer sees records for
    its requirements; a platform admin (role admin, no organization) sees all.
    Each row keeps the exact source references so KPIs reconcile to records.
    """
    query = (
        select(RecoveryRecord)
        .join(Transaction, RecoveryRecord.transaction_id == Transaction.id)
        .join(Offer, Transaction.offer_id == Offer.id)
        .join(WasteListing, Offer.listing_id == WasteListing.id)
        .join(MaterialRequirement, Offer.requirement_id == MaterialRequirement.id)
        .outerjoin(
            ImpactEstimate,
            (ImpactEstimate.recovery_record_id == RecoveryRecord.id)
            & (ImpactEstimate.is_current.is_(True)),
        )
        .options(
            joinedload(RecoveryRecord.transaction).joinedload(Transaction.offer).joinedload(Offer.listing),
            joinedload(RecoveryRecord.transaction).joinedload(Transaction.offer).joinedload(Offer.requirement),
            joinedload(RecoveryRecord.estimates),
        )
        .order_by(RecoveryRecord.recorded_at.desc(), RecoveryRecord.id)
    )
    if not (user.role == "admin" and user.organization_id is None):
        org_id = user.organization_id
        query = query.where(
            (WasteListing.organization_id == org_id)
            | (MaterialRequirement.organization_id == org_id)
        )
    if period_from is not None:
        query = query.where(RecoveryRecord.recorded_at >= period_from)
    if period_to is not None:
        query = query.where(RecoveryRecord.recorded_at < _day_after(period_to))

    recovery_records = db.scalars(query).unique().all()

    rows = []
    for recovery in recovery_records:
        transaction = recovery.transaction
        offer = transaction.offer
        listing = offer.listing
        requirement = offer.requirement
        current = next(
            (est for est in recovery.estimates if est.is_current), None
        )
        rows.append({
            "recovery_record_id": recovery.id,
            "transaction_id": transaction.id,
            "listing_id": listing.id,
            "listing_title": listing.title,
            "category": listing.category,
            "seller_organization_id": listing.organization_id,
            "buyer_organization_id": requirement.organization_id,
            "seller_organization": listing.organization.name,
            "buyer_organization": requirement.organization.name,
            "recovered_quantity": recovery.recovered_quantity,
            "unit": recovery.unit,
            "recovery_route": recovery.recovery_route or "other",
            "verification_status": recovery.verification_status,
            "verified": recovery.verification_status == "verified",
            "recorded_at": recovery.recorded_at,
            "estimate": current,
            "user_notes": recovery.calculation_notes,
        })
    return rows


def build_dashboard(
    db: Session,
    user: User,
    period_from: date_type | None = None,
    period_to: date_type | None = None,
) -> dict:
    rows = scoped_recovery_rows(db, user, period_from, period_to)
    recorded_dates = [
        row["recorded_at"].date() for row in rows if row["recorded_at"] is not None
    ]
    first_recorded = min(recorded_dates).isoformat() if recorded_dates else None
    last_recorded = max(recorded_dates).isoformat() if recorded_dates else None

    recovered_by_unit: dict[str, dict] = {}
    kg_diverted_total = Decimal("0")
    kg_co2e_total = Decimal("0")
    band_low_total = Decimal("0")
    band_high_total = Decimal("0")
    band_rows = 0
    band_rows_missing = 0
    supported_estimates = 0
    unsupported_records: list[str] = []
    route_breakdown: dict[str, dict] = {}
    verified_count = 0
    unverified_count = 0
    records_payload = []

    for row in rows:
        recorded_at = row["recorded_at"]
        date_only = recorded_at.date().isoformat() if recorded_at is not None else None

        unit = row["unit"]
        bucket = recovered_by_unit.setdefault(
            unit,
            {"unit": unit, "total": 0.0, "record_count": 0, "basis": "user_reported"},
        )
        bucket["total"] = float(Decimal(str(bucket["total"])) + row["recovered_quantity"])
        bucket["record_count"] += 1

        if row["verified"]:
            verified_count += 1
        else:
            unverified_count += 1

        route = row["recovery_route"]
        breakdown = route_breakdown.setdefault(
            route,
            {"recovery_route": route, "record_count": 0, "tonnes_recovered": 0.0},
        )
        breakdown["record_count"] += 1

        estimate = row["estimate"]
        estimate_supported = bool(estimate is not None and estimate.supported)
        if estimate_supported:
            supported_estimates += 1
            diverted = estimate.landfill_diverted_kg or Decimal("0")
            avoided = estimate.avoided_co2e_kg or Decimal("0")
            kg_diverted_total += diverted
            kg_co2e_total += avoided
            band = estimate.assumptions or {}
            if band.get("avoided_co2e_kg_low") is not None:
                band_low_total += Decimal(str(band["avoided_co2e_kg_low"]))
                band_high_total += Decimal(str(band["avoided_co2e_kg_high"]))
                band_rows += 1
            else:
                band_rows_missing += 1
            tonnes = float(estimate.quantity_tonnes or 0)
            breakdown["tonnes_recovered"] = round(breakdown["tonnes_recovered"] + tonnes, 6)
        else:
            reason = (
                estimate.unsupported_reason if estimate is not None else "Estimate not available"
            )
            unsupported_records.append(
                {
                    "recovery_record_id": str(row["recovery_record_id"]),
                    "reason": reason,
                }
            )

        records_payload.append(
            {
                "recovery_record_id": str(row["recovery_record_id"]),
                "transaction_id": str(row["transaction_id"]),
                "listing_id": str(row["listing_id"]),
                "listing_title": row["listing_title"],
                "category": row["category"],
                "seller_organization": row["seller_organization"],
                "buyer_organization": row["buyer_organization"],
                "recovered_quantity": float(row["recovered_quantity"]),
                "unit": row["unit"],
                "recovery_route": route,
                "verification_status": row["verification_status"],
                "recorded_date": date_only,
                "estimate": _estimate_payload(estimate),
                "user_notes": row["user_notes"],
            }
        )

    for unit_bucket in recovered_by_unit.values():
        unit_bucket["total"] = round(unit_bucket["total"], 3)
    for breakdown in route_breakdown.values():
        breakdown["tonnes_recovered"] = round(breakdown["tonnes_recovered"], 6)

    mass_records = [row for row in rows if row["unit"] in carbon.MASS_UNIT_TO_KG]
    non_mass_count = len(rows) - len(mass_records)
    mass_kg_total = Decimal("0")
    for row in mass_records:
        mass_kg_total += row["recovered_quantity"] * carbon.MASS_UNIT_TO_KG[row["unit"]]

    points = carbon.green_credit_points(
        float(kg_diverted_total), float(kg_co2e_total)
    )

    return {
        "version": ESG_VERSION,
        "period": {
            "from": period_from.isoformat() if period_from else None,
            "to": period_to.isoformat() if period_to else None,
            "basis": "recovery_record.recorded_at (UTC date)",
        },
        "coverage": {
            "recovery_record_count": len(rows),
            "verified_count": verified_count,
            "unverified_count": unverified_count,
            "records_with_supported_estimate": supported_estimates,
            "records_without_supported_estimate": len(unsupported_records),
            "first_recorded_date": first_recorded,
            "last_recorded_date": last_recorded,
        },
        "metrics": {
            "recovered_by_unit": list(recovered_by_unit.values()),
            "mass_normalized": {
                "tonnes_recovered": float(mass_kg_total / Decimal("1000")),
                "record_count": len(mass_records),
                "excluded_non_mass_records": non_mass_count,
                "excluded_reason": (
                    "litre/unit quantities cannot be converted to mass without "
                    "density or item weights" if non_mass_count else None
                ),
            },
            "landfill_diverted": {
                "tonnes_estimate": float(kg_diverted_total / Decimal("1000")),
                "kg_estimate": float(kg_diverted_total),
                "basis": "estimated (factor-based)",
                "record_count": supported_estimates,
            },
            "avoided_emissions": {
                "kg_co2e_estimate": float(kg_co2e_total),
                "tonnes_estimate": float(kg_co2e_total / Decimal("1000")),
                "basis": "estimated (factor-based)",
                "method": carbon.METHOD,
                "factor_catalog_version": carbon.FACTOR_CATALOG_VERSION,
                "factor_source": carbon.FACTOR_SOURCE,
                "baseline_reference": carbon.BASELINE_REFERENCE,
                "uncertainty": (
                    {
                        "band_low_kg": float(band_low_total),
                        "band_high_kg": float(band_high_total),
                        "rows_with_band": band_rows,
                        "rows_without_band": band_rows_missing,
                        "basis": (
                            "summed worst-case interval over row-level "
                            "uncertainty ratios" if band_rows else None
                        ),
                    }
                    if supported_estimates
                    else None
                ),
                "unsupported_records": unsupported_records,
            },
            "recovery_route_breakdown": list(route_breakdown.values()),
            "verification": {
                "verified_count": verified_count,
                "unverified_count": unverified_count,
                "note": (
                    "Verified status is recorded by platform admins; "
                    "unverified rows are user-reported outcomes."
                ),
            },
        },
        "metric_states": {
            "user_reported": ["recovered_by_unit", "recovery_route", "calculation_notes"],
            "estimated": ["landfill_diverted", "avoided_emissions"],
            "verified": ["records with verification_status == 'verified'"],
        },
        "green_credit": {
            "points": points,
            "formula": "1 point per kg landfill-diverted + 1 point per kg CO2e avoided",
            "basis": "indicative visualization only",
            "disclaimers": carbon.CREDIT_DISCLAIMERS,
        },
        "records": records_payload,
        "limitations": carbon.LIMITATIONS,
    }


def _estimate_payload(estimate: ImpactEstimate | None) -> dict | None:
    if estimate is None:
        return None
    return {
        "id": str(estimate.id),
        "supported": estimate.supported,
        "unsupported_reason": estimate.unsupported_reason,
        "avoided_co2e_kg": float(estimate.avoided_co2e_kg) if estimate.avoided_co2e_kg is not None else None,
        "landfill_diverted_kg": (
            float(estimate.landfill_diverted_kg) if estimate.landfill_diverted_kg is not None else None
        ),
        "quantity_tonnes": float(estimate.quantity_tonnes) if estimate.quantity_tonnes is not None else None,
        "method": estimate.method,
        "factor_catalog_version": estimate.factor_catalog_version,
        "factor_source": estimate.factor_source,
        "baseline_reference": estimate.baseline_reference,
        "assumptions": estimate.assumptions,
        "created_at": estimate.created_at.isoformat(),
    }


def export_csv(
    db: Session, user: User, period_from: date_type | None, period_to: date_type | None
) -> str:
    rows = scoped_recovery_rows(db, user, period_from, period_to)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        estimate = row["estimate"]
        supported = bool(estimate is not None and estimate.supported)
        band = (estimate.assumptions or {}) if estimate else {}
        writer.writerow(
            {
                "recovery_record_id": row["recovery_record_id"],
                "transaction_id": row["transaction_id"],
                "listing_id": row["listing_id"],
                "listing_title": row["listing_title"],
                "category": row["category"],
                "seller_organization": row["seller_organization"],
                "buyer_organization": row["buyer_organization"],
                "recovered_quantity": row["recovered_quantity"],
                "unit": row["unit"],
                "recovery_route": row["recovery_route"],
                "verification_status": row["verification_status"],
                "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else "",
                "estimate_supported": "yes" if supported else "no",
                "avoided_co2e_kg": (
                    estimate.avoided_co2e_kg if supported and estimate else ""
                ),
                "landfill_diverted_kg": (
                    estimate.landfill_diverted_kg if supported and estimate else ""
                ),
                "method": estimate.method if estimate else "",
                "factor_catalog_version": estimate.factor_catalog_version if estimate else "",
                "uncertainty": (
                    (
                        f"[{band.get('avoided_co2e_kg_low', '')}; "
                        f"{band.get('avoided_co2e_kg_high', '')}] "
                        + str(band.get("uncertainty_basis", ""))
                    )
                    if supported and band.get("avoided_co2e_kg_low") is not None
                    else ("unsupported" if not supported else "not quantified")
                ),
            }
        )
    return buffer.getvalue()


def _day_after(value: date_type) -> date_type:
    from datetime import timedelta

    return value + timedelta(days=1)
