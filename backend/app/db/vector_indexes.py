"""DDL helpers for pgvector indexes whose dimension is known at runtime.

An unbounded ``vector`` column can hold embeddings from several model spaces, but
pgvector requires a fixed dimension on an ANN expression index. The model service
calls these helpers after it validates an embedding model's dimension.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

MIN_VECTOR_DIMENSION = 1
MAX_VECTOR_DIMENSION = 16_000


def embedding_hnsw_index_name(model_config_id: UUID, dimension: int) -> str:
    """Return a deterministic, identifier-safe index name."""

    _validate_dimension(dimension)
    return f"ix_chunks_hnsw_v2_{model_config_id.hex}_{dimension}"


async def create_embedding_hnsw_index(
    bind: AsyncConnection | AsyncSession,
    *,
    model_config_id: UUID,
    dimension: int,
    m: int = 16,
    ef_construction: int = 64,
) -> str:
    """Create the partial cosine HNSW index for one embedding space.

    Values embedded in the DDL are validated integers/UUIDs rather than arbitrary
    user input. ``CREATE INDEX CONCURRENTLY`` is intentionally not used here: the
    caller may be inside an application transaction, while concurrent DDL must run
    in PostgreSQL autocommit mode.
    """

    _validate_dimension(dimension)
    if dimension > 4_000:
        return ""  # Higher dimensions remain available through exact retrieval.
    if not 2 <= m <= 100:
        raise ValueError("HNSW m must be between 2 and 100")
    if not 4 <= ef_construction <= 1_000:
        raise ValueError("HNSW ef_construction must be between 4 and 1000")

    index_name = embedding_hnsw_index_name(model_config_id, dimension)
    vector_type = "vector" if dimension <= 2_000 else "halfvec"
    statement = text(
        f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON knowledge_chunks
        USING hnsw ((embedding::{vector_type}({dimension})) {vector_type}_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction})
        WHERE embedding_model_config_id = '{model_config_id}'::uuid
          AND embedding IS NOT NULL
          AND is_active IS TRUE
          AND is_enabled IS TRUE
        """
    )
    await bind.execute(statement)
    return index_name


async def drop_embedding_hnsw_index(
    bind: AsyncConnection | AsyncSession,
    *,
    model_config_id: UUID,
    dimension: int,
) -> str:
    """Drop the ANN index for an embedding space, if it exists."""

    index_name = embedding_hnsw_index_name(model_config_id, dimension)
    await bind.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    return index_name


def _validate_dimension(dimension: int) -> None:
    if not MIN_VECTOR_DIMENSION <= dimension <= MAX_VECTOR_DIMENSION:
        raise ValueError(
            f"embedding dimension must be between {MIN_VECTOR_DIMENSION} and {MAX_VECTOR_DIMENSION}"
        )
