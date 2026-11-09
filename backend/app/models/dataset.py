"""Curated online cases survive source log retention independently."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EvaluationDataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_datasets"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class EvaluationSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_samples"
    __table_args__ = (
        UniqueConstraint("dataset_id", "source_run_id", name="uq_evaluation_sample_source"),
        CheckConstraint("label IN ('good', 'bad')", name="label_valid"),
        CheckConstraint("state IN ('draft', 'ready', 'archived')", name="state_valid"),
        CheckConstraint("scope IN ('turn', 'history')", name="scope_valid"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index("ix_evaluation_samples_dataset_created", "dataset_id", "created_at"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False
    )
    # Deliberately no FK: deleting old run logs must not change identity or erase the snapshot.
    source_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rubric: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ready_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
