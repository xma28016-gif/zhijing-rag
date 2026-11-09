"""Anonymous browser sessions, conversations, and durable chat messages."""

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
from app.models.enums import ChatRole, ExperienceRole, database_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BrowserSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        Index("ix_browser_sessions_expires_at", "expires_at"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )

    # The raw random token is kept by the browser; only its SHA-256 is persisted.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    selected_role: Mapped[ExperienceRole] = mapped_column(
        database_enum(ExperienceRole, name="experience_role"),
        nullable=False,
        server_default=text("'user'"),
    )
    active_assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    client_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    active_assistant: Mapped[Any | None] = relationship("Assistant")
    conversations: Mapped[list[ChatConversation]] = relationship(
        back_populates="browser_session", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_chat_conversations_browser_updated", "browser_session_id", "updated_at"),
        Index("ix_chat_conversations_assistant", "assistant_id"),
    )

    browser_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE")
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    external_conversation_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255))
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    browser_session: Mapped[BrowserSession | None] = relationship(back_populates="conversations")
    assistant: Mapped[Any] = relationship("Assistant", back_populates="conversations")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.sequence",
    )
    runs: Mapped[list[Any]] = relationship("RunRecord", back_populates="conversation", passive_deletes=True)


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_chat_messages_sequence"),
        CheckConstraint("sequence >= 0", name="sequence_nonnegative"),
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_records.id", ondelete="SET NULL")
    )
    role: Mapped[ChatRole] = mapped_column(database_enum(ChatRole, name="chat_role"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSONB), nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    usage: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
    run: Mapped[Any | None] = relationship("RunRecord", foreign_keys=[run_id])
