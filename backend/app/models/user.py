import uuid

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ROLES
from app.db.session import Base

from .organization import Organization


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('generator', 'buyer', 'admin')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization | None] = relationship(lazy="joined")

    def __init__(self, **kwargs):
        if "role" in kwargs and kwargs["role"] not in ROLES:
            raise ValueError(f"Invalid role: {kwargs['role']}")
        super().__init__(**kwargs)
