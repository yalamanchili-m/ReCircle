"""Offer -> Transaction -> RecoveryRecord workflow.

This provides the transactional source records that the ESG dashboard
(blueprint Phase 12) aggregates. Every stage enforces organization
ownership, records audit events in the same transaction, and keeps the
distinguishable metric states: user-reported recovery quantities, factor-
based impact estimates, and verified outcomes.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MaterialRequirement,
    Offer,
    RecoveryRecord,
    Transaction,
    User,
    WasteListing,
)
from app.schemas.trade import OfferCreate, RecoveryRecordCreate
from app.services import audit, carbon

RECORDABLE_STATUSES = ("agreed", "collection_scheduled", "in_transit", "delivered")


def _org_scoped_admin(user: User) -> bool:
    return user.role == "admin" and user.organization_id is None


def _require_membership(user: User, org_id: UUID, message: str) -> None:
    if _org_scoped_admin(user):
        return
    if user.organization_id is None or user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def create_offer(db: Session, user: User, data: OfferCreate) -> Offer:
    listing = db.get(WasteListing, data.listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    if listing.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only active listings can receive offers"
        )
    requirement = db.get(MaterialRequirement, data.requirement_id)
    if requirement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found"
        )
    if requirement.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only active requirements can create offers"
        )

    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Offers must be created by a user belonging to the buying organization",
        )
    _require_membership(
        user, requirement.organization_id, "Only the requirement's organization may create an offer"
    )

    if requirement.unit != listing.unit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unit mismatch: requirement unit '{requirement.unit}' differs from "
                f"listing unit '{listing.unit}'; quantities must not be compared "
                "across incompatible units"
            ),
        )

    offer = Offer(
        listing_id=listing.id,
        requirement_id=requirement.id,
        offered_by=user.id,
        quantity=data.quantity,
        price_per_unit=data.price_per_unit,
        message=data.message,
    )
    db.add(offer)
    db.flush()
    audit.record_audit(
        db,
        actor=user,
        action="offer.create",
        entity_type="offer",
        entity_id=offer.id,
        details={"listing_id": str(listing.id), "requirement_id": str(requirement.id)},
    )
    return offer


def list_offers(db: Session, user: User, page: int = 1, page_size: int = 20) -> tuple[list[Offer], int]:
    query = select(Offer).join(
        MaterialRequirement, Offer.requirement_id == MaterialRequirement.id
    )
    if not _org_scoped_admin(user):
        query = query.where(MaterialRequirement.organization_id == user.organization_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Offer.created_at.desc(), Offer.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return items, total


def get_offer_or_404(db: Session, offer_id: UUID) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found")
    return offer


def accept_offer(db: Session, user: User, offer_id: UUID) -> Transaction:
    offer = get_offer_or_404(db, offer_id)
    listing = db.get(WasteListing, offer.listing_id)
    if listing is None:  # pragma: no cover - listings are never deleted
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    _require_membership(
        user, listing.organization_id, "Only the listing's organization may accept an offer"
    )
    if offer.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offer is {offer.status}; only pending offers can be accepted",
        )
    if listing.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Listing is {listing.status}; only active listings can be matched",
        )

    existing = db.scalar(select(Transaction).where(Transaction.offer_id == offer.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Transaction already exists for this offer"
        )

    transaction = Transaction(
        offer_id=offer.id,
        status="agreed",
        agreed_quantity=offer.quantity,
        agreed_price_per_unit=offer.price_per_unit,
    )
    db.add(transaction)
    offer.status = "accepted"
    listing.status = "matched"
    db.flush()
    audit.record_audit(
        db,
        actor=user,
        action="offer.accept",
        entity_type="offer",
        entity_id=offer.id,
        details={"transaction_id": str(transaction.id), "listing_id": str(listing.id)},
    )
    return transaction


def withdraw_offer(db: Session, user: User, offer_id: UUID) -> Offer:
    offer = get_offer_or_404(db, offer_id)
    requirement = db.get(MaterialRequirement, offer.requirement_id)
    if requirement is not None:
        _require_membership(
            user,
            requirement.organization_id,
            "Only the offering organization may withdraw this offer",
        )
    if offer.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offer is {offer.status}; only pending offers can be withdrawn",
        )
    offer.status = "withdrawn"
    db.flush()
    audit.record_audit(
        db,
        actor=user,
        action="offer.withdraw",
        entity_type="offer",
        entity_id=offer.id,
    )
    return offer


def list_transactions(
    db: Session, user: User, page: int = 1, page_size: int = 20
) -> tuple[list[Transaction], int]:
    query = (
        select(Transaction)
        .join(Offer, Transaction.offer_id == Offer.id)
        .join(WasteListing, Offer.listing_id == WasteListing.id)
        .join(MaterialRequirement, Offer.requirement_id == MaterialRequirement.id)
    )
    if not _org_scoped_admin(user):
        org_id = user.organization_id
        query = query.where(
            (WasteListing.organization_id == org_id)
            | (MaterialRequirement.organization_id == org_id)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Transaction.created_at.desc(), Transaction.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return items, total


def get_transaction_for_user(db: Session, transaction_id: UUID, user: User) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    offer = db.get(Offer, transaction.offer_id)
    listing = db.get(WasteListing, offer.listing_id)
    requirement = db.get(MaterialRequirement, offer.requirement_id)

    admin_non_scoped = _org_scoped_admin(user)
    if not admin_non_scoped:
        org_id = user.organization_id
        is_party = bool(
            org_id is not None
            and org_id in (listing.organization_id, requirement.organization_id)
        )
        if not is_party:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only participants of this transaction may access it",
            )
    return transaction


def record_recovery(
    db: Session, user: User, transaction_id: UUID, data: RecoveryRecordCreate
) -> RecoveryRecord:
    transaction = get_transaction_for_user(db, transaction_id, user)
    if transaction.status not in RECORDABLE_STATUSES:
        if transaction.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Recovery outcome already recorded for this transaction",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transaction status '{transaction.status}' cannot record recovery yet",
        )

    offer = db.get(Offer, transaction.offer_id)
    listing = db.get(WasteListing, offer.listing_id)

    recovery = RecoveryRecord(
        transaction_id=transaction.id,
        recovered_quantity=data.recovered_quantity,
        unit=data.unit,
        recovery_route=data.recovery_route,
        environmental_estimate={},
        calculation_notes=data.calculation_notes,
        verification_status="unverified",
    )
    db.add(recovery)
    db.flush()

    transaction.status = "completed"
    transaction.completed_at = datetime.now(timezone.utc)

    # Factor-based estimate persisted with full provenance; unsupported
    # combinations are recorded as unsupported (never fabricated values).
    estimate = carbon.estimate_and_persist(db, recovery, listing.category)
    db.flush()

    audit.record_audit(
        db,
        actor=user,
        action="transaction.complete",
        entity_type="recovery_record",
        entity_id=recovery.id,
        details={
            "transaction_id": str(transaction.id),
            "estimate_supported": estimate.supported,
            "factor_catalog_version": carbon.FACTOR_CATALOG_VERSION,
        },
    )
    return recovery


def verify_recovery(db: Session, user: User, recovery_record_id: UUID) -> RecoveryRecord:
    """Platform-admin verification of a user-reported recovery outcome."""
    recovery = db.get(RecoveryRecord, recovery_record_id)
    if recovery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recovery record not found"
        )
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins may verify recovery records",
        )
    if recovery.verification_status == "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Recovery record already verified"
        )
    recovery.verification_status = "verified"
    recovery.verified_by = user.id
    recovery.verified_at = datetime.now(timezone.utc)
    db.flush()
    audit.record_audit(
        db,
        actor=user,
        action="recovery.verify",
        entity_type="recovery_record",
        entity_id=recovery.id,
    )
    return recovery


def get_recovery_for_user(db: Session, recovery_record_id: UUID, user: User) -> RecoveryRecord:
    recovery = db.get(RecoveryRecord, recovery_record_id)
    if recovery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recovery record not found"
        )
    transaction = db.get(Transaction, recovery.transaction_id)
    get_transaction_for_user(db, transaction.id, user)
    return recovery
