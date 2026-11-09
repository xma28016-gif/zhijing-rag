"""Embedding and atomic activation of a parsed document version."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

import jieba
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.crypto import CredentialCipher
from app.db.session import AsyncSessionFactory
from app.db.vector_indexes import create_embedding_hnsw_index
from app.models.enums import BuildStatus
from app.models.knowledge import Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.knowledge import ChunkSettings, ParseResult
from app.schemas.model_config import ProviderKind
from app.services.build_lock import lock_build_task
from app.services.build_state import ensure_transition
from app.services.chunk_previews import cached_preview
from app.services.document_parsers import build_chunk_preview
from app.services.knowledge_status import refresh_knowledge_base_summary
from app.services.langchain_runtime import ConfiguredEmbeddings
from app.services.model_providers.templates import embedding_batch_limit
from app.services.model_runtime import ProviderCallError
from app.services.object_storage import get_bytes


def segment_for_search(text: str) -> str:
    return " ".join(token.strip() for token in jieba.cut_for_search(text) if token.strip())


async def _fail(task_id: uuid.UUID, version_id: uuid.UUID, code: str, message: str) -> None:
    async with AsyncSessionFactory() as session:
        task = await lock_build_task(session, task_id)
        version = await session.get(DocumentVersion, version_id)
        if task and task.status in {BuildStatus.READY, BuildStatus.CANCELLED}:
            return
        if task:
            task.status = BuildStatus.FAILED
            task.current_step = "failed"
            task.error_code = code
            task.error_message = message
            task.finished_at = datetime.now(UTC)
        if version:
            version.status = BuildStatus.FAILED
        if task:
            await refresh_knowledge_base_summary(session, task.knowledge_base_id)
        await session.commit()


async def index_document_version(task_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        task = await lock_build_task(session, task_id)
        if task is None or task.status is not BuildStatus.PREVIEW_READY:
            return
        version = await session.get(DocumentVersion, task.document_version_id)
        knowledge_base = await session.get(KnowledgeBase, task.knowledge_base_id)
        if not version or not knowledge_base or not version.parsed_object_key:
            return
        document = await session.get(Document, version.document_id)
        model = await session.get(ModelConfig, knowledge_base.embedding_model_config_id)
        provider = await session.get(ModelProvider, model.provider_id) if model else None
        if document and document.deleted_at is not None:
            return
        if not document or not model or not provider or not model.embedding_dimension:
            invalid_version_id = version.id
            await session.rollback()
            await _fail(
                task_id,
                invalid_version_id,
                "embedding_model_invalid",
                "Embedding 模型未通过维度验证，无法构建索引。",
            )
            return
        has_active = bool(
            await session.scalar(
                select(DocumentVersion.id)
                .where(DocumentVersion.document_id == document.id, DocumentVersion.is_active.is_(True))
                .limit(1)
            )
        )
        target = BuildStatus.REPLACING if has_active else BuildStatus.INDEXING
        ensure_transition(task.status, target)
        task.status = target
        task.current_step = "embedding"
        task.progress = 65
        version.status = target
        await session.commit()
        version_id = version.id
        parsed_key = version.parsed_object_key
        settings = ChunkSettings.model_validate(version.preview_settings or {})
        stored_settings = dict(version.preview_settings or {})

    try:
        parsed = ParseResult.model_validate_json(await asyncio.to_thread(get_bytes, parsed_key))
        previews = cached_preview(stored_settings, settings, parsed_key)
        if previews is None:
            previews = build_chunk_preview(parsed, settings)
        if not previews:
            raise ProviderCallError("empty_document", "解析结果没有可构建的正文内容。")
        cipher = CredentialCipher(get_settings().master_key)
        vectors: list[list[float]] = []
        try:
            provider_kind = ProviderKind(provider.key)
        except ValueError as exc:
            raise ProviderCallError("provider_unsupported", "暂不支持该模型供应商。") from exc
        batch_limit = embedding_batch_limit(provider_kind)
        for offset in range(0, len(previews), batch_limit):
            async with AsyncSessionFactory() as progress_session:
                running = await lock_build_task(progress_session, task_id)
                if running is None:
                    return
                if running.status in {BuildStatus.FAILED, BuildStatus.CANCELLED, BuildStatus.READY}:
                    return
                if running.cancel_requested:
                    running.status = BuildStatus.CANCELLED
                    running.current_step = "cancelled"
                    running.finished_at = datetime.now(UTC)
                    current_version = await progress_session.get(DocumentVersion, version_id)
                    if current_version:
                        current_version.status = BuildStatus.CANCELLED
                    await refresh_knowledge_base_summary(progress_session, running.knowledge_base_id)
                    await progress_session.commit()
                    return
                running.progress = 65 + round(15 * offset / len(previews))
                running.current_step = f"embedding:{offset}/{len(previews)}"
                await progress_session.commit()
            batch = previews[offset : offset + batch_limit]
            vectors.extend(
                await ConfiguredEmbeddings(model, provider, cipher).aembed_documents(
                    [item.content for item in batch]
                )
            )

        async with AsyncSessionFactory() as session:
            task = await lock_build_task(session, task_id)
            version = await session.get(DocumentVersion, version_id)
            knowledge_base = (
                await session.scalar(
                    select(KnowledgeBase).where(KnowledgeBase.id == task.knowledge_base_id).with_for_update()
                )
                if task
                else None
            )
            document = (
                await session.scalar(
                    select(Document).where(Document.id == version.document_id).with_for_update()
                )
                if version
                else None
            )
            if not task or not version or not knowledge_base or not document:
                return
            if task.status not in {BuildStatus.INDEXING, BuildStatus.REPLACING}:
                return
            newer_active = await session.scalar(
                select(DocumentVersion.id)
                .where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version_number > version.version_number,
                    DocumentVersion.is_active.is_(True),
                )
                .limit(1)
            )
            if task.cancel_requested or document.deleted_at is not None or newer_active:
                task.status = BuildStatus.CANCELLED
                task.current_step = "superseded" if newer_active else "cancelled"
                task.error_message = "更新版本已就绪，本次构建已取消。" if newer_active else None
                task.finished_at = datetime.now(UTC)
                version.status = BuildStatus.CANCELLED
                await refresh_knowledge_base_summary(session, task.knowledge_base_id)
                await session.commit()
                return
            if task.status is BuildStatus.REPLACING:
                ensure_transition(task.status, BuildStatus.INDEXING)
                task.status = BuildStatus.INDEXING
                version.status = BuildStatus.INDEXING
            task.current_step = "writing_index"
            task.progress = 85
            for preview, vector in zip(previews, vectors, strict=True):
                segmented = segment_for_search(preview.content)
                session.add(
                    KnowledgeChunk(
                        knowledge_base_id=knowledge_base.id,
                        document_version_id=version.id,
                        embedding_model_config_id=model.id,
                        ordinal=preview.ordinal,
                        kind=preview.kind,
                        content=preview.content,
                        content_tsv=func.to_tsvector("simple", segmented),
                        content_sha256=hashlib.sha256(preview.content.encode()).hexdigest(),
                        title_path=preview.title_path,
                        page_from=preview.page_from,
                        page_to=preview.page_to,
                        sheet_name=preview.sheet_name,
                        cell_range=preview.cell_range,
                        object_key=preview.object_key,
                        source_metadata=preview.metadata,
                        token_count=preview.token_count,
                        char_count=preview.char_count,
                        embedding=vector,
                        is_active=False,
                        embedding_created_at=datetime.now(UTC),
                    )
                )
            await session.flush()
            await create_embedding_hnsw_index(
                session, model_config_id=model.id, dimension=model.embedding_dimension
            )
            old_version_ids = list(
                (
                    await session.scalars(
                        select(DocumentVersion.id).where(
                            DocumentVersion.document_id == document.id,
                            DocumentVersion.id != version.id,
                            DocumentVersion.is_active.is_(True),
                        )
                    )
                ).all()
            )
            if old_version_ids:
                await session.execute(
                    update(KnowledgeChunk)
                    .where(KnowledgeChunk.document_version_id.in_(old_version_ids))
                    .values(is_active=False)
                )
                await session.execute(
                    update(DocumentVersion)
                    .where(DocumentVersion.id.in_(old_version_ids))
                    .values(is_active=False)
                )
                await session.flush()
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.document_version_id == version.id)
                .values(is_active=True)
            )
            version.is_active = True
            version.status = BuildStatus.READY
            version.activated_at = datetime.now(UTC)
            document.current_content_sha256 = version.content_sha256
            task.status = BuildStatus.READY
            task.progress = 100
            task.current_step = "ready"
            task.finished_at = datetime.now(UTC)
            await session.flush()
            await refresh_knowledge_base_summary(session, knowledge_base.id)
            await session.commit()
    except ProviderCallError as exc:
        await _fail(task_id, version_id, exc.code, exc.safe_message)
    except Exception:
        await _fail(
            task_id,
            version_id,
            "index_internal_error",
            "索引构建异常终止，旧版本仍可使用，可稍后重试。",
        )


def run_index_task(task_id: str) -> None:
    asyncio.run(index_document_version(uuid.UUID(task_id)))
