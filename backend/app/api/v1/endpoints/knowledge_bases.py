"""Knowledge-base creation, upload routing, parsing jobs, and previews."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.crypto import CredentialCipher
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.enums import (
    BuildStatus,
    BuildTaskType,
    DocumentSourceType,
    KnowledgeBaseStatus,
    ModelKind,
    ParserKind,
    ValidationStatus,
)
from app.models.knowledge import BuildTask, Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.knowledge import (
    BuildTaskDetailRead,
    BuildTaskRead,
    ChunkListResponse,
    ChunkPreview,
    ChunkPreviewResponse,
    ChunkRead,
    ChunkSettings,
    DocumentContentRead,
    DocumentRead,
    DocumentSourceRead,
    EmbeddingModelOption,
    FileDisposition,
    ImportBatchRead,
    ImportItemRead,
    KnowledgeBaseCreate,
    KnowledgeBaseDeleteRead,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    ParseResult,
    ParseRoute,
    RerankModelOption,
    RetrievalTestRequest,
    RetrievalTestResponse,
)
from app.services.build_state import ensure_transition
from app.services.chunk_previews import cached_preview, generate_preview, preview_snapshot
from app.services.document_content import read_document_content, read_original, source_for_chunk
from app.services.document_lifecycle import change_document_deleted, require_document_available
from app.services.document_parsers import build_chunk_preview, determine_parse_route
from app.services.document_parsers.base import DocumentParseError
from app.services.document_parsers.chunking import chunking_warnings
from app.services.knowledge_base_lifecycle import delete_knowledge_base
from app.services.knowledge_status import refresh_knowledge_base_summary
from app.services.model_runtime import ProviderCallError
from app.services.object_storage import get_bytes, put_bytes, remove_object
from app.services.retrieval import retrieve_for_test
from app.services.system_settings import docmind_is_configured, get_system_settings
from app.worker import index_document, parse_document

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
logger = logging.getLogger(__name__)
ManagerRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN, ExperienceRole.MANAGER))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

DOCMIND_CONFIGURATION_MESSAGE = (
    "云端增强解析尚未配置 DocMind AccessKey。请在“系统设置 → 云端 OCR”填写凭据；"
    "普通文本 Word、Excel 和电子 PDF 可关闭云端增强，使用本地解析。"
)


async def require_docmind_configuration(session: AsyncSession) -> None:
    if not await docmind_is_configured(session):
        raise HTTPException(
            status_code=409,
            detail={"code": "docmind_not_configured", "message": DOCMIND_CONFIGURATION_MESSAGE},
        )


def _source_type(extension: str) -> DocumentSourceType:
    return {
        ".doc": DocumentSourceType.WORD,
        ".docx": DocumentSourceType.WORD,
        ".pdf": DocumentSourceType.PDF,
        ".md": DocumentSourceType.MARKDOWN,
        ".markdown": DocumentSourceType.MARKDOWN,
        ".csv": DocumentSourceType.CSV,
        ".xls": DocumentSourceType.SPREADSHEET,
        ".xlsx": DocumentSourceType.SPREADSHEET,
        ".png": DocumentSourceType.IMAGE,
        ".jpg": DocumentSourceType.IMAGE,
        ".jpeg": DocumentSourceType.IMAGE,
        ".webp": DocumentSourceType.IMAGE,
        ".bmp": DocumentSourceType.IMAGE,
        ".tif": DocumentSourceType.IMAGE,
        ".tiff": DocumentSourceType.IMAGE,
    }.get(extension, DocumentSourceType.OTHER)


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(_: ManagerRole, session: DbSession) -> list[KnowledgeBaseRead]:
    records = await session.scalars(select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc()))
    return [KnowledgeBaseRead.model_validate(record) for record in records]


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    knowledge_base_id: uuid.UUID, payload: KnowledgeBaseUpdate, _: ManagerRole, session: DbSession
) -> KnowledgeBaseRead:
    record = await session.get(KnowledgeBase, knowledge_base_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    values = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None or key == "description"
    }
    name = values.get("name")
    if name and await session.scalar(
        select(KnowledgeBase.id).where(KnowledgeBase.name == name, KnowledgeBase.id != record.id)
    ):
        raise HTTPException(
            status_code=409, detail={"code": "knowledge_base_name_exists", "message": "知识库名称已存在。"}
        )
    if values.get("chunk_overlap_tokens", record.chunk_overlap_tokens) >= values.get(
        "chunk_target_tokens", record.chunk_target_tokens
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_chunk_settings", "message": "重叠长度必须小于分块长度。"},
        )
    for key, value in values.items():
        setattr(record, key, value)
    await session.commit()
    await session.refresh(record)
    return KnowledgeBaseRead.model_validate(record)


@router.delete("/{knowledge_base_id}", response_model=KnowledgeBaseDeleteRead)
async def remove_knowledge_base(
    knowledge_base_id: uuid.UUID, _: ManagerRole, session: DbSession
) -> KnowledgeBaseDeleteRead:
    complete = await delete_knowledge_base(session, knowledge_base_id)
    return KnowledgeBaseDeleteRead(storage_cleanup_complete=complete)


@router.get("/embedding-model-options", response_model=list[EmbeddingModelOption])
async def embedding_model_options(_: ManagerRole, session: DbSession) -> list[EmbeddingModelOption]:
    rows = (
        await session.execute(
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.kind == ModelKind.EMBEDDING,
                ModelConfig.enabled.is_(True),
                ModelConfig.embedding_dimension.is_not(None),
                ModelConfig.validation_status == ValidationStatus.VALID,
                ModelProvider.enabled.is_(True),
            )
            .order_by(ModelConfig.is_default.desc(), ModelConfig.name)
        )
    ).all()
    return [
        EmbeddingModelOption(
            id=model.id,
            name=model.name,
            model_id=model.model_id,
            provider_name=provider.name,
            embedding_dimension=int(model.embedding_dimension or 0),
            is_default=model.is_default,
        )
        for model, provider in rows
    ]


@router.get("/rerank-model-options", response_model=list[RerankModelOption])
async def rerank_model_options(_: ManagerRole, session: DbSession) -> list[RerankModelOption]:
    rows = (
        await session.execute(
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.kind == ModelKind.RERANK,
                ModelConfig.enabled.is_(True),
                ModelConfig.validation_status == ValidationStatus.VALID,
                ModelProvider.enabled.is_(True),
            )
            .order_by(ModelConfig.is_default.desc(), ModelConfig.name)
        )
    ).all()
    return [
        RerankModelOption(
            id=model.id,
            name=model.name,
            model_id=model.model_id,
            provider_name=provider.name,
            is_default=model.is_default,
        )
        for model, provider in rows
    ]


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate, _: ManagerRole, session: DbSession
) -> KnowledgeBaseRead:
    model = await session.get(ModelConfig, payload.embedding_model_config_id)
    if (
        model is None
        or model.kind is not ModelKind.EMBEDDING
        or not model.enabled
        or model.validation_status is not ValidationStatus.VALID
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_embedding_model",
                "message": "请选择已启用且连通性验证成功的 Embedding 模型。",
            },
        )
    if await session.scalar(select(KnowledgeBase.id).where(KnowledgeBase.name == payload.name)):
        raise HTTPException(
            status_code=409, detail={"code": "knowledge_base_name_exists", "message": "知识库名称已存在。"}
        )
    system_settings = await get_system_settings(session)
    knowledge_base = KnowledgeBase(
        **payload.model_dump(exclude={"knowledge_base_type"}),
        settings={"knowledge_base_type": payload.knowledge_base_type},
        embedding_dimension=model.embedding_dimension,
        file_size_limit_bytes=system_settings.file_size_limit_bytes,
        page_limit=system_settings.page_limit,
        batch_file_limit=system_settings.batch_file_limit,
    )
    session.add(knowledge_base)
    await session.commit()
    await session.refresh(knowledge_base)
    return KnowledgeBaseRead.model_validate(knowledge_base)


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=413,
                detail={"code": "file_too_large", "message": "文件超过当前知识库的大小限制。"},
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _mark_dispatch_failed(
    session: AsyncSession,
    task: BuildTask,
    version: DocumentVersion,
    *,
    action: str,
) -> None:
    await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == task.knowledge_base_id).with_for_update()
    )
    await session.refresh(task, with_for_update=True)
    if task.status in {BuildStatus.CANCELLED, BuildStatus.READY}:
        return
    ensure_transition(task.status, BuildStatus.FAILED)
    task.status = BuildStatus.FAILED
    task.current_step = "failed"
    task.error_code = "task_queue_unavailable"
    task.error_message = f"后台任务队列暂时不可用，{action}未启动，可安全重试。"
    task.finished_at = datetime.now(UTC)
    if not version.is_active:
        version.status = BuildStatus.FAILED
    await refresh_knowledge_base_summary(session, task.knowledge_base_id)
    await session.commit()


@router.post("/{knowledge_base_id}/imports", response_model=ImportBatchRead)
async def import_documents(
    knowledge_base_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    files: Annotated[list[UploadFile], File()],
    confirm_data_egress: Annotated[bool, Form()] = False,
    enhanced: Annotated[bool, Form()] = False,
) -> ImportBatchRead:
    knowledge_base = await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id).with_for_update()
    )
    if knowledge_base is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    if not files or len(files) > knowledge_base.batch_file_limit:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "batch_file_limit",
                "message": f"单批最多上传 {knowledge_base.batch_file_limit} 个文件。",
            },
        )
    results: list[ImportItemRead] = []
    dispatch_ids: list[uuid.UUID] = []
    uploaded_keys: list[str] = []
    try:
        for upload in files:
            filename = Path(upload.filename or "").name.strip()
            content = await _read_upload(upload, knowledge_base.file_size_limit_bytes)
            digest = hashlib.sha256(content).hexdigest()
            if knowledge_base.knowledge_base_type == "table" and Path(filename).suffix.lower() not in {
                ".csv",
                ".xls",
                ".xlsx",
            }:
                route = ParseRoute(
                    disposition=FileDisposition.REJECT,
                    parser_kind=None,
                    detected_extension=Path(filename).suffix.lower(),
                    reason_code="table_file_required",
                    reason_message="表格知识库仅支持 Excel / CSV 文件，请选择 .xlsx、.xls 或 .csv。",
                )
            else:
                route = await asyncio.to_thread(
                    determine_parse_route,
                    filename,
                    content,
                    max_size_bytes=knowledge_base.file_size_limit_bytes,
                    max_pages=knowledge_base.page_limit,
                    enhanced=enhanced,
                )
            if route.disposition is FileDisposition.CLOUD and not await docmind_is_configured(session):
                route = route.model_copy(update={
                    "disposition": FileDisposition.REJECT,
                    "parser_kind": None,
                    "data_egress_required": False,
                    "reason_code": "docmind_not_configured",
                    "reason_message": DOCMIND_CONFIGURATION_MESSAGE,
                })
            if route.disposition is FileDisposition.REJECT:
                results.append(
                    ImportItemRead(
                        filename=filename,
                        accepted=False,
                        route=route,
                        content_sha256=digest,
                        message=route.reason_message,
                    )
                )
                continue
            duplicate = await session.scalar(
                select(DocumentVersion.id)
                .join(Document)
                .where(
                    Document.knowledge_base_id == knowledge_base.id,
                    Document.deleted_at.is_(None),
                    DocumentVersion.content_sha256 == digest,
                )
                .limit(1)
            )
            if duplicate:
                results.append(
                    ImportItemRead(
                        filename=filename,
                        accepted=False,
                        route=route,
                        content_sha256=digest,
                        message="相同内容已存在，未重复导入。",
                    )
                )
                continue
            document = await session.scalar(
                select(Document).where(
                    Document.knowledge_base_id == knowledge_base.id,
                    Document.name == filename,
                    Document.deleted_at.is_(None),
                )
            )
            replacing = document is not None
            if document is None:
                document = Document(
                    id=uuid.uuid4(),
                    knowledge_base_id=knowledge_base.id,
                    name=filename,
                    source_type=_source_type(route.detected_extension),
                    current_content_sha256=None,
                    mime_type=upload.content_type,
                )
                session.add(document)
                version_number = 1
            else:
                current_max = await session.scalar(
                    select(func.max(DocumentVersion.version_number)).where(
                        DocumentVersion.document_id == document.id
                    )
                )
                version_number = int(current_max or 0) + 1
            version_id = uuid.uuid4()
            object_key = f"original/{knowledge_base.id}/{version_id}/{filename}"
            await asyncio.to_thread(
                put_bytes,
                object_key,
                content,
                content_type=upload.content_type or "application/octet-stream",
            )
            uploaded_keys.append(object_key)
            cloud = route.parser_kind is ParserKind.DOCMIND
            version = DocumentVersion(
                id=version_id,
                document_id=document.id,
                version_number=version_number,
                content_sha256=digest,
                size_bytes=len(content),
                original_object_key=object_key,
                parser_kind=route.parser_kind,
                status=BuildStatus.QUEUED,
                needs_cloud_parse=cloud,
                data_egress_confirmed=bool(confirm_data_egress) if cloud else False,
            )
            task = BuildTask(
                id=uuid.uuid4(),
                knowledge_base_id=knowledge_base.id,
                document_version_id=version.id,
                task_type=BuildTaskType.REPLACE if replacing else BuildTaskType.IMPORT,
                status=BuildStatus.QUEUED,
                current_step=(
                    "queued" if not cloud or confirm_data_egress else "awaiting_data_egress_confirmation"
                ),
            )
            session.add_all([version, task])
            knowledge_base.status = KnowledgeBaseStatus.BUILDING
            if not cloud or confirm_data_egress:
                dispatch_ids.append(task.id)
            results.append(
                ImportItemRead(
                    filename=filename,
                    accepted=True,
                    document_id=document.id,
                    document_version_id=version.id,
                    build_task_id=task.id,
                    route=route,
                    content_sha256=digest,
                    status=BuildStatus.QUEUED,
                    message=("已进入解析队列" if task.id in dispatch_ids else "等待确认数据出网"),
                )
            )
            await session.flush()  # Make same-batch deduplication/version lookup observe preceding files.
        await session.commit()
    except Exception:
        await session.rollback()
        for object_key in uploaded_keys:
            try:
                await asyncio.to_thread(remove_object, object_key)
            except Exception:
                logger.warning("orphan_object_cleanup_failed", extra={"object_key": object_key})
        raise
    for task_id in dispatch_ids:
        try:
            parse_document.delay(str(task_id))
        except Exception:
            logger.exception("parse_task_dispatch_failed", extra={"task_id": str(task_id)})
            task = await session.get(BuildTask, task_id)
            version = await session.get(DocumentVersion, task.document_version_id) if task else None
            if task and version:
                await _mark_dispatch_failed(session, task, version, action="解析")
                for item in results:
                    if item.build_task_id == task_id:
                        item.status = BuildStatus.FAILED
                        item.message = task.error_message or "解析任务未启动。"
    return ImportBatchRead(items=results)


@router.get("/{knowledge_base_id}/documents", response_model=list[DocumentRead])
async def list_documents(
    knowledge_base_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    deleted: bool = False,
) -> list[DocumentRead]:
    if await session.get(KnowledgeBase, knowledge_base_id) is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    documents = (
        await session.scalars(
            select(Document)
            .where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.deleted_at.is_not(None) if deleted else Document.deleted_at.is_(None),
            )
            .order_by(Document.updated_at.desc())
        )
    ).all()
    response: list[DocumentRead] = []
    for document in documents:
        latest = await session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        if latest is None:
            continue
        latest_task = await session.scalar(
            select(BuildTask)
            .where(BuildTask.document_version_id == latest.id)
            .order_by(BuildTask.created_at.desc())
            .limit(1)
        )
        response.append(
            DocumentRead(
                id=document.id,
                name=document.name,
                source_type=document.source_type,
                mime_type=document.mime_type,
                current_content_sha256=document.current_content_sha256,
                latest_version_id=latest.id,
                latest_version_number=latest.version_number,
                latest_status=latest.status,
                parser_kind=latest.parser_kind,
                size_bytes=latest.size_bytes,
                page_count=latest.page_count,
                is_active=latest.is_active,
                latest_task_id=latest_task.id if latest_task else None,
                error_code=latest_task.error_code if latest_task else None,
                error_message=latest_task.error_message if latest_task else None,
                created_at=document.created_at,
                updated_at=document.updated_at,
                deleted_at=document.deleted_at,
            )
        )
    return response


@router.delete("/{knowledge_base_id}/documents/{document_id}", status_code=204)
async def delete_document(
    knowledge_base_id: uuid.UUID, document_id: uuid.UUID, _: ManagerRole, session: DbSession
) -> Response:
    await change_document_deleted(session, knowledge_base_id, document_id, deleted=True)
    return Response(status_code=204)


@router.post("/{knowledge_base_id}/documents/{document_id}/restore", status_code=204)
async def restore_document(
    knowledge_base_id: uuid.UUID, document_id: uuid.UUID, _: ManagerRole, session: DbSession
) -> Response:
    await change_document_deleted(session, knowledge_base_id, document_id, deleted=False)
    return Response(status_code=204)


@router.get("/chunks/{chunk_id}/source", response_model=DocumentSourceRead)
async def chunk_source(chunk_id: uuid.UUID, _: ManagerRole, session: DbSession) -> DocumentSourceRead:
    return await source_for_chunk(session, chunk_id)


@router.get("/{knowledge_base_id}/documents/{document_id}/content", response_model=DocumentContentRead)
async def document_content(
    knowledge_base_id: uuid.UUID,
    document_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    version_number: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DocumentContentRead:
    return await read_document_content(session, knowledge_base_id, document_id, version_number, offset, limit)


@router.get("/{knowledge_base_id}/documents/{document_id}/original")
async def document_original(
    knowledge_base_id: uuid.UUID,
    document_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    version_number: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    name, content = await read_original(session, knowledge_base_id, document_id, version_number)
    suffix = Path(name).suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(suffix, "application/octet-stream")
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/{knowledge_base_id}/chunks", response_model=ChunkListResponse)
async def list_chunks(
    knowledge_base_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    query: Annotated[str | None, Query(max_length=500)] = None,
) -> ChunkListResponse:
    if await session.get(KnowledgeBase, knowledge_base_id) is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    filters = [
        KnowledgeChunk.knowledge_base_id == knowledge_base_id,
        KnowledgeChunk.is_active.is_(True),
    ]
    if query:
        filters.append(KnowledgeChunk.content.ilike(f"%{query.strip()}%"))
    total = int(await session.scalar(select(func.count(KnowledgeChunk.id)).where(*filters)) or 0)
    rows = (
        await session.execute(
            select(KnowledgeChunk, DocumentVersion, Document)
            .join(DocumentVersion, DocumentVersion.id == KnowledgeChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(*filters)
            .order_by(Document.name, KnowledgeChunk.ordinal)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return ChunkListResponse(
        items=[
            ChunkRead(
                id=chunk.id,
                document_version_id=version.id,
                document_name=document.name,
                document_version=version.version_number,
                ordinal=chunk.ordinal,
                kind=chunk.kind,
                content=chunk.content,
                title_path=chunk.title_path,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range,
                token_count=chunk.token_count,
                char_count=chunk.char_count,
                is_enabled=chunk.is_enabled,
            )
            for chunk, version, document in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{knowledge_base_id}/build-tasks", response_model=list[BuildTaskDetailRead])
async def list_build_tasks(
    knowledge_base_id: uuid.UUID, _: ManagerRole, session: DbSession
) -> list[BuildTaskDetailRead]:
    if await session.get(KnowledgeBase, knowledge_base_id) is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    rows = (
        await session.execute(
            select(BuildTask, DocumentVersion, Document)
            .join(DocumentVersion, DocumentVersion.id == BuildTask.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(BuildTask.knowledge_base_id == knowledge_base_id, Document.deleted_at.is_(None))
            .order_by(BuildTask.created_at.desc())
        )
    ).all()
    return [
        BuildTaskDetailRead(
            **BuildTaskRead.model_validate(task).model_dump(),
            task_type=task.task_type,
            document_name=document.name,
            document_version=version.version_number,
            parser_kind=version.parser_kind,
            attempt_count=task.attempt_count,
            max_attempts=task.max_attempts,
            cancel_requested=task.cancel_requested,
            started_at=task.started_at,
            finished_at=task.finished_at,
            chunk_settings=ChunkSettings.model_validate(version.preview_settings or {}),
        )
        for task, version, document in rows
    ]


@router.post("/build-tasks/{task_id}/confirm-data-egress", response_model=BuildTaskRead)
async def confirm_data_egress(task_id: uuid.UUID, _: ManagerRole, session: DbSession) -> BuildTaskRead:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "build_task_not_found", "message": "任务不存在。"},
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    await require_document_available(session, version)
    if version is None or not version.needs_cloud_parse:
        raise HTTPException(
            status_code=409, detail={"code": "data_egress_not_required", "message": "该文件不需要云端解析。"}
        )
    if version.data_egress_confirmed:
        return BuildTaskRead.model_validate(task)
    await require_docmind_configuration(session)
    version.data_egress_confirmed = True
    task.current_step = "queued"
    await session.commit()
    try:
        parse_document.delay(str(task.id))
    except Exception:
        logger.exception("parse_task_dispatch_failed", extra={"task_id": str(task.id)})
        await _mark_dispatch_failed(session, task, version, action="云端解析")
    await session.refresh(task)
    return BuildTaskRead.model_validate(task)


@router.get("/build-tasks/{task_id}", response_model=BuildTaskRead)
async def get_build_task(task_id: uuid.UUID, _: ManagerRole, session: DbSession) -> BuildTaskRead:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "build_task_not_found", "message": "任务不存在。"},
        )
    return BuildTaskRead.model_validate(task)


@router.post("/build-tasks/{task_id}/cancel", response_model=BuildTaskRead)
async def cancel_build_task(task_id: uuid.UUID, _: ManagerRole, session: DbSession) -> BuildTaskRead:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail={"code": "build_task_not_found", "message": "任务不存在。"}
        )
    if task.status in {BuildStatus.READY, BuildStatus.FAILED, BuildStatus.CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "build_task_not_cancellable",
                "message": "当前任务已结束，无需取消。",
            },
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    task.cancel_requested = True
    if task.status in {BuildStatus.QUEUED, BuildStatus.PREVIEW_READY}:
        ensure_transition(task.status, BuildStatus.CANCELLED)
        task.status = BuildStatus.CANCELLED
        task.current_step = "cancelled"
        task.finished_at = datetime.now(UTC)
        if version:
            version.status = BuildStatus.CANCELLED
        await refresh_knowledge_base_summary(session, task.knowledge_base_id)
    else:
        task.current_step = "cancellation_requested"
    await session.commit()
    await session.refresh(task)
    return BuildTaskRead.model_validate(task)


@router.post("/build-tasks/{task_id}/retry", response_model=BuildTaskRead)
async def retry_build_task(
    task_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    local_parse: Annotated[bool, Query()] = False,
) -> BuildTaskRead:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail={"code": "build_task_not_found", "message": "任务不存在。"}
        )
    if task.status not in {BuildStatus.FAILED, BuildStatus.CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "build_task_not_retryable",
                "message": "只有失败或已取消的任务可以重试。",
            },
        )
    if task.attempt_count >= task.max_attempts:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "build_task_attempts_exhausted",
                "message": "已达最大尝试次数，请检查错误原因后重新导入。",
            },
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    await require_document_available(session, version)
    if version is None:
        raise HTTPException(
            status_code=409, detail={"code": "document_version_missing", "message": "文档版本不存在。"}
        )
    if local_parse:
        content = await asyncio.to_thread(get_bytes, version.original_object_key)
        route = await asyncio.to_thread(
            determine_parse_route, Path(version.original_object_key).name, content, enhanced=False,
        )
        if route.parser_kind is not ParserKind.LOCAL:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "local_parse_unavailable",
                    "message": (
                        "该文件无法完整本地解析，请配置 DocMind 后重试云端解析，"
                        "以免遗漏图片或扫描内容。"
                    ),
                },
            )
        version.parser_kind = ParserKind.LOCAL
        version.needs_cloud_parse = False
        version.data_egress_confirmed = False
    elif version.needs_cloud_parse:
        await require_docmind_configuration(session)
    ensure_transition(task.status, BuildStatus.QUEUED)
    task.status = BuildStatus.QUEUED
    task.progress = 0
    task.current_step = (
        "queued"
        if not version.needs_cloud_parse or version.data_egress_confirmed
        else "awaiting_data_egress_confirmation"
    )
    task.cancel_requested = False
    task.error_code = None
    task.error_message = None
    task.error_details = {}
    task.started_at = None
    task.finished_at = None
    version.status = BuildStatus.QUEUED
    await refresh_knowledge_base_summary(session, task.knowledge_base_id)
    await session.commit()
    if not version.needs_cloud_parse or version.data_egress_confirmed:
        try:
            parse_document.delay(str(task.id))
        except Exception:
            logger.exception("parse_task_dispatch_failed", extra={"task_id": str(task.id)})
            await _mark_dispatch_failed(session, task, version, action="重试解析")
    await session.refresh(task)
    return BuildTaskRead.model_validate(task)


@router.get("/build-tasks/{task_id}/preview", response_model=ChunkPreviewResponse)
async def preview_build_task(
    task_id: uuid.UUID,
    _: ManagerRole,
    session: DbSession,
    target_tokens: Annotated[int, Query(ge=100, le=4_000)] = 800,
    overlap_tokens: Annotated[int, Query(ge=0, le=1_000)] = 120,
) -> ChunkPreviewResponse:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "build_task_not_found", "message": "任务不存在。"},
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    await require_document_available(session, version)
    if task.status is not BuildStatus.PREVIEW_READY or not version or not version.parsed_object_key:
        raise HTTPException(
            status_code=409, detail={"code": "preview_not_ready", "message": "解析尚未完成，请稍后重试。"}
        )
    if overlap_tokens >= target_tokens:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_chunk_settings",
                "message": "重叠长度必须小于分块长度。",
            },
        )
    settings = ChunkSettings(target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    parsed = ParseResult.model_validate_json(await asyncio.to_thread(get_bytes, version.parsed_object_key))
    chunks = build_chunk_preview(parsed, settings)
    return ChunkPreviewResponse(
        task=BuildTaskRead.model_validate(task),
        settings=settings,
        chunks=chunks,
        warnings=parsed.warnings,
    )


async def _configured_preview(
    session: AsyncSession,
    task: BuildTask,
    version: DocumentVersion,
    settings: ChunkSettings,
) -> tuple[list[ChunkPreview], ParseResult]:
    if not version.parsed_object_key:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "preview_not_ready",
                "message": "解析结果尚未就绪。",
            },
        )
    parsed = ParseResult.model_validate_json(await asyncio.to_thread(get_bytes, version.parsed_object_key))
    chunks = cached_preview(version.preview_settings or {}, settings, version.parsed_object_key)
    if chunks is None:
        kb = await session.get(KnowledgeBase, task.knowledge_base_id)
        model = await session.get(ModelConfig, kb.embedding_model_config_id) if kb else None
        provider = await session.get(ModelProvider, model.provider_id) if model else None
        try:
            chunks = await generate_preview(
                parsed,
                settings,
                model=model,
                provider=provider,
                cipher=CredentialCipher(get_settings().master_key),
            )
        except (DocumentParseError, ProviderCallError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": exc.code,
                    "message": exc.safe_message,
                },
            ) from exc
    if not chunks:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "empty_document",
                "message": "没有可构建的正文内容，请检查文档和分块配置。",
            },
        )
    version.preview_settings = preview_snapshot(settings, chunks, version.parsed_object_key)
    return chunks, parsed


@router.put("/build-tasks/{task_id}/chunk-settings", response_model=ChunkSettings)
async def save_chunk_settings(
    task_id: uuid.UUID,
    settings: ChunkSettings,
    _: ManagerRole,
    session: DbSession,
) -> ChunkSettings:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail={"code": "build_task_not_found", "message": "任务不存在。"}
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    await require_document_available(session, version)
    if (
        task.status not in {BuildStatus.QUEUED, BuildStatus.PARSING, BuildStatus.PREVIEW_READY}
        or task.current_step == "queued_for_indexing"
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "chunk_settings_locked", "message": "任务已开始构建，无法修改分块配置。"},
        )
    if ChunkSettings.model_validate(version.preview_settings or {}) != settings:
        version.preview_settings = settings.model_dump(mode="json")
    elif not version.preview_settings:
        version.preview_settings = settings.model_dump(mode="json")
    await session.commit()
    return settings


@router.post("/build-tasks/{task_id}/preview", response_model=ChunkPreviewResponse)
async def preview_configured_task(
    task_id: uuid.UUID,
    settings: ChunkSettings,
    _: ManagerRole,
    session: DbSession,
) -> ChunkPreviewResponse:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail={"code": "build_task_not_found", "message": "任务不存在。"}
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    await require_document_available(session, version)
    if task.status is not BuildStatus.PREVIEW_READY or not version or not version.parsed_object_key:
        raise HTTPException(
            status_code=409, detail={"code": "preview_not_ready", "message": "解析尚未完成。"}
        )
    if task.current_step == "queued_for_indexing":
        raise HTTPException(
            status_code=409, detail={"code": "build_already_queued", "message": "任务已进入构建队列。"}
        )
    chunks, parsed = await _configured_preview(session, task, version, settings)
    await session.commit()
    warnings = chunking_warnings(parsed, settings)
    if any(chunk.token_count > settings.target_tokens for chunk in chunks):
        warnings.append("部分完整页、问答或表格行超过目标长度，已保留完整内容，请检查预览。")
    return ChunkPreviewResponse(
        task=BuildTaskRead.model_validate(task),
        settings=settings,
        chunks=chunks,
        warnings=warnings,
    )


@router.post("/build-tasks/{task_id}/build", response_model=BuildTaskRead)
async def start_build(
    task_id: uuid.UUID, settings: ChunkSettings, _: ManagerRole, session: DbSession
) -> BuildTaskRead:
    task = await session.get(BuildTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "build_task_not_found", "message": "任务不存在。"},
        )
    await require_document_available(session, await session.get(DocumentVersion, task.document_version_id))
    await session.refresh(task, with_for_update=True)
    if task.status is not BuildStatus.PREVIEW_READY:
        raise HTTPException(
            status_code=409,
            detail={"code": "build_not_ready", "message": "请等待解析完成并检查预览后再开始构建。"},
        )
    if task.current_step == "queued_for_indexing":
        raise HTTPException(
            status_code=409,
            detail={"code": "build_already_queued", "message": "任务已进入构建队列，请等待后台处理。"},
        )
    version = await session.get(DocumentVersion, task.document_version_id)
    if version is None:
        raise HTTPException(
            status_code=409, detail={"code": "document_version_missing", "message": "文档版本不存在。"}
        )
    await _configured_preview(session, task, version, settings)
    task.current_step = "queued_for_indexing"
    await session.commit()
    try:
        index_document.delay(str(task.id))
    except Exception:
        logger.exception("index_task_dispatch_failed", extra={"task_id": str(task.id)})
        await _mark_dispatch_failed(session, task, version, action="索引构建")
    await session.refresh(task)
    return BuildTaskRead.model_validate(task)


@router.post("/{knowledge_base_id}/retrieval-test", response_model=RetrievalTestResponse)
async def retrieval_test(
    knowledge_base_id: uuid.UUID,
    payload: RetrievalTestRequest,
    _: ManagerRole,
    session: DbSession,
) -> RetrievalTestResponse:
    knowledge_base = await session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(
            status_code=404, detail={"code": "knowledge_base_not_found", "message": "知识库不存在。"}
        )
    embedding_model = await session.get(ModelConfig, knowledge_base.embedding_model_config_id)
    embedding_provider = (
        await session.get(ModelProvider, embedding_model.provider_id) if embedding_model else None
    )
    if not embedding_model or not embedding_provider:
        raise HTTPException(
            status_code=409,
            detail={"code": "embedding_model_unavailable", "message": "知识库的 Embedding 模型不可用。"},
        )
    rerank_model = None
    rerank_provider = None
    if payload.rerank_model_config_id:
        rerank_model = await session.get(ModelConfig, payload.rerank_model_config_id)
        if not rerank_model or rerank_model.kind is not ModelKind.RERANK:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_rerank_model", "message": "请选择有效的 Rerank 模型。"},
            )
        rerank_provider = await session.get(ModelProvider, rerank_model.provider_id)
    return await retrieve_for_test(
        query=payload.query,
        knowledge_base_id=knowledge_base.id,
        embedding_model=embedding_model,
        embedding_provider=embedding_provider,
        semantic_top_k=payload.semantic_top_k,
        keyword_top_k=payload.keyword_top_k,
        fusion_top_k=payload.fusion_top_k,
        final_top_k=payload.final_top_k,
        rerank_model=rerank_model,
        rerank_provider=rerank_provider,
    )
