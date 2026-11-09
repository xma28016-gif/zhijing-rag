"""Run log and daily metric response contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import RunChannel, RunStatus, RunStepKind, UsageAccuracy


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_id: str
    conversation_id: UUID | None
    assistant_id: UUID
    api_key_id: UUID | None
    channel: RunChannel
    status: RunStatus
    query_text: str
    rewritten_query: str | None
    answer_text: str | None
    evidence_sufficient: bool | None
    retrieved_chunk_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_accuracy: UsageAccuracy
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class RunStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: RunStepKind
    sequence: int
    status: RunStatus
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    input_tokens: int
    output_tokens: int
    duration_ms: int | None
    error_code: str | None
    error_message: str | None


class RunDetail(RunRead):
    citations: list[dict[str, Any]]
    retrieval_results: list[dict[str, Any]]
    config_snapshot: dict[str, Any]
    steps: list[RunStepRead]


class DailyMetricRead(BaseModel):
    metric_date: date
    channel: str
    request_count: int
    success_count: int
    error_count: int
    insufficient_evidence_count: int
    total_tokens: int
    total_duration_ms: int
    max_duration_ms: int
