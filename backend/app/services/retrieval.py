"""Parallel semantic/keyword retrieval, RRF fusion, and optional reranking."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy import cast, func, select

from app.core.config import get_settings
from app.core.crypto import CredentialCipher
from app.db.session import AsyncSessionFactory
from app.models.knowledge import Document, DocumentVersion, KnowledgeChunk
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.knowledge import RetrievalHit, RetrievalTestResponse
from app.services.indexing import segment_for_search
from app.services.langchain_runtime import ConfiguredEmbeddings
from app.services.model_runtime import rerank_documents


@dataclass(slots=True)
class RankedChunk:
    hit: RetrievalHit
    source_score: float


def retrieval_content(chunk: KnowledgeChunk) -> str:
    metadata = chunk.source_metadata or {}
    parent = metadata.get("parent_content")
    return (
        parent if metadata.get("chunk_mode") == "parent_child" and isinstance(parent, str) else chunk.content
    )


def retrieval_parent_id(chunk: KnowledgeChunk) -> str | None:
    parent = (chunk.source_metadata or {}).get("parent_id")
    return f"{chunk.document_version_id}:{parent}" if parent else None


async def _semantic_search(
    knowledge_base_id: uuid.UUID, model_id: uuid.UUID, vector: list[float], limit: int
) -> list[RankedChunk]:
    dimension = len(vector)
    vector_type = Vector(dimension) if dimension <= 2_000 or dimension > 4_000 else HALFVEC(dimension)
    distance = cast(KnowledgeChunk.embedding, vector_type).cosine_distance(vector)
    statement = (
        select(
            KnowledgeChunk,
            (1 - distance).label("score"),
            Document.name,
            DocumentVersion.version_number,
        )
        .join(DocumentVersion, DocumentVersion.id == KnowledgeChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            KnowledgeChunk.knowledge_base_id == knowledge_base_id,
            KnowledgeChunk.embedding_model_config_id == model_id,
            KnowledgeChunk.is_active.is_(True),
            KnowledgeChunk.is_enabled.is_(True),
            KnowledgeChunk.embedding.is_not(None),
            DocumentVersion.is_active.is_(True),
            Document.deleted_at.is_(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    async with AsyncSessionFactory() as session:
        rows = (await session.execute(statement)).all()
    return [
        RankedChunk(
            hit=RetrievalHit(
                chunk_id=chunk.id,
                document_name=name,
                document_version=version,
                chunk_ordinal=chunk.ordinal,
                content=retrieval_content(chunk),
                parent_id=retrieval_parent_id(chunk),
                title_path=chunk.title_path,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range,
                semantic_score=float(score),
                rrf_score=0,
            ),
            source_score=float(score),
        )
        for chunk, score, name, version in rows
    ]


async def _keyword_search(knowledge_base_id: uuid.UUID, query: str, limit: int) -> list[RankedChunk]:
    tsquery = func.plainto_tsquery("simple", segment_for_search(query))
    score = func.ts_rank_cd(KnowledgeChunk.content_tsv, tsquery)
    statement = (
        select(KnowledgeChunk, score.label("score"), Document.name, DocumentVersion.version_number)
        .join(DocumentVersion, DocumentVersion.id == KnowledgeChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            KnowledgeChunk.knowledge_base_id == knowledge_base_id,
            KnowledgeChunk.is_active.is_(True),
            KnowledgeChunk.is_enabled.is_(True),
            KnowledgeChunk.content_tsv.op("@@")(tsquery),
            DocumentVersion.is_active.is_(True),
            Document.deleted_at.is_(None),
        )
        .order_by(score.desc())
        .limit(limit)
    )
    async with AsyncSessionFactory() as session:
        rows = (await session.execute(statement)).all()
    return [
        RankedChunk(
            hit=RetrievalHit(
                chunk_id=chunk.id,
                document_name=name,
                document_version=version,
                chunk_ordinal=chunk.ordinal,
                content=retrieval_content(chunk),
                parent_id=retrieval_parent_id(chunk),
                title_path=chunk.title_path,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range,
                keyword_score=float(raw_score),
                rrf_score=0,
            ),
            source_score=float(raw_score),
        )
        for chunk, raw_score, name, version in rows
    ]


def reciprocal_rank_fusion(
    semantic: list[RankedChunk],
    keyword: list[RankedChunk],
    *,
    k: int = 60,
    limit: int = 20,
) -> list[RetrievalHit]:
    by_id: dict[uuid.UUID, RetrievalHit] = {}
    scores: dict[uuid.UUID, float] = {}
    for results, source in ((semantic, "semantic"), (keyword, "keyword")):
        for rank, candidate in enumerate(results, start=1):
            chunk_id = candidate.hit.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank)
            if chunk_id not in by_id:
                by_id[chunk_id] = candidate.hit.model_copy(deep=True)
            elif source == "semantic":
                by_id[chunk_id].semantic_score = candidate.source_score
            else:
                by_id[chunk_id].keyword_score = candidate.source_score
    ordered = sorted(scores, key=scores.get, reverse=True)
    for chunk_id in ordered:
        by_id[chunk_id].rrf_score = scores[chunk_id]
    selected: list[RetrievalHit] = []
    parents: set[str] = set()
    for chunk_id in ordered:
        hit = by_id[chunk_id]
        if hit.parent_id and hit.parent_id in parents:
            continue
        if hit.parent_id:
            parents.add(hit.parent_id)
        selected.append(hit)
        if len(selected) >= limit:
            break
    return selected


async def retrieve_for_test(
    *,
    query: str,
    knowledge_base_id: uuid.UUID,
    embedding_model: ModelConfig,
    embedding_provider: ModelProvider,
    semantic_top_k: int,
    keyword_top_k: int,
    fusion_top_k: int,
    final_top_k: int,
    rerank_model: ModelConfig | None = None,
    rerank_provider: ModelProvider | None = None,
) -> RetrievalTestResponse:
    cipher = CredentialCipher(get_settings().master_key)
    started = time.perf_counter()
    vector = await ConfiguredEmbeddings(embedding_model, embedding_provider, cipher).aembed_query(query)
    embedding_ms = round((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    semantic, keyword = await asyncio.gather(
        _semantic_search(knowledge_base_id, embedding_model.id, vector, semantic_top_k),
        _keyword_search(knowledge_base_id, query, keyword_top_k),
    )
    fused = reciprocal_rank_fusion(semantic, keyword, limit=fusion_top_k)
    retrieval_ms = round((time.perf_counter() - started) * 1000)
    rerank_ms = 0
    if rerank_model and rerank_provider and fused:
        started = time.perf_counter()
        ranked = await rerank_documents(
            rerank_model,
            rerank_provider,
            query,
            [item.content for item in fused],
            cipher,
            top_n=min(final_top_k, len(fused)),
        )
        selected: list[RetrievalHit] = []
        for index, score in ranked:
            if 0 <= index < len(fused):
                fused[index].rerank_score = score
                selected.append(fused[index])
        fused = selected
        rerank_ms = round((time.perf_counter() - started) * 1000)
    else:
        fused = fused[:final_top_k]
    return RetrievalTestResponse(
        query=query,
        results=fused,
        embedding_ms=embedding_ms,
        retrieval_ms=retrieval_ms,
        rerank_ms=rerank_ms,
    )
