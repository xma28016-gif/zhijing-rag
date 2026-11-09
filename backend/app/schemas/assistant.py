"""Assistant configuration contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssistantStatus, ModelKind


class AssistantKnowledgeBaseInput(BaseModel):
    knowledge_base_id: UUID
    priority: int = Field(default=0, ge=0)
    enabled: bool = True


class AssistantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    alias: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,99}$")
    description: str | None = None
    status: AssistantStatus = AssistantStatus.DRAFT
    llm_model_config_id: UUID
    rerank_model_config_id: UUID | None = None
    system_prompt: str = ""
    insufficient_evidence_message: str = "当前知识库未找到足够依据"
    enable_query_rewrite: bool = True
    semantic_top_k: int = Field(default=30, ge=1, le=100)
    keyword_top_k: int = Field(default=30, ge=1, le=100)
    rerank_top_k: int = Field(default=20, ge=1, le=100)
    answer_top_k: int = Field(default=6, ge=1, le=20)
    max_context_tokens: int = Field(default=6_000, ge=500, le=32_000)
    relevance_threshold: float = Field(default=0.5, ge=0, le=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=2_048, ge=1, le=32_000)
    knowledge_bases: list[AssistantKnowledgeBaseInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_retrieval_counts(self) -> AssistantCreate:
        if self.answer_top_k > self.rerank_top_k:
            raise ValueError("answer_top_k cannot exceed rerank_top_k")
        ids = [item.knowledge_base_id for item in self.knowledge_bases]
        if len(ids) != len(set(ids)):
            raise ValueError("knowledge bases cannot be bound more than once")
        return self


class AssistantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    status: AssistantStatus | None = None
    llm_model_config_id: UUID | None = None
    rerank_model_config_id: UUID | None = None
    system_prompt: str | None = None
    insufficient_evidence_message: str | None = None
    enable_query_rewrite: bool | None = None
    semantic_top_k: int | None = Field(default=None, ge=1, le=100)
    keyword_top_k: int | None = Field(default=None, ge=1, le=100)
    rerank_top_k: int | None = Field(default=None, ge=1, le=100)
    answer_top_k: int | None = Field(default=None, ge=1, le=20)
    max_context_tokens: int | None = Field(default=None, ge=500, le=32_000)
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_000)
    knowledge_bases: list[AssistantKnowledgeBaseInput] | None = None


class AssistantKnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    knowledge_base_id: UUID
    priority: int
    enabled: bool
    knowledge_base_name: str


class AssistantModelOption(BaseModel):
    id: UUID
    kind: ModelKind
    name: str
    model_id: str
    provider_name: str
    is_default: bool


class AssistantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    alias: str
    description: str | None
    status: AssistantStatus
    llm_model_config_id: UUID
    llm_model_name: str
    rerank_model_config_id: UUID | None
    rerank_model_name: str | None
    system_prompt: str
    insufficient_evidence_message: str
    enable_query_rewrite: bool
    semantic_top_k: int
    keyword_top_k: int
    rerank_top_k: int
    answer_top_k: int
    max_context_tokens: int
    relevance_threshold: float
    temperature: float
    max_output_tokens: int
    knowledge_bases: list[AssistantKnowledgeBaseRead]
    created_at: datetime
    updated_at: datetime
