"""Async SQLAlchemy engine and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Celery tasks create independent asyncio loops. Connections must not leak
    # from a closed task loop into the next invocation in the same worker.
    poolclass=NullPool,
    connect_args={"connect_timeout": 5} if settings.database_url.startswith("postgresql") else {},
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one transaction-neutral session for a FastAPI request.

    Services own their transaction boundary explicitly. An uncommitted transaction
    is rolled back when the request leaves this dependency.
    """

    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close pooled connections during application shutdown."""

    await engine.dispose()
