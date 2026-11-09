"""Delete a knowledge base and its owned records and stored files."""

import asyncio
import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import Assistant, AssistantKnowledgeBase
from app.models.knowledge import Document, DocumentVersion, KnowledgeBase
from app.services.object_storage import remove_object

logger = logging.getLogger(__name__)


async def delete_knowledge_base(session: AsyncSession, knowledge_base_id: UUID) -> bool:
    """Return whether all stored files were cleaned after the database commit."""
    record = await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id).with_for_update()
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    assistants = list(
        await session.scalars(
            select(Assistant.name)
            .join(AssistantKnowledgeBase, AssistantKnowledgeBase.assistant_id == Assistant.id)
            .where(AssistantKnowledgeBase.knowledge_base_id == knowledge_base_id)
            .order_by(Assistant.name)
        )
    )
    if assistants:
        names = "、".join(assistants[:3]) + ("等" if len(assistants) > 3 else "")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "knowledge_base_in_use",
                "message": f"该知识库被助手“{names}”引用，请先在助手设置中解除绑定，再删除。",
            },
        )
    versions = (
        await session.execute(
            select(DocumentVersion.id, DocumentVersion.original_object_key, DocumentVersion.parsed_object_key)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.knowledge_base_id == knowledge_base_id)
        )
    ).all()
    keys = {
        key
        for version in versions
        for key in (version.original_object_key, version.parsed_object_key, f"parsed/{version.id}.json")
        if key
    }
    # Database foreign keys cascade to documents, versions, chunks and build tasks.
    # Historical conversation citations are snapshots and remain available.
    await session.execute(delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id))
    await session.commit()

    def clean_files() -> bool:
        complete = True
        for key in keys:
            try:
                remove_object(key)
            except Exception:
                complete = False
                logger.exception("knowledge_base_file_cleanup_failed", extra={"object_key": key})
        return complete

    return await asyncio.to_thread(clean_files)
