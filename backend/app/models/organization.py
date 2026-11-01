import uuid

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ORGANIZATION_TYPES
from app.db.session import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(30), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="India", server_default="India")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __init__(self, **kwargs):
        if "organization_type" in kwargs and kwargs["organization_type"] not in ORGANIZATION_TYPES:
            raise ValueError(f"Invalid organization_type: {kwargs['organization_type']}")
        super().__init__(**kwargs)
