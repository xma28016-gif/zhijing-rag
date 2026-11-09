"""Serialize worker writes with document and knowledge-base deletion."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import BuildTask, KnowledgeBase


async def lock_build_task(session: AsyncSession, task_id: UUID) -> BuildTask | None:
    parent = await session.scalar(
        select(KnowledgeBase.id)
        .join(BuildTask, BuildTask.knowledge_base_id == KnowledgeBase.id)
        .where(BuildTask.id == task_id)
        .with_for_update(of=KnowledgeBase)
    )
    if parent is None:
        return None
    return await session.scalar(
        select(BuildTask)
        .where(BuildTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
