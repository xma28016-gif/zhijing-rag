"""Contracts shared by document parsing, preview, indexing, and APIs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    BuildStatus,
    BuildTaskType,
    ChunkKind,
    DocumentSourceType,
    KnowledgeBaseStatus,
    ParserKind,
)


class FileDisposition(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"
    REJECT = "reject"


class ParseRoute(BaseModel):
    disposition: FileDisposition
    parser_kind: ParserKind | None
    reason_code: str
    reason_message: str
    data_egress_required: bool = False
    detected_extension: str
    page_count: int | None = None


class StructuredBlock(BaseModel):
    ordinal: int = Field(ge=0)
    kind: ChunkKind
    content: str
    title_path: list[str] = Field(default_factory=list)
    page_from: int | None = Field(default=None, gt=0)
    page_to: int | None = Field(default=None, gt=0)
    sheet_name: str | None = None
    cell_range: str | None = None
    object_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_page_range(self) -> StructuredBlock:
        if self.page_from and self.page_to and self.page_to < self.page_from:
            raise ValueError("page_to must be greater than or equal to page_from")
        return self


class ParseResult(BaseModel):
    parser_kind: ParserKind
    blocks: list[StructuredBlock]
    page_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    parser_metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkMode(StrEnum):
    SMART = "smart"
    TITLE = "title"
    DELIMITER = "delimiter"
    FIXED = "fixed"
    PARENT_CHILD = "parent_child"
    SEMANTIC = "semantic"
    QA = "qa"
    PAGE = "page"
    TABLE_ROW = "table_row"


class ChunkSettings(BaseModel):
    mode: ChunkMode = ChunkMode.SMART
    target_tokens: int = Field(default=800, ge=100, le=4_000)
    overlap_tokens: int = Field(default=120, ge=0, le=1_000)
    delimiter: str = Field(default="\n\n", min_length=1, max_length=100)
    parent_target_tokens: int = Field(default=1600, ge=100, le=8_000)
    semantic_threshold: float = Field(default=0.65, ge=-1, le=1)
    table_rows: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_overlap(self) -> ChunkSettings:
        if self.mode in {ChunkMode.PAGE, ChunkMode.QA, ChunkMode.TABLE_ROW, ChunkMode.SEMANTIC}:
            self.overlap_tokens = 0
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")
        if self.mode is ChunkMode.PARENT_CHILD and self.parent_target_tokens <= self.target_tokens:
            raise ValueError("父块长度必须大于子块目标长度。")
        return self


class ChunkPreview(BaseModel):
    ordinal: int = Field(ge=0)
    kind: ChunkKind
    content: str
    token_count: int = Field(ge=0)
    char_count: int = Field(ge=0)
    title_path: list[str] = Field(default_factory=list)
    page_from: int | None = None
    page_to: int | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    object_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseDeleteRead(BaseModel):
    storage_cleanup_complete: bool


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    embedding_model_config_id: UUID
    knowledge_base_type: Literal["general", "table"] = "general"
    chunk_target_tokens: int = Field(default=800, ge=100, le=4_000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_chunks(self) -> KnowledgeBaseCreate:
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_target_tokens")
        return self


class KnowledgeBaseRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    description: str | None
    knowledge_base_type: Literal["general", "table"]
    status: KnowledgeBaseStatus
    embedding_model_config_id: UUID
    embedding_dimension: int | None
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    file_size_limit_bytes: int
    page_limit: int
    batch_file_limit: int
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    chunk_target_tokens: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap_tokens: int | None = Field(default=None, ge=0, le=1000)


class EmbeddingModelOption(BaseModel):
    id: UUID
    name: str
    model_id: str
    provider_name: str
    embedding_dimension: int
    is_default: bool


class RerankModelOption(BaseModel):
    id: UUID
    name: str
    model_id: str
    provider_name: str
    is_default: bool


class ImportItemRead(BaseModel):
    filename: str
    accepted: bool
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    build_task_id: UUID | None = None
    route: ParseRoute
    content_sha256: str
    status: BuildStatus | None = None
    message: str


class ImportBatchRead(BaseModel):
    items: list[ImportItemRead]


class BuildTaskRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    knowledge_base_id: UUID
    document_version_id: UUID
    status: BuildStatus
    progress: int
    current_step: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class BuildTaskDetailRead(BuildTaskRead):
    task_type: BuildTaskType
    document_name: str
    document_version: int
    parser_kind: ParserKind
    attempt_count: int
    max_attempts: int
    cancel_requested: bool
    started_at: datetime | None
    finished_at: datetime | None
    chunk_settings: ChunkSettings | None = None


class DocumentRead(BaseModel):
    deleted_at: datetime | None = None
    id: UUID
    name: str
    source_type: DocumentSourceType
    mime_type: str | None
    current_content_sha256: str | None
    latest_version_id: UUID
    latest_version_number: int
    latest_status: BuildStatus
    parser_kind: ParserKind
    size_bytes: int
    page_count: int | None
    is_active: bool
    latest_task_id: UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentSourceRead(BaseModel):
    knowledge_base_id: UUID
    document_id: UUID
    document_name: str
    version_number: int


class DocumentContentRead(DocumentSourceRead):
    source_type: DocumentSourceType
    mime_type: str | None
    status: BuildStatus
    deleted_at: datetime | None
    size_bytes: int
    page_count: int | None
    content_source: str
    blocks: list[StructuredBlock]
    warnings: list[str]
    total: int
    offset: int
    limit: int


class ChunkRead(BaseModel):
    id: UUID
    document_version_id: UUID
    document_name: str
    document_version: int
    ordinal: int
    kind: ChunkKind
    content: str
    title_path: list[str]
    page_from: int | None
    page_to: int | None
    sheet_name: str | None
    cell_range: str | None
    token_count: int
    char_count: int
    is_enabled: bool


class ChunkListResponse(BaseModel):
    items: list[ChunkRead]
    total: int
    offset: int
    limit: int


class ChunkPreviewResponse(BaseModel):
    task: BuildTaskRead
    settings: ChunkSettings
    chunks: list[ChunkPreview]
    warnings: list[str] = Field(default_factory=list)


class RetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    rerank_model_config_id: UUID | None = None
    semantic_top_k: int = Field(default=30, ge=1, le=100)
    keyword_top_k: int = Field(default=30, ge=1, le=100)
    fusion_top_k: int = Field(default=20, ge=1, le=100)
    final_top_k: int = Field(default=6, ge=1, le=20)


class RetrievalHit(BaseModel):
    chunk_id: UUID
    document_name: str
    document_version: int
    chunk_ordinal: int
    content: str
    title_path: list[str]
    page_from: int | None
    page_to: int | None
    sheet_name: str | None
    cell_range: str | None
    parent_id: str | None = None
    semantic_score: float | None = None
    keyword_score: float | None = None
    rrf_score: float
    rerank_score: float | None = None


class RetrievalTestResponse(BaseModel):
    query: str
    results: list[RetrievalHit]
    embedding_ms: int = Field(ge=0)
    retrieval_ms: int = Field(ge=0)
    rerank_ms: int = Field(ge=0)
