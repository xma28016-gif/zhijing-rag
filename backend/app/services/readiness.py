"""Dependency checks used by the readiness endpoint."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import engine
from app.services.object_storage import storage_ready

_backend_dir = Path(__file__).resolve().parents[2]
_migration_config = Config(str(_backend_dir / "alembic.ini"))
_migration_config.set_main_option("script_location", str(_backend_dir / "alembic"))
SCHEMA_REVISION = ScriptDirectory.from_config(_migration_config).get_current_head()


async def database_ready() -> bool:
    async with engine.connect() as connection:
        version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        return version == SCHEMA_REVISION and bool(
            await connection.scalar(text("SELECT to_regclass('knowledge_chunks') IS NOT NULL"))
        )


def redis_ready(settings: Settings):
    async def check() -> bool:
        client = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()

    return check


def minio_ready(settings: Settings):
    async def check() -> bool:
        return await asyncio.to_thread(storage_ready, settings)

    return check


def worker_ready(settings: Settings):
    async def check() -> bool:
        client = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        try:
            async for key in client.scan_iter("rag:worker:*"):
                value = await client.get(key)
                if value and time.time() - float(value) < 60:
                    return True
            return False
        finally:
            await client.aclose()

    return check
