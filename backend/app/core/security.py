from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

_password_hasher = PasswordHash.recommended()

ALGORITHM = "HS256"


def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _password_hasher.verify(plain_password, password_hash)


def create_access_token(user_id: UUID, role: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
