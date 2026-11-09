"""Shared preview generation and persisted snapshots for deterministic indexing."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.crypto import CredentialCipher
from app.models.enums import ModelKind, ValidationStatus
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.knowledge import ChunkMode, ChunkPreview, ChunkSettings, ParseResult
from app.schemas.model_config import ProviderKind
from app.services.document_parsers.base import DocumentParseError
from app.services.document_parsers.chunking import build_chunk_preview, semantic_units
from app.services.model_providers.templates import embedding_batch_limit
from app.services.model_runtime import embed_texts


def cached_preview(
    stored: dict[str, Any],
    settings: ChunkSettings,
    source: str,
) -> list[ChunkPreview] | None:
    cache = stored.get("_chunk_cache", {})
    if (
        cache.get("version") != 1
        or cache.get("source") != source
        or cache.get("settings") != settings.model_dump(mode="json")
    ):
        return None
    try:
        return [ChunkPreview.model_validate(item) for item in cache["chunks"]]
    except (ValidationError, KeyError, TypeError):
        return None


def preview_snapshot(
    settings: ChunkSettings,
    chunks: list[ChunkPreview],
    source: str,
) -> dict[str, Any]:
    values = settings.model_dump(mode="json")
    return {
        **values,
        "_chunk_cache": {
            "version": 1,
            "source": source,
            "settings": values,
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        },
    }


async def generate_preview(
    parsed: ParseResult,
    settings: ChunkSettings,
    *,
    model: ModelConfig | None = None,
    provider: ModelProvider | None = None,
    cipher: CredentialCipher | None = None,
) -> list[ChunkPreview]:
    if settings.mode is not ChunkMode.SEMANTIC:
        return build_chunk_preview(parsed, settings)
    units = semantic_units(parsed, settings)
    vectors: list[list[float]] = []
    if units:
        if (
            not model
            or not provider
            or not cipher
            or not model.enabled
            or not provider.enabled
            or model.kind is not ModelKind.EMBEDDING
            or not model.embedding_dimension
            or model.validation_status is not ValidationStatus.VALID
        ):
            raise DocumentParseError(
                "semantic_model_unavailable",
                "语义分块需要知识库绑定的 Embedding 模型已启用并验证通过。",
            )
        if len(units) > 4096:
            raise DocumentParseError(
                "semantic_document_too_large",
                "语义分块最多处理 4096 个句段，请拆分文件或改用智能分块。",
            )
        try:
            batch_size = embedding_batch_limit(ProviderKind(provider.key))
        except ValueError as exc:
            raise DocumentParseError(
                "semantic_provider_unsupported", "Embedding 服务商暂不支持语义分块。"
            ) from exc
        for offset in range(0, len(units), batch_size):
            vectors.extend(
                await embed_texts(
                    model,
                    provider,
                    [unit.content for unit in units[offset : offset + batch_size]],
                    cipher,
                )
            )
    return build_chunk_preview(parsed, settings, vectors=vectors)
