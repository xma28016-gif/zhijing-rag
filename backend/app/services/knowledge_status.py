"""Keep knowledge-base counters and summary state aligned with build tasks."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BuildStatus, KnowledgeBaseStatus
from app.models.knowledge import BuildTask, Document, DocumentVersion, KnowledgeBase, KnowledgeChunk

OPEN_BUILD_STATUSES = {
    BuildStatus.QUEUED,
    BuildStatus.PARSING,
    BuildStatus.PREVIEW_READY,
    BuildStatus.INDEXING,
    BuildStatus.REPLACING,
}


async def refresh_knowledge_base_summary(
    session: AsyncSession, knowledge_base_id: uuid.UUID
) -> KnowledgeBaseStatus | None:
    # Serialize writers before flushing task/version changes, so deletion and
    # workers share the same KB -> task/version lock order.
    knowledge_base = await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id).with_for_update()
    )
    if knowledge_base is None:
        return None
    await session.flush()

    active_documents = int(
        await session.scalar(
            select(func.count(Document.id)).where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.current_content_sha256.is_not(None),
                Document.deleted_at.is_(None),
            )
        )
        or 0
    )
    active_chunks = int(
        await session.scalar(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeChunk.is_active.is_(True),
            )
        )
        or 0
    )
    open_tasks = int(
        await session.scalar(
            select(func.count(BuildTask.id)).where(
                BuildTask.document_version_id.in_(
                    select(DocumentVersion.id).join(Document).where(Document.deleted_at.is_(None))
                ),
                BuildTask.knowledge_base_id == knowledge_base_id,
                BuildTask.status.in_(OPEN_BUILD_STATUSES),
            )
        )
        or 0
    )
    failed_tasks = int(
        await session.scalar(
            select(func.count(BuildTask.id)).where(
                BuildTask.document_version_id.in_(
                    select(DocumentVersion.id).join(Document).where(Document.deleted_at.is_(None))
                ),
                BuildTask.knowledge_base_id == knowledge_base_id,
                BuildTask.status == BuildStatus.FAILED,
            )
        )
        or 0
    )

    knowledge_base.document_count = active_documents
    knowledge_base.chunk_count = active_chunks
    if open_tasks:
        knowledge_base.status = KnowledgeBaseStatus.BUILDING
    elif active_documents:
        knowledge_base.status = KnowledgeBaseStatus.READY
    elif failed_tasks:
        knowledge_base.status = KnowledgeBaseStatus.FAILED
    else:
        knowledge_base.status = KnowledgeBaseStatus.EMPTY
    return knowledge_base.status
