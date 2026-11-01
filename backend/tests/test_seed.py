from sqlalchemy import func, select

from app.db.seed import seed
from app.db.session import SessionLocal
from app.models import MaterialRequirement, Organization, User, WasteListing


def test_seed_is_idempotent():
    first = seed()
    second = seed()
    assert first == second
    assert first["users_total"] >= 3
    assert first["listings_total"] >= 5
    assert first["requirements_total"] >= 3


def test_seed_creates_expected_demo_data():
    with SessionLocal() as db:
        org = db.scalar(
            select(Organization).where(Organization.name == "Shakti Metals Works")
        )
        assert org is not None
        assert org.organization_type == "generator"

        buyer = db.scalar(select(User).where(User.email == "buyer@recircle.local"))
        assert buyer is not None
        assert buyer.role == "buyer"
        assert buyer.password_hash != "ReCircleDemo123!"
        assert buyer.password_hash.startswith("$argon2")

        listing_titles = {
            row for row in db.scalars(select(WasteListing.title))
        }
        assert "Mild Steel Offcuts" in listing_titles
        assert "Wood Pallet Offcuts" in listing_titles

        requirement_titles = {
            row for row in db.scalars(select(MaterialRequirement.title))
        }
        assert "Ferrous Metal Scrap Supply" in requirement_titles


def test_seed_rerun_does_not_overwrite_user_edits():
    """Seed is create-if-missing: manual edits to seeded rows survive reruns."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "generator@recircle.local"))
        user.full_name = "Manually Edited Name"
        db.commit()
    try:
        seed()
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "generator@recircle.local"))
            assert user.full_name == "Manually Edited Name"
    finally:
        # Restore so other tests and the demo environment are unaffected.
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "generator@recircle.local"))
            user.full_name = "Demo Generator"
            db.commit()


def test_seed_rerun_does_not_duplicate_or_overwrite_listings():
    with SessionLocal() as db:
        listing = db.scalar(
            select(WasteListing).where(
                WasteListing.title == "Mild Steel Offcuts"
            )
        )
        listing.quantity = 123.000
        db.commit()

    before = seed()
    after = seed()

    assert before == after  # no duplication
    with SessionLocal() as db:
        listings = db.scalars(
            select(WasteListing).where(WasteListing.title == "Mild Steel Offcuts")
        ).all()
        assert len(listings) == 1
        assert float(listings[0].quantity) == 123.000  # edit not overwritten
