import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import ALGORITHM, create_access_token
from app.db.seed import DEMO_PASSWORD, seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditLog, User

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    seed()


def _login(email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


DEMO_ACCOUNTS = [
    ("generator@recircle.local", "generator", "Shakti Metals Works"),
    ("buyer@recircle.local", "buyer", "GreenPack Industries"),
    ("admin@recircle.local", "admin", "ReCircle Demo Administration"),
]


@pytest.mark.parametrize("email,expected_role,expected_org", DEMO_ACCOUNTS)
def test_login_succeeds_for_seeded_accounts(email, expected_role, expected_org):
    response = _login(email, DEMO_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    assert body["user"]["role"] == expected_role
    assert body["user"]["organization"]["name"] == expected_org


def test_login_rejects_wrong_password():
    response = _login("generator@recircle.local", "wrong-password")
    assert response.status_code == 401


def test_login_rejects_unknown_email():
    response = _login("nobody@recircle.local", DEMO_PASSWORD)
    assert response.status_code == 401


def test_login_rejects_malformed_email():
    response = client.post(
        "/api/auth/login", json={"email": "not-an-email", "password": DEMO_PASSWORD}
    )
    assert response.status_code == 422


def test_me_returns_current_user_with_token():
    login_response = _login("buyer@recircle.local", DEMO_PASSWORD)
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "buyer@recircle.local"
    assert body["role"] == "buyer"
    assert body["organization"]["name"] == "GreenPack Industries"


def test_me_requires_token():
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_tampered_token():
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer tampered.token.value"}
    )
    assert response.status_code == 401


def test_organizations_me_returns_callers_organization():
    login_response = _login("generator@recircle.local", DEMO_PASSWORD)
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/organizations/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Shakti Metals Works"
    assert body["organization_type"] == "generator"


def test_organizations_me_requires_auth():
    response = client.get("/api/organizations/me")
    assert response.status_code == 401


def _token_with_payload(payload: dict) -> str:
    settings = get_settings()
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def test_expired_token_is_rejected():
    user_id = str(uuid.uuid4())  # any id; expiry is checked before lookup
    expired = _token_with_payload(
        {
            "sub": user_id,
            "role": "generator",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "iat": datetime.now(timezone.utc) - timedelta(minutes=61),
        }
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected():
    user_id = str(uuid.uuid4())
    forged = jwt.encode(
        {
            "sub": user_id,
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "iat": datetime.now(timezone.utc),
        },
        "not-the-real-secret",
        algorithm=ALGORITHM,
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_disabled_account_cannot_login_or_use_existing_token():
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "generator@recircle.local"))
        user.is_active = False
        db.commit()
        token, _ = create_access_token(user.id, user.role)
    try:
        login_response = _login("generator@recircle.local", DEMO_PASSWORD)
        assert login_response.status_code == 403

        me_response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 401
    finally:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "generator@recircle.local"))
            user.is_active = True
            db.commit()


def test_login_writes_audit_event():
    before = _audit_count("auth.login")
    response = _login("buyer@recircle.local", DEMO_PASSWORD)
    assert response.status_code == 200
    assert _audit_count("auth.login") == before + 1
    with SessionLocal() as db:
        row = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "auth.login")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert row.actor_user_id is not None
        assert row.entity_type == "user"


def test_listing_create_writes_audit_event():
    login_response = _login("generator@recircle.local", DEMO_PASSWORD)
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "title": "Audit Trail Copper",
        "description": "Audit test listing description",
        "category": "metals",
        "quantity": "10.000",
        "unit": "kg",
        "city": "Pune",
        "region": "Maharashtra",
    }
    before = _audit_count("listing.create")
    response = client.post("/api/listings", json=payload, headers=headers)
    assert response.status_code == 201
    assert _audit_count("listing.create") == before + 1


def _audit_count(action: str) -> int:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == action)).all()
        return len(list(rows))
