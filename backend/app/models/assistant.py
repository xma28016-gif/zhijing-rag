"""Knowledge assistants and their ordered knowledge-base bindings."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AssistantStatus, database_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Assistant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistants"
    __table_args__ = (
        CheckConstraint("semantic_top_k > 0", name="semantic_top_k_positive"),
        CheckConstraint("keyword_top_k > 0", name="keyword_top_k_positive"),
        CheckConstraint("rerank_top_k > 0", name="rerank_top_k_positive"),
        CheckConstraint("answer_top_k > 0", name="answer_top_k_positive"),
        CheckConstraint("max_context_tokens > 0", name="max_context_tokens_positive"),
        CheckConstraint(
            "relevance_threshold >= 0 AND relevance_threshold <= 1",
            name="relevance_threshold_range",
        ),
        CheckConstraint("temperature >= 0 AND temperature <= 2", name="temperature_range"),
        CheckConstraint("max_output_tokens > 0", name="max_output_tokens_positive"),
        Index("ix_assistants_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    alias: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AssistantStatus] = mapped_column(
        database_enum(AssistantStatus, name="assistant_status"),
        nullable=False,
        server_default=text("'draft'"),
    )
    llm_model_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False
    )
    rerank_model_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="RESTRICT")
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    insufficient_evidence_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'当前知识库未找到足够依据'"),
    )
    enable_query_rewrite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    semantic_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    keyword_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    answer_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("6"))
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("6000"))
    relevance_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0.5000")
    )
    temperature: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default=text("0.200"))
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2048"))
    extra_config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    llm_model: Mapped[Any] = relationship("ModelConfig", foreign_keys=[llm_model_config_id])
    rerank_model: Mapped[Any | None] = relationship("ModelConfig", foreign_keys=[rerank_model_config_id])
    knowledge_base_bindings: Mapped[list[AssistantKnowledgeBase]] = relationship(
        back_populates="assistant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssistantKnowledgeBase.priority",
    )
    conversations: Mapped[list[Any]] = relationship("ChatConversation", back_populates="assistant")


class AssistantKnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistant_knowledge_bases"
    __table_args__ = (
        UniqueConstraint("assistant_id", "knowledge_base_id", name="uq_assistant_knowledge_bases_binding"),
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
        Index("ix_assistant_knowledge_bases_kb", "knowledge_base_id"),
    )

    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    retrieval_overrides: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    assistant: Mapped[Assistant] = relationship(back_populates="knowledge_base_bindings")
    knowledge_base: Mapped[Any] = relationship("KnowledgeBase", back_populates="assistant_bindings")
