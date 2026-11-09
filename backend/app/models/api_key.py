"""Hashed external API credentials and assistant access bindings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ApiKeyStatus, ExperienceRole, database_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("rate_limit_per_minute > 0", name="rate_limit_positive"),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at", name="expiry_after_creation"),
        Index("ix_api_keys_status_expires", "status", "expires_at"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[ApiKeyStatus] = mapped_column(
        database_enum(ApiKeyStatus, name="api_key_status"),
        nullable=False,
        server_default=text("'active'"),
    )
    allow_all_assistants: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_role: Mapped[ExperienceRole] = mapped_column(
        database_enum(ExperienceRole, name="experience_role"),
        nullable=False,
        server_default=text("'admin'"),
    )

    assistant_bindings: Mapped[list[ApiKeyAssistant]] = relationship(
        back_populates="api_key", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list[object]] = relationship("RunRecord", back_populates="api_key")


class ApiKeyAssistant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_key_assistants"
    __table_args__ = (
        UniqueConstraint("api_key_id", "assistant_id", name="uq_api_key_assistants_binding"),
        Index("ix_api_key_assistants_assistant", "assistant_id"),
    )

    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="CASCADE"), nullable=False
    )

    api_key: Mapped[ApiKey] = relationship(back_populates="assistant_bindings")
    assistant: Mapped[object] = relationship("Assistant")
