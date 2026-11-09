"""Contracts for manual case collection and annotation; no automatic evaluation."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("评测集名称不能为空。")
        return value.strip()


class DatasetRead(DatasetCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
    total_count: int = 0
    good_count: int = 0
    bad_count: int = 0
    draft_count: int = 0
    ready_count: int = 0
    archived_count: int = 0


class SampleCapture(BaseModel):
    source_run_id: UUID
    label: Literal["good", "bad"]
    scope: Literal["turn", "history"] = "turn"
    note: str = Field(default="", max_length=10000)


class SampleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_id: UUID
    source_run_id: UUID
    label: Literal["good", "bad"]
    scope: Literal["turn", "history"]
    state: Literal["draft", "ready", "archived"]
    question: str
    answer: str
    note: str
    reference_answer: str
    rubric: str
    ready_confirmed: bool
    revision: int
    created_at: datetime
    updated_at: datetime


class SampleDetail(SampleSummary):
    snapshot: dict[str, Any]
    source_available: bool


class SamplePage(BaseModel):
    items: list[SampleSummary]
    total: int


class CaptureResult(BaseModel):
    sample: SampleSummary
    already_exists: bool


class SampleUpdate(BaseModel):
    revision: int = Field(ge=1)
    label: Literal["good", "bad"]
    state: Literal["draft", "ready", "archived"]
    note: str = Field(max_length=10000)
    reference_answer: str = Field(max_length=100000)
    rubric: str = Field(max_length=10000)
    ready_confirmed: bool

    @model_validator(mode="after")
    def validate_ready(self):
        if self.state == "ready" and (
            not self.ready_confirmed or not (self.reference_answer.strip() or self.rubric.strip())
        ):
            raise ValueError("标为可评测前，请填写参考答案或判定标准，并确认已检查。")
        return self
