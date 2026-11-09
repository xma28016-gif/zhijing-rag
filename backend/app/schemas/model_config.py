"""API contracts for model providers, model configurations, and live probes.

API keys are accepted as :class:`~pydantic.SecretStr` and never appear in a
model representation or serialized response.  Database-facing response models
only expose the pre-computed key mask.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.models.enums import ModelKind, UsageAccuracy, ValidationStatus


class ProviderKind(StrEnum):
    """Provider templates shipped with version 1.0."""

    OPENROUTER = "openrouter"
    AIHUBMIX = "aihubmix"
    TONGYI = "tongyi"


class UsageSource(StrEnum):
    """Where token usage in a connection result came from."""

    PROVIDER = "provider"
    LOCAL_ESTIMATE = "local_estimate"


class ProviderTemplate(BaseModel):
    """Public, secret-free defaults used to pre-fill the provider form."""

    model_config = ConfigDict(frozen=True)

    key: ProviderKind
    name: str
    default_base_url: str
    capabilities: tuple[ModelKind, ...]
    llm_path: str = "/chat/completions"
    embedding_path: str = "/embeddings"
    rerank_path: str
    documentation_url: str
    notes: str | None = None


def _normalize_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query string or fragment")
    return normalized


_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-goog-api-key",
        "cookie",
        "set-cookie",
    }
)


def _validate_non_secret_headers(headers: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = raw_name.strip()
        value = raw_value.strip()
        if not name or not value:
            raise ValueError("extra header names and values must not be blank")
        if name.casefold() in _SENSITIVE_HEADER_NAMES:
            raise ValueError(f"{name} must be supplied through the API key field")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise ValueError("extra headers must not contain newline characters")
        normalized[name] = value
    return normalized


class ModelProviderCreate(BaseModel):
    """Create or replace a provider connection."""

    key: ProviderKind
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    base_url: str | None = None
    api_key: SecretStr = Field(repr=False)
    default_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    _base_url = field_validator("base_url")(_normalize_base_url)
    _headers = field_validator("default_headers")(_validate_non_secret_headers)


class ModelProviderUpdate(BaseModel):
    """Mutable provider fields; a missing API key keeps the stored key."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)
    default_headers: dict[str, str] | None = None
    enabled: bool | None = None

    _base_url = field_validator("base_url")(_normalize_base_url)

    @field_validator("default_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _validate_non_secret_headers(value)


class ModelProviderRead(BaseModel):
    """Provider response with a mask in place of encrypted key material."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    api_style: str
    base_url: str
    api_key_mask: str | None
    default_headers: dict[str, Any]
    capabilities: dict[str, Any]
    is_builtin: bool
    enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ModelConfigCreate(BaseModel):
    """Register a concrete LLM, embedding, or rerank model."""

    provider_id: uuid.UUID
    kind: ModelKind
    name: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=255)
    description: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_config: dict[str, Any] = Field(default_factory=dict)
    embedding_dimension: int | None = Field(default=None, gt=0, le=16000)
    max_context_tokens: int | None = Field(default=None, gt=0)
    enabled: bool = True
    is_default: bool = False

    _base_url = field_validator("base_url")(_normalize_base_url)
    _headers = field_validator("extra_headers")(_validate_non_secret_headers)

    @model_validator(mode="after")
    def validate_embedding_dimension(self) -> ModelConfigCreate:
        if self.kind is not ModelKind.EMBEDDING and self.embedding_dimension is not None:
            raise ValueError("embedding_dimension is only valid for embedding models")
        return self


class ModelConfigUpdate(BaseModel):
    """Update model metadata; dimensions are guarded again by the service layer."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    model_id: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)
    extra_headers: dict[str, str] | None = None
    extra_config: dict[str, Any] | None = None
    embedding_dimension: int | None = Field(default=None, gt=0, le=16000)
    max_context_tokens: int | None = Field(default=None, gt=0)
    enabled: bool | None = None
    is_default: bool | None = None

    _base_url = field_validator("base_url")(_normalize_base_url)

    @field_validator("extra_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _validate_non_secret_headers(value)


class ModelConfigRead(BaseModel):
    """Secret-free model response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    kind: ModelKind
    name: str
    model_id: str
    description: str | None
    base_url: str | None
    api_key_mask: str | None
    extra_headers: dict[str, Any]
    extra_config: dict[str, Any]
    embedding_dimension: int | None
    max_context_tokens: int | None
    supports_streaming: bool
    supports_usage: bool
    enabled: bool
    is_default: bool
    validation_status: ValidationStatus
    validated_at: datetime | None
    validation_latency_ms: int | None
    validation_error: str | None
    total_requests: int
    created_at: datetime
    updated_at: datetime


class ModelConnectionTestRequest(BaseModel):
    """A one-request capability probe executed before a model is saved."""

    provider: ProviderKind
    kind: ModelKind
    model_id: str = Field(min_length=1, max_length=255)
    api_key: SecretStr = Field(repr=False)
    base_url: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    expected_dimensions: int | None = Field(default=None, gt=0, le=16000)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)

    _base_url = field_validator("base_url")(_normalize_base_url)
    _headers = field_validator("extra_headers")(_validate_non_secret_headers)

    @field_validator("model_id")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_id must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_expected_dimensions(self) -> ModelConnectionTestRequest:
        if self.kind is not ModelKind.EMBEDDING and self.expected_dimensions is not None:
            raise ValueError("expected_dimensions is only valid for embedding models")
        return self


class TokenUsage(BaseModel):
    """Normalized usage with an explicit precision/source marker."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    accuracy: UsageAccuracy
    source: UsageSource

    @model_validator(mode="after")
    def validate_source_matches_accuracy(self) -> TokenUsage:
        expected_source = (
            UsageSource.PROVIDER if self.accuracy is UsageAccuracy.EXACT else UsageSource.LOCAL_ESTIMATE
        )
        if self.accuracy is UsageAccuracy.UNAVAILABLE or self.source is not expected_source:
            raise ValueError("usage source and accuracy are inconsistent")
        return self


class ModelConnectionTestResult(BaseModel):
    """Normalized result returned by every provider adapter."""

    ok: bool
    provider: ProviderKind
    kind: ModelKind
    model_id: str
    returned_model: str | None = None
    latency_ms: int = Field(ge=0)
    dimensions: int | None = Field(default=None, gt=0)
    supports_streaming: bool = False
    usage: TokenUsage | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_success_shape(self) -> ModelConnectionTestResult:
        if self.ok and (self.error_code is not None or self.error_message is not None):
            raise ValueError("successful connection results cannot contain an error")
        if not self.ok and (not self.error_code or not self.error_message):
            raise ValueError("failed connection results require a safe error code and message")
        return self


# Small aliases keep route code readable while retaining explicit public names.
ConnectionTestRequest = ModelConnectionTestRequest
ConnectionTestResult = ModelConnectionTestResult
ModelType = Literal["llm", "embedding", "rerank"]
