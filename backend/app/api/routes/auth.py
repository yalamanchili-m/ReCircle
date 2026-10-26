from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse, UserSummary
from app.services import audit

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == request.email.lower()))
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    token, expires_at = create_access_token(user.id, user.role)
    audit.record_audit(
        db,
        actor=user,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email},
    )
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserSummary.model_validate(user),
    )


@router.get("/auth/me", response_model=UserSummary)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserSummary:
    return UserSummary.model_validate(current_user)
