"""Converge abandoned worker tasks to an actionable failed state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select

from app.core.config import get_settings
from app.db.session import AsyncSessionFactory
from app.models.enums import BuildStatus
from app.models.knowledge import BuildTask, DocumentVersion, KnowledgeBase
from app.services.knowledge_status import refresh_knowledge_base_summary

ACTIVE_WORKER_STATUSES = {
    BuildStatus.PARSING,
    BuildStatus.INDEXING,
    BuildStatus.REPLACING,
}


async def fail_stale_build_tasks() -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=get_settings().build_task_stale_minutes)
    queue_cutoff = datetime.now(UTC) - timedelta(minutes=get_settings().queued_task_timeout_minutes)
    async with AsyncSessionFactory() as session:
        condition = or_(
            and_(BuildTask.status.in_(ACTIVE_WORKER_STATUSES), BuildTask.updated_at < cutoff),
            and_(
                BuildTask.status == BuildStatus.QUEUED,
                or_(
                    BuildTask.current_step.is_(None),
                    BuildTask.current_step != "awaiting_data_egress_confirmation",
                ),
                BuildTask.updated_at < queue_cutoff,
            ),
            and_(
                BuildTask.status == BuildStatus.PREVIEW_READY,
                BuildTask.current_step == "queued_for_indexing",
                BuildTask.updated_at < queue_cutoff,
            ),
        )
        base_ids = list(
            (await session.scalars(select(BuildTask.knowledge_base_id).where(condition).distinct())).all()
        )
        if not base_ids:
            return 0
        await session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.id.in_(base_ids))
            .order_by(KnowledgeBase.id)
            .with_for_update()
        )
        tasks = (
            await session.scalars(
                select(BuildTask)
                .where(condition, BuildTask.knowledge_base_id.in_(base_ids))
                .with_for_update(skip_locked=True)
            )
        ).all()
        knowledge_base_ids = set()
        for task in tasks:
            task.status = BuildStatus.FAILED
            task.current_step = "failed"
            task.error_code = "worker_timeout"
            task.error_message = "后台任务未被及时处理，请检查 Worker 状态后重试。"
            task.finished_at = datetime.now(UTC)
            version = await session.get(DocumentVersion, task.document_version_id)
            if version and not version.is_active:
                version.status = BuildStatus.FAILED
            knowledge_base_ids.add(task.knowledge_base_id)
        for knowledge_base_id in knowledge_base_ids:
            await refresh_knowledge_base_summary(session, knowledge_base_id)
        await session.commit()
        return len(tasks)


def run_stale_build_recovery() -> int:
    return asyncio.run(fail_stale_build_tasks())
