"""Idempotent seed script.

Creates clearly-marked SYNTHETIC demo organizations, users, listings, and
requirements. Running it repeatedly never duplicates records: every entity is
looked up by a stable natural key (email, organization name, or title within
organization) and only inserted when missing.

Demo passwords are for local demonstration only and are stored as Argon2 hashes.

Usage:
    python -m app.db.seed
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import MaterialRequirement, Organization, User, WasteListing

DEMO_PASSWORD = "ReCircleDemo123!"

DEMO_ORGANIZATIONS = [
    {
        "name": "Shakti Metals Works",
        "organization_type": "generator",
        "industry": "Metal fabrication",
        "description": "SYNTHETIC demo organization: mid-size steel fabrication plant.",
        "city": "Pune",
        "region": "Maharashtra",
    },
    {
        "name": "GreenPack Industries",
        "organization_type": "buyer",
        "industry": "Sustainable packaging",
        "description": "SYNTHETIC demo organization: recycled-materials packaging maker.",
        "city": "Mumbai",
        "region": "Maharashtra",
    },
    {
        "name": "ReCircle Demo Administration",
        "organization_type": "admin",
        "industry": "Platform operations",
        "description": "SYNTHETIC demo organization: admin account holder.",
        "city": "Pune",
        "region": "Maharashtra",
    },
]

DEMO_USERS = [
    {
        "email": "generator@recircle.local",
        "full_name": "Demo Generator",
        "role": "generator",
        "organization_name": "Shakti Metals Works",
    },
    {
        "email": "buyer@recircle.local",
        "full_name": "Demo Buyer",
        "role": "buyer",
        "organization_name": "GreenPack Industries",
    },
    {
        "email": "admin@recircle.local",
        "full_name": "Demo Admin",
        "role": "admin",
        "organization_name": "ReCircle Demo Administration",
    },
]

DEMO_LISTINGS = [
    {
        "title": "Mild Steel Offcuts",
        "category": "metals",
        "material_name": "Mild steel (IS 2062 E250)",
        "description": (
            "SYNTHETIC demo listing: clean offcuts of mild steel from a fabrication "
            "line. Mostly flat bar and angle pieces, light surface rust, no coatings."
        ),
        "composition": "Low carbon steel",
        "grade": "IS 2062 E250",
        "condition": "Clean, unmixed",
        "contamination_notes": "Trace cutting oil on some pieces",
        "quantity": 800.000,
        "unit": "kg",
        "price_per_unit": 18.00,
        "city": "Pune",
        "region": "Maharashtra",
        "status": "active",
    },
    {
        "title": "Clean Cardboard Sheets",
        "category": "paper_cardboard",
        "material_name": "Corrugated cardboard (OCC)",
        "description": (
            "SYNTHETIC demo listing: baled clean corrugated cardboard sheets from "
            "packaging waste. Dry, no food residue, staples removed."
        ),
        "composition": "Old corrugated containers",
        "grade": "OCC Grade 1",
        "condition": "Dry, baled",
        "contamination_notes": None,
        "quantity": 1200.000,
        "unit": "kg",
        "price_per_unit": 9.50,
        "city": "Pune",
        "region": "Maharashtra",
        "status": "active",
    },
    {
        "title": "Clear PET Plastic Flakes",
        "category": "plastics",
        "material_name": "PET flakes",
        "description": (
            "SYNTHETIC demo listing: washed clear PET bottle flakes, label and cap "
            "material removed. Suitable for fibre or sheet extrusion trials."
        ),
        "composition": "PET (resin code 1)",
        "grade": "Hot-washed clear flakes",
        "condition": "Washed, dried",
        "contamination_notes": "Minor PVC content possible, unverified",
        "quantity": 500.000,
        "unit": "kg",
        "price_per_unit": 55.00,
        "city": "Pune",
        "region": "Maharashtra",
        "status": "active",
    },
    {
        "title": "Wood Pallet Offcuts",
        "category": "wood",
        "material_name": "Mixed hardwood offcuts",
        "description": (
            "SYNTHETIC demo listing: offcuts and damaged pallet timber. Nails not "
            "fully removed. Saved as a draft example."
        ),
        "composition": "Mixed hardwood",
        "grade": None,
        "condition": "Unprocessed",
        "contamination_notes": "Contains nails and staples",
        "quantity": 900.000,
        "unit": "kg",
        "price_per_unit": None,
        "city": "Pune",
        "region": "Maharashtra",
        "status": "draft",
    },
    {
        "title": "Aluminium Extrusion Scrap",
        "category": "metals",
        "material_name": "Aluminium 6063 extrusion",
        "description": (
            "SYNTHETIC demo listing: clean 6063 aluminium extrusion scrap from window "
            "frame manufacturing. Free of iron fittings and paint."
            " Contact before pickup."
        ),
        "composition": "Aluminium alloy 6063",
        "grade": "6063 bare bright",
        "condition": "Clean, segregated",
        "contamination_notes": None,
        "quantity": 350.000,
        "unit": "kg",
        "price_per_unit": 160.00,
        "city": "Pune",
        "region": "Maharashtra",
        "available_from": date(2026, 11, 2),
        "status": "active",
    },
]

DEMO_REQUIREMENTS = [
    {
        "title": "Ferrous Metal Scrap Supply",
        "category": "metals",
        "description": "SYNTHETIC demo requirement: regular monthly supply of steel scrap for remelting trials.",
        "min_quantity": 500.000,
        "unit": "kg",
        "required_grade": "Low carbon steel",
        "max_price_per_unit": 22.00,
        "preferred_city": "Mumbai",
        "preferred_region": "Maharashtra",
        "status": "active",
    },
    {
        "title": "Clean Cardboard Supply",
        "category": "paper_cardboard",
        "description": "SYNTHETIC demo requirement: clean dry cardboard for recycled packaging board production.",
        "min_quantity": 1000.000,
        "unit": "kg",
        "required_grade": "OCC Grade 1",
        "max_price_per_unit": 12.00,
        "preferred_city": "Mumbai",
        "preferred_region": "Maharashtra",
        "status": "active",
    },
    {
        "title": "Clear PET Flakes Supply",
        "category": "plastics",
        "description": "SYNTHETIC demo requirement: washed clear PET flakes for sheet extrusion.",
        "min_quantity": 400.000,
        "unit": "kg",
        "required_grade": "Hot-washed clear flakes",
        "max_price_per_unit": 60.00,
        "preferred_city": "Mumbai",
        "preferred_region": "Maharashtra",
        "status": "active",
    },
]


def _get_or_create_organization(db: Session, spec: dict) -> Organization:
    organization = db.scalar(select(Organization).where(Organization.name == spec["name"]))
    if organization is None:
        organization = Organization(**spec)
        db.add(organization)
        db.flush()
    return organization


def _get_or_create_user(db: Session, spec: dict, password_hash: str) -> User:
    user = db.scalar(select(User).where(User.email == spec["email"]))
    if user is None:
        organization = db.scalar(
            select(Organization).where(Organization.name == spec["organization_name"])
        )
        assert organization is not None, f"Seed organization missing: {spec['organization_name']}"
        user = User(
            email=spec["email"],
            full_name=spec["full_name"],
            role=spec["role"],
            password_hash=password_hash,
            organization_id=organization.id,
            is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def _get_or_create_listing(
    db: Session, spec: dict, organization: Organization, creator: User
) -> WasteListing:
    listing = db.scalar(
        select(WasteListing).where(
            WasteListing.organization_id == organization.id,
            WasteListing.title == spec["title"],
        )
    )
    if listing is None:
        listing = WasteListing(
            **spec,
            organization_id=organization.id,
            created_by=creator.id,
        )
        db.add(listing)
        db.flush()
    return listing


def _get_or_create_requirement(
    db: Session, spec: dict, organization: Organization, creator: User
) -> MaterialRequirement:
    requirement = db.scalar(
        select(MaterialRequirement).where(
            MaterialRequirement.organization_id == organization.id,
            MaterialRequirement.title == spec["title"],
        )
    )
    if requirement is None:
        requirement = MaterialRequirement(
            **spec,
            organization_id=organization.id,
            created_by=creator.id,
        )
        db.add(requirement)
        db.flush()
    return requirement


def seed(db: Session | None = None) -> dict:
    """Seed demo data idempotently. Returns counts of created records."""
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        password_hash = hash_password(DEMO_PASSWORD)
        organizations = {
            spec["name"]: _get_or_create_organization(db, spec) for spec in DEMO_ORGANIZATIONS
        }
        users = {
            spec["email"]: _get_or_create_user(db, spec, password_hash) for spec in DEMO_USERS
        }

        generator_org = organizations["Shakti Metals Works"]
        buyer_org = organizations["GreenPack Industries"]
        generator_user = users["generator@recircle.local"]
        buyer_user = users["buyer@recircle.local"]

        for spec in DEMO_LISTINGS:
            _get_or_create_listing(db, spec, generator_org, generator_user)
        for spec in DEMO_REQUIREMENTS:
            _get_or_create_requirement(db, spec, buyer_org, buyer_user)

        db.commit()

        # Report table totals after seeding (deltas are zero on repeat runs).
        totals = {
            "users_total": db.scalar(select(func.count()).select_from(User)),
            "organizations_total": db.scalar(select(func.count()).select_from(Organization)),
            "listings_total": db.scalar(select(func.count()).select_from(WasteListing)),
            "requirements_total": db.scalar(
                select(func.count()).select_from(MaterialRequirement)
            ),
        }
        return totals
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def main() -> None:
    counts = seed()
    print(f"Seed complete (synthetic demo data only): {counts}")


if __name__ == "__main__":
    main()
