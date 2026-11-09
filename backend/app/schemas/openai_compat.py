"""Subset of OpenAI Chat Completions accepted by external callers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[OpenAIMessage] = Field(min_length=1)
    stream: bool = False
    user: str | None = None
    # Accepted for SDK compatibility, but assistant-owned values always win.
    temperature: float | None = None
    max_tokens: int | None = None
