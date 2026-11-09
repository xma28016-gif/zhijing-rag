"""External API key contracts; raw keys are returned exactly once."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ApiKeyStatus


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    assistant_ids: list[UUID] = Field(default_factory=list)
    allow_all_assistants: bool = False
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def normalize_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ApiKeyCreated(BaseModel):
    id: UUID
    name: str
    key: str
    key_hint: str
    expires_at: datetime | None
    rate_limit_per_minute: int


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    key_hint: str
    status: ApiKeyStatus
    allow_all_assistants: bool
    assistant_ids: list[UUID]
    rate_limit_per_minute: int
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
