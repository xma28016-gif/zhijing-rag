import uuid

import pytest

from app.schemas.knowledge import RetrievalHit
from app.services.retrieval import RankedChunk, reciprocal_rank_fusion


def hit(chunk_id: uuid.UUID, content: str, score: float, source: str) -> RankedChunk:
    return RankedChunk(
        hit=RetrievalHit(
            chunk_id=chunk_id,
            document_name="guide.md",
            document_version=1,
            chunk_ordinal=0,
            content=content,
            title_path=[],
            page_from=None,
            page_to=None,
            sheet_name=None,
            cell_range=None,
            semantic_score=score if source == "semantic" else None,
            keyword_score=score if source == "keyword" else None,
            rrf_score=0,
        ),
        source_score=score,
    )


def test_rrf_rewards_chunks_returned_by_both_retrievers() -> None:
    shared = uuid.uuid4()
    semantic_only = uuid.uuid4()
    keyword_only = uuid.uuid4()
    results = reciprocal_rank_fusion(
        [hit(semantic_only, "semantic", 0.9, "semantic"), hit(shared, "shared", 0.8, "semantic")],
        [hit(keyword_only, "keyword", 0.9, "keyword"), hit(shared, "shared", 0.8, "keyword")],
    )
    assert results[0].chunk_id == shared
    assert results[0].semantic_score == pytest.approx(0.8)
    assert results[0].keyword_score == pytest.approx(0.8)


def test_rrf_limit_is_applied_after_fusion() -> None:
    semantic = [hit(uuid.uuid4(), str(index), 1 - index / 10, "semantic") for index in range(5)]
    assert len(reciprocal_rank_fusion(semantic, [], limit=2)) == 2
