"""Anonymous browser conversation and grounded chat contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BrowserSessionRead(BaseModel):
    id: UUID
    token: str
    expires_at: datetime


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    conversation_id: UUID | None = None


class CitationRead(BaseModel):
    index: int
    chunk_id: UUID
    document_name: str
    document_version: int
    chunk_ordinal: int
    location: str
    excerpt: str
    score: float


class ConversationRead(BaseModel):
    id: UUID
    assistant_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    id: UUID
    role: str
    sequence: int
    content: str
    citations: list[dict]
    usage: dict
    created_at: datetime
