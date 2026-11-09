"""Long-lived daily aggregates produced before detailed log retention expires."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MetricScope, database_enum
from app.models.mixins import UUIDPrimaryKeyMixin


class DailyMetric(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="request_count_nonnegative"),
        CheckConstraint("success_count >= 0", name="success_count_nonnegative"),
        CheckConstraint("error_count >= 0", name="error_count_nonnegative"),
        CheckConstraint("insufficient_evidence_count >= 0", name="insufficient_evidence_count_nonnegative"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_nonnegative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_nonnegative"),
        CheckConstraint("total_tokens >= 0", name="total_tokens_nonnegative"),
        CheckConstraint("total_duration_ms >= 0", name="total_duration_nonnegative"),
        CheckConstraint("total_retrieved_chunks >= 0", name="retrieved_chunks_nonnegative"),
        CheckConstraint(
            "(scope = 'system' AND scope_id IS NULL) OR (scope <> 'system' AND scope_id IS NOT NULL)",
            name="scope_id_presence",
        ),
        Index(
            "uq_daily_metrics_system",
            "metric_date",
            "channel",
            unique=True,
            postgresql_where=text("scope = 'system'"),
        ),
        Index(
            "uq_daily_metrics_scoped",
            "metric_date",
            "scope",
            "scope_id",
            "channel",
            unique=True,
            postgresql_where=text("scope_id IS NOT NULL"),
        ),
        Index("ix_daily_metrics_date_scope", "metric_date", "scope"),
    )

    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[MetricScope] = mapped_column(
        database_enum(MetricScope, name="metric_scope"), nullable=False
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'all'"))
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    insufficient_evidence_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_retrieved_chunks: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
