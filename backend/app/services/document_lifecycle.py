"""Reversible removal of knowledge documents and their retrieval indexes."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BuildStatus
from app.models.knowledge import BuildTask, Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.services.knowledge_status import OPEN_BUILD_STATUSES, refresh_knowledge_base_summary


async def require_document_available(session: AsyncSession, version: DocumentVersion | None) -> Document:
    document = await session.get(Document, version.document_id) if version else None
    if document:
        await session.scalar(
            select(KnowledgeBase).where(KnowledgeBase.id == document.knowledge_base_id).with_for_update()
        )
        await session.refresh(document)
    if document is None or document.deleted_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_deleted",
                "message": "文档已删除，请先在“已删除”列表恢复。",
            },
        )
    return document


async def change_document_deleted(
    session: AsyncSession,
    knowledge_base_id: UUID,
    document_id: UUID,
    *,
    deleted: bool,
) -> None:
    knowledge_base = await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id).with_for_update()
    )
    document = await session.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.knowledge_base_id == knowledge_base_id,
        )
        .with_for_update()
    )
    if knowledge_base is None or document is None:
        raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "文档不存在。"})
    if (document.deleted_at is not None) == deleted:
        return
    versions = select(DocumentVersion.id).where(DocumentVersion.document_id == document.id)
    if deleted:
        document.deleted_at = datetime.now(UTC)
        await session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.document_version_id.in_(versions))
            .values(is_active=False)
        )
        await session.execute(
            update(DocumentVersion).where(DocumentVersion.document_id == document.id).values(is_active=False)
        )
        await session.execute(
            update(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.status.in_(OPEN_BUILD_STATUSES),
            )
            .values(status=BuildStatus.CANCELLED)
        )
        await session.execute(
            update(BuildTask)
            .where(
                BuildTask.document_version_id.in_(versions),
                BuildTask.status.in_(OPEN_BUILD_STATUSES),
            )
            .values(
                status=BuildStatus.CANCELLED,
                cancel_requested=True,
                current_step="document_deleted",
                error_code="document_deleted",
                error_message="文档已删除，任务已取消。",
                finished_at=datetime.now(UTC),
            )
        )
    else:
        latest_ready = await session.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.status == BuildStatus.READY,
            )
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        duplicate_condition = Document.name == document.name
        if latest_ready:
            duplicate_condition = or_(
                duplicate_condition, DocumentVersion.content_sha256 == latest_ready.content_sha256
            )
        conflict = await session.scalar(
            select(Document.id)
            .join(DocumentVersion)
            .where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.id != document.id,
                Document.deleted_at.is_(None),
                duplicate_condition,
            )
            .limit(1)
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "document_restore_conflict",
                    "message": "同名或相同内容的文件已重新导入，无法重复恢复。",
                },
            )
        document.deleted_at = None
        if latest_ready:
            latest_ready.is_active = True
            document.current_content_sha256 = latest_ready.content_sha256
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.document_version_id == latest_ready.id)
                .values(is_active=True)
            )
    await refresh_knowledge_base_summary(session, knowledge_base_id)
    await session.commit()
