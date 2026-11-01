"""Material Passport foundation service (blueprint Phase 3 / §4.1).

A passport is created from the listing's own data with `user_provided`
provenance. Edits create new immutable versions; the previous active version
is marked `superseded`. Review is a separate human action that must never
change content.
"""

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MaterialPassport, User, WasteListing
from app.schemas.passport import PassportUpdate

PASSPORT_FIELDS = (
    "material_name",
    "composition",
    "grade",
    "condition",
    "contamination_notes",
    "quantity",
    "unit",
    "city",
    "region",
)


def get_active_passport(db: Session, listing_id: UUID) -> MaterialPassport | None:
    return db.scalar(
        select(MaterialPassport).where(
            MaterialPassport.listing_id == listing_id,
            MaterialPassport.status == "active",
        )
    )


def get_passport_or_404(db: Session, listing_id: UUID) -> MaterialPassport:
    passport = get_active_passport(db, listing_id)
    if passport is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport not found for this listing"
        )
    return passport


def assert_can_manage(passport: MaterialPassport, user: User) -> None:
    if user.organization_id is None or passport.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner organization may manage this passport",
        )


def _attributes_from_listing(listing: WasteListing) -> dict:
    """Seed passport attributes from the listing itself (user-provided facts).

    Unknown values are stored as null with provenance `unverified`, never as
    zero or fabricated defaults.
    """
    attributes: dict = {}
    for field in PASSPORT_FIELDS:
        value = getattr(listing, field)
        if isinstance(value, Decimal):
            # JSONB cannot hold Decimal; keep full precision as a string.
            value = str(value)
        attributes[field] = {
            "value": value,
            "provenance": "user_provided" if value is not None else "unverified",
            "confidence": None,
        }
    return attributes


def create_passport(
    db: Session, listing: WasteListing, user: User, notes: str | None = None
) -> MaterialPassport:
    if get_active_passport(db, listing.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This listing already has an active passport",
        )
    passport = MaterialPassport(
        listing_id=listing.id,
        organization_id=listing.organization_id,
        version=1,
        status="active",
        attributes=_attributes_from_listing(listing),
        notes=notes,
        created_by=user.id,
    )
    db.add(passport)
    db.flush()
    return passport


def update_passport(
    db: Session, passport: MaterialPassport, payload: PassportUpdate, user: User
) -> MaterialPassport:
    data = payload.model_dump(exclude_unset=True)
    new_version = MaterialPassport(
        listing_id=passport.listing_id,
        organization_id=passport.organization_id,
        version=passport.version + 1,
        status="active",
        attributes=data.get("attributes", passport.attributes),
        possible_applications=data.get(
            "possible_applications", passport.possible_applications
        ),
        suitable_industries=data.get("suitable_industries", passport.suitable_industries),
        candidate_pathways=data.get("candidate_pathways", passport.candidate_pathways),
        notes=data.get("notes", passport.notes),
        review_status="unreviewed",  # new content requires fresh human review
        created_by=user.id,
    )
    passport.status = "superseded"
    db.add(new_version)
    db.flush()
    return new_version


def set_review_status(
    db: Session, passport: MaterialPassport, review_status: str, user: User
) -> MaterialPassport:
    from datetime import datetime, timezone

    passport.review_status = review_status
    if review_status == "reviewed":
        passport.reviewed_by = user.id
        passport.reviewed_at = datetime.now(timezone.utc)
    else:
        passport.reviewed_by = None
        passport.reviewed_at = None
    db.flush()
    return passport
