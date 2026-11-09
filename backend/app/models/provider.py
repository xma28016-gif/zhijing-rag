"""Model provider connections and concrete model configurations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModelKind, ValidationStatus, database_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ModelProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A provider connection; built-ins are seeded as editable templates."""

    __tablename__ = "model_providers"

    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    api_style: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'openai_compatible'")
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_mask: Mapped[str | None] = mapped_column(String(100))
    default_headers: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    configuration_schema: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    model_configs: Mapped[list[ModelConfig]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A selectable LLM, embedding, or rerank model under a provider."""

    __tablename__ = "model_configs"
    __table_args__ = (
        UniqueConstraint("provider_id", "kind", "name", name="uq_model_configs_provider_kind_name"),
        UniqueConstraint("provider_id", "kind", "model_id", name="uq_model_configs_provider_kind_model"),
        CheckConstraint(
            "embedding_dimension IS NULL OR embedding_dimension > 0",
            name="embedding_dimension_positive",
        ),
        CheckConstraint(
            "max_context_tokens IS NULL OR max_context_tokens > 0",
            name="max_context_tokens_positive",
        ),
        Index(
            "uq_model_configs_default_kind",
            "kind",
            unique=True,
            postgresql_where=text("is_default AND enabled"),
        ),
        Index("ix_model_configs_provider_kind", "provider_id", "kind"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_providers.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[ModelKind] = mapped_column(database_enum(ModelKind, name="model_kind"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Optional per-model overrides; provider values are used when these are null.
    base_url: Mapped[str | None] = mapped_column(String(500))
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_mask: Mapped[str | None] = mapped_column(String(100))
    extra_headers: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    extra_config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    max_context_tokens: Mapped[int | None] = mapped_column(Integer)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    supports_usage: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    validation_status: Mapped[ValidationStatus] = mapped_column(
        database_enum(ValidationStatus, name="validation_status"),
        nullable=False,
        server_default=text("'untested'"),
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_latency_ms: Mapped[int | None] = mapped_column(Integer)
    validation_error: Mapped[str | None] = mapped_column(Text)
    total_requests: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    provider: Mapped[ModelProvider] = relationship(back_populates="model_configs")
