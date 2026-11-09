"""Read stored document versions without invoking a parser or model provider."""

import asyncio
from uuid import UUID

from fastapi import HTTPException
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ChunkKind, DocumentSourceType
from app.models.knowledge import Document, DocumentVersion, KnowledgeChunk
from app.schemas.knowledge import DocumentContentRead, DocumentSourceRead, ParseResult, StructuredBlock
from app.services.object_storage import get_bytes


async def document_version(
    session: AsyncSession, knowledge_base_id: UUID, document_id: UUID, version_number: int | None
) -> tuple[Document, DocumentVersion]:
    row = (
        await session.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(
                Document.id == document_id,
                Document.knowledge_base_id == knowledge_base_id,
                *([DocumentVersion.version_number == version_number] if version_number else []),
            )
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=404, detail={"code": "document_not_found", "message": "文件或对应版本不存在。"}
        )
    return row[0], row[1]


async def source_for_chunk(session: AsyncSession, chunk_id: UUID) -> DocumentSourceRead:
    row = (
        await session.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(KnowledgeChunk, KnowledgeChunk.document_version_id == DocumentVersion.id)
            .where(KnowledgeChunk.id == chunk_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "source_document_missing",
                "message": "来源文件已被移除，仍可查看日志中的引用快照。",
            },
        )
    document, version = row
    return DocumentSourceRead(
        knowledge_base_id=document.knowledge_base_id, document_id=document.id,
        document_name=document.name, version_number=version.version_number,
    )


async def read_document_content(
    session: AsyncSession, knowledge_base_id: UUID, document_id: UUID,
    version_number: int | None, offset: int, limit: int,
) -> DocumentContentRead:
    document, version = await document_version(session, knowledge_base_id, document_id, version_number)
    blocks: list[StructuredBlock] = []
    warnings: list[str] = []
    source = "unavailable"
    if version.parsed_object_key:
        try:
            raw_parsed = await asyncio.to_thread(get_bytes, version.parsed_object_key)
            parsed = ParseResult.model_validate_json(raw_parsed)
            blocks, warnings, source = parsed.blocks, parsed.warnings, "parsed"
        except (OSError, S3Error, ValueError):
            warnings.append("解析文件暂不可用，尝试展示已存储的分块内容。")
    if not blocks:
        chunks = list(await session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_version_id == version.id)
            .order_by(KnowledgeChunk.ordinal)
        ))
        if chunks:
            blocks = [StructuredBlock(
                ordinal=chunk.ordinal, kind=chunk.kind, content=chunk.content, title_path=chunk.title_path,
                page_from=chunk.page_from, page_to=chunk.page_to, sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range, object_key=chunk.object_key,
            ) for chunk in chunks]
            source = "chunks"
    if not blocks and document.source_type in {DocumentSourceType.MARKDOWN, DocumentSourceType.CSV}:
        try:
            raw = await asyncio.to_thread(get_bytes, version.original_object_key)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030", errors="replace")
            blocks = [
                StructuredBlock(ordinal=index // 4000, kind=ChunkKind.TEXT, content=text[index:index + 4000])
                for index in range(0, len(text), 4000)
            ]
            source = "original_text"
        except (OSError, S3Error):
            warnings.append("原文件暂不可用，请联系管理员检查文件存储。")
    if not blocks:
        warnings.append("暂无可展示的解析内容，可查看或下载原文件；未完成解析的文件请先完成构建。")
    return DocumentContentRead(
        knowledge_base_id=knowledge_base_id, document_id=document.id, document_name=document.name,
        version_number=version.version_number, source_type=document.source_type, mime_type=document.mime_type,
        status=version.status, deleted_at=document.deleted_at, size_bytes=version.size_bytes,
        page_count=version.page_count, content_source=source, blocks=blocks[offset:offset+limit],
        warnings=warnings, total=len(blocks), offset=offset, limit=limit,
    )


async def read_original(session: AsyncSession, kb_id: UUID, doc_id: UUID, version_number: int | None):
    document, version = await document_version(session, kb_id, doc_id, version_number)
    try:
        content = await asyncio.to_thread(get_bytes, version.original_object_key)
    except (OSError, S3Error) as exc:
        raise HTTPException(
            status_code=404, detail={"code": "original_file_missing", "message": "原文件暂不可用。"}
        ) from exc
    return document.name, content
