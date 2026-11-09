"""Stable database enum values used by the 1.0 domain model."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SQLAlchemyEnum


class ModelKind(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ValidationStatus(StrEnum):
    UNTESTED = "untested"
    VALID = "valid"
    INVALID = "invalid"


class KnowledgeBaseStatus(StrEnum):
    EMPTY = "empty"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class DocumentSourceType(StrEnum):
    WORD = "word"
    PDF = "pdf"
    MARKDOWN = "markdown"
    IMAGE = "image"
    SPREADSHEET = "spreadsheet"
    CSV = "csv"
    OTHER = "other"


class ParserKind(StrEnum):
    LOCAL = "local"
    DOCMIND = "docmind"


class BuildStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    PREVIEW_READY = "preview_ready"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REPLACING = "replacing"


class BuildTaskType(StrEnum):
    IMPORT = "import"
    REPLACE = "replace"
    REINDEX = "reindex"


class ChunkKind(StrEnum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class AssistantStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class ExperienceRole(StrEnum):
    ADMIN = "admin"
    KNOWLEDGE_MANAGER = "manager"
    USER = "user"


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class RunChannel(StrEnum):
    BROWSER = "browser"
    API = "api"
    RETRIEVAL_TEST = "retrieval_test"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RunStepKind(StrEnum):
    QUERY_REWRITE = "query_rewrite"
    EMBEDDING = "embedding"
    SEMANTIC_RETRIEVAL = "semantic_retrieval"
    KEYWORD_RETRIEVAL = "keyword_retrieval"
    RRF_FUSION = "rrf_fusion"
    RERANK = "rerank"
    GENERATION = "generation"


class UsageAccuracy(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class MetricScope(StrEnum):
    SYSTEM = "system"
    ASSISTANT = "assistant"
    API_KEY = "api_key"
    MODEL = "model"


def database_enum(enum_type: type[StrEnum], *, name: str) -> SQLAlchemyEnum:
    """Build a native PostgreSQL enum using enum values rather than member names."""

    return SQLAlchemyEnum(
        enum_type,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
