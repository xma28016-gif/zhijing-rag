"""Knowledge-base ingestion, versioning, chunks, and embeddings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    BuildStatus,
    BuildTaskType,
    ChunkKind,
    DocumentSourceType,
    KnowledgeBaseStatus,
    ParserKind,
    database_enum,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint("chunk_target_tokens > 0", name="chunk_target_tokens_positive"),
        CheckConstraint("chunk_overlap_tokens >= 0", name="chunk_overlap_nonnegative"),
        CheckConstraint("chunk_overlap_tokens < chunk_target_tokens", name="chunk_overlap_less_than_target"),
        CheckConstraint("file_size_limit_bytes > 0", name="file_size_limit_positive"),
        CheckConstraint("page_limit > 0", name="page_limit_positive"),
        CheckConstraint("batch_file_limit > 0", name="batch_file_limit_positive"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        database_enum(KnowledgeBaseStatus, name="knowledge_base_status"),
        nullable=False,
        server_default=text("'empty'"),
    )
    embedding_model_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False
    )
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    chunk_target_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("800"))
    chunk_overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("120"))
    file_size_limit_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("104857600")
    )
    page_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("500"))
    batch_file_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    chunk_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    settings: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    embedding_model: Mapped[Any] = relationship("ModelConfig", foreign_keys=[embedding_model_config_id])

    @property
    def knowledge_base_type(self) -> str:
        return self.settings.get("knowledge_base_type", "general")

    documents: Mapped[list[Document]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )
    assistant_bindings: Mapped[list[Any]] = relationship(
        "AssistantKnowledgeBase", back_populates="knowledge_base", passive_deletes=True
    )


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_knowledge_base", "knowledge_base_id"),
        Index(
            "uq_documents_active_content_hash",
            "knowledge_base_id",
            "current_content_sha256",
            unique=True,
            postgresql_where=text("current_content_sha256 IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        database_enum(DocumentSourceType, name="document_source_type"), nullable=False
    )
    mime_type: Mapped[str | None] = mapped_column(String(255))
    current_content_sha256: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        UniqueConstraint("document_id", "content_sha256", name="uq_document_versions_content"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_nonnegative"),
        CheckConstraint("NOT is_active OR status = 'ready'", name="active_version_is_ready"),
        Index(
            "uq_document_versions_one_active",
            "document_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_document_versions_status", "status"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_object_key: Mapped[str] = mapped_column(String(1_024), nullable=False, unique=True)
    parsed_object_key: Mapped[str | None] = mapped_column(String(1_024))
    parser_kind: Mapped[ParserKind] = mapped_column(
        database_enum(ParserKind, name="parser_kind"), nullable=False
    )
    status: Mapped[BuildStatus] = mapped_column(
        database_enum(BuildStatus, name="build_status"),
        nullable=False,
        server_default=text("'queued'"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    needs_cloud_parse: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    data_egress_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_result: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    preview_settings: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")
    tasks: Mapped[list[BuildTask]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan", passive_deletes=True
    )
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan", passive_deletes=True
    )


class BuildTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "build_tasks"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        Index("ix_build_tasks_kb_status", "knowledge_base_id", "status"),
        Index(
            "uq_build_tasks_one_open_per_version",
            "document_version_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'parsing', 'preview_ready', 'indexing', 'replacing')"
            ),
        ),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[BuildTaskType] = mapped_column(
        database_enum(BuildTaskType, name="build_task_type"), nullable=False
    )
    status: Mapped[BuildStatus] = mapped_column(
        database_enum(BuildStatus, name="build_status"),
        nullable=False,
        server_default=text("'queued'"),
    )
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    current_step: Mapped[str | None] = mapped_column(String(100))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    task_settings: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped[KnowledgeBase] = relationship()
    document_version: Mapped[DocumentVersion] = relationship(back_populates="tasks")


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_knowledge_chunks_ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint("char_count >= 0", name="char_count_nonnegative"),
        CheckConstraint("page_from IS NULL OR page_from > 0", name="page_from_positive"),
        CheckConstraint("page_to IS NULL OR page_to >= page_from", name="page_range_valid"),
        Index("ix_knowledge_chunks_version", "document_version_id"),
        Index(
            "ix_knowledge_chunks_active_lookup",
            "knowledge_base_id",
            "embedding_model_config_id",
            postgresql_where=text("is_active AND is_enabled"),
        ),
        Index("ix_knowledge_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    embedding_model_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ChunkKind] = mapped_column(
        database_enum(ChunkKind, name="chunk_kind"), nullable=False, server_default=text("'text'")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsv: Mapped[Any | None] = mapped_column(TSVECTOR)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title_path: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(String(255))), nullable=False, default=list, server_default=text("'{}'")
    )
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    cell_range: Mapped[str | None] = mapped_column(String(100))
    object_key: Mapped[str | None] = mapped_column(String(1_024))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    embedding: Mapped[Any | None] = mapped_column(Vector())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embedding_model: Mapped[Any] = relationship("ModelConfig")
