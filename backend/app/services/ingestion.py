"""Background parsing pipeline; indexing is intentionally a separate stage."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionFactory
from app.models.enums import BuildStatus, KnowledgeBaseStatus, ParserKind
from app.models.knowledge import Document, DocumentVersion, KnowledgeBase
from app.services.build_lock import lock_build_task
from app.services.build_state import ensure_transition
from app.services.document_parsers import DocMindParser, LocalDocumentParser
from app.services.document_parsers.base import DocumentParseError
from app.services.knowledge_status import refresh_knowledge_base_summary
from app.services.object_storage import download_file, put_bytes
from app.services.system_settings import get_parser_settings


async def _mark_failed(
    session: AsyncSession,
    task_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    code: str,
    message: str,
) -> None:
    await session.rollback()
    task = await lock_build_task(session, task_id)
    version = await session.get(DocumentVersion, version_id)
    if task is None or version is None or task.status in {BuildStatus.CANCELLED, BuildStatus.READY}:
        return
    task.status = BuildStatus.FAILED
    task.current_step = "failed"
    task.error_code = code
    task.error_message = message
    version.status = BuildStatus.FAILED
    task.finished_at = datetime.now(UTC)
    await refresh_knowledge_base_summary(session, task.knowledge_base_id)
    await session.commit()


async def parse_document_version(task_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        task = await lock_build_task(session, task_id)
        if task is None or task.status is not BuildStatus.QUEUED:
            return
        version = await session.get(DocumentVersion, task.document_version_id)
        knowledge_base = await session.get(KnowledgeBase, task.knowledge_base_id)
        if version is None or knowledge_base is None:
            return
        document = await session.get(Document, version.document_id)
        if document is None or document.deleted_at is not None:
            return
        if task.cancel_requested:
            task.status = BuildStatus.CANCELLED
            version.status = BuildStatus.CANCELLED
            task.finished_at = datetime.now(UTC)
            await refresh_knowledge_base_summary(session, task.knowledge_base_id)
            await session.commit()
            return
        if version.needs_cloud_parse and not version.data_egress_confirmed:
            task.current_step = "awaiting_data_egress_confirmation"
            await session.commit()
            return
        ensure_transition(task.status, BuildStatus.PARSING)
        task.status = BuildStatus.PARSING
        task.attempt_count += 1
        task.started_at = task.started_at or datetime.now(UTC)
        task.progress = 10
        task.current_step = "downloading_original"
        version.status = BuildStatus.PARSING
        knowledge_base.status = KnowledgeBaseStatus.BUILDING
        await session.commit()

        suffix = Path(version.original_object_key).suffix
        version_id = version.id
        try:
            with tempfile.TemporaryDirectory(prefix="rag-parse-") as directory:
                local_path = Path(directory) / f"source{suffix}"
                await asyncio.to_thread(download_file, version.original_object_key, local_path)
                task = await lock_build_task(session, task_id)
                if task is None or task.status is not BuildStatus.PARSING:
                    return
                task.current_step = "parsing_document"
                task.progress = 25
                await session.commit()
                parser = (
                    DocMindParser(settings=await get_parser_settings(session))
                    if version.parser_kind is ParserKind.DOCMIND
                    else LocalDocumentParser()
                )
                result = await asyncio.to_thread(
                    parser.parse,
                    local_path,
                    filename=Path(version.original_object_key).name,
                )
                parsed_key = f"parsed/{version_id}.json"
            task = await lock_build_task(session, task_id)
            if task is None or task.status is not BuildStatus.PARSING:
                return
            if task.cancel_requested:
                task.status = BuildStatus.CANCELLED
                task.current_step = "cancelled"
                task.finished_at = datetime.now(UTC)
                version.status = BuildStatus.CANCELLED
                await refresh_knowledge_base_summary(session, task.knowledge_base_id)
                await session.commit()
                return
            await asyncio.to_thread(
                put_bytes,
                parsed_key,
                result.model_dump_json().encode("utf-8"),
                content_type="application/json",
            )
            ensure_transition(task.status, BuildStatus.PREVIEW_READY)
            task.status = BuildStatus.PREVIEW_READY
            task.progress = 60
            task.current_step = "preview_ready"
            version.status = BuildStatus.PREVIEW_READY
            version.parsed_object_key = parsed_key
            version.preview_settings = {
                key: value for key, value in (version.preview_settings or {}).items()
                if key != "_chunk_cache"
            }
            version.page_count = result.page_count
            version.parser_result = {
                "block_count": len(result.blocks),
                "warnings": result.warnings,
                **result.parser_metadata,
            }
            await session.commit()
        except DocumentParseError as exc:
            await _mark_failed(session, task_id, version_id, code=exc.code, message=exc.safe_message)
        except Exception:
            await _mark_failed(
                session,
                task_id,
                version_id,
                code="parse_internal_error",
                message="解析任务异常终止，原文件仍已保留，可稍后重试。",
            )


def run_parse_task(task_id: str) -> None:
    asyncio.run(parse_document_version(uuid.UUID(task_id)))
