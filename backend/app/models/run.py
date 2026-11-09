"""Observable RAG executions and per-stage timing details."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    RunChannel,
    RunStatus,
    RunStepKind,
    UsageAccuracy,
    database_enum,
)
from app.models.mixins import UUIDPrimaryKeyMixin


class RunRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "run_records"
    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_nonnegative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_nonnegative"),
        CheckConstraint("total_tokens >= 0", name="total_tokens_nonnegative"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("retrieved_chunk_count >= 0", name="retrieved_chunk_count_nonnegative"),
        Index("ix_run_records_started_at", "started_at"),
        Index("ix_run_records_assistant_started", "assistant_id", "started_at"),
        Index("ix_run_records_status_started", "status", "started_at"),
        Index("ix_run_records_api_key_started", "api_key_id", "started_at"),
    )

    request_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_conversations.id", ondelete="SET NULL")
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    llm_model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    rerank_model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="SET NULL")
    )
    channel: Mapped[RunChannel] = mapped_column(database_enum(RunChannel, name="run_channel"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        database_enum(RunStatus, name="run_status"),
        nullable=False,
        server_default=text("'running'"),
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    evidence_sufficient: Mapped[bool | None] = mapped_column(Boolean)
    retrieved_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSONB), nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    retrieval_results: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSONB), nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    usage_accuracy: Mapped[UsageAccuracy] = mapped_column(
        database_enum(UsageAccuracy, name="usage_accuracy"),
        nullable=False,
        server_default=text("'unavailable'"),
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Any | None] = relationship(
        "ChatConversation", back_populates="runs", foreign_keys=[conversation_id]
    )
    assistant: Mapped[Any] = relationship("Assistant")
    api_key: Mapped[Any | None] = relationship("ApiKey", back_populates="runs")
    llm_model: Mapped[Any | None] = relationship("ModelConfig", foreign_keys=[llm_model_config_id])
    rerank_model: Mapped[Any | None] = relationship("ModelConfig", foreign_keys=[rerank_model_config_id])
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RunStep.sequence",
    )


class RunStep(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_steps_sequence"),
        CheckConstraint("sequence >= 0", name="sequence_nonnegative"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("input_tokens >= 0", name="input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="output_tokens_nonnegative"),
        Index("ix_run_steps_run_kind", "run_id", "kind"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_records.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[RunStepKind] = mapped_column(
        database_enum(RunStepKind, name="run_step_kind"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        database_enum(RunStatus, name="run_status"),
        nullable=False,
        server_default=text("'running'"),
    )
    input_summary: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    output_summary: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[RunRecord] = relationship(back_populates="steps")
