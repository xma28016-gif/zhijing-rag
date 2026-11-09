"""Generate, hash, authorize, and rate-limit external credentials."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.api_key import ApiKey, ApiKeyAssistant
from app.models.assistant import Assistant
from app.models.enums import ApiKeyStatus, AssistantStatus
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_api_key(session: AsyncSession, payload: ApiKeyCreate) -> ApiKeyCreated:
    now = datetime.now(UTC)
    if payload.expires_at and payload.expires_at <= now:
        raise HTTPException(
            status_code=422, detail={"code": "expiry_in_past", "message": "有效期必须晚于当前时间。"}
        )
    assistant_ids = set(payload.assistant_ids)
    if not payload.allow_all_assistants and not assistant_ids:
        raise HTTPException(
            status_code=422,
            detail={"code": "assistant_scope_required", "message": "请至少选择一个允许调用的助手。"},
        )
    if assistant_ids:
        existing = set(
            (
                await session.scalars(
                    select(Assistant.id).where(
                        Assistant.id.in_(assistant_ids), Assistant.status == AssistantStatus.ACTIVE
                    )
                )
            ).all()
        )
        if existing != assistant_ids:
            raise HTTPException(
                status_code=422,
                detail={"code": "assistant_scope_invalid", "message": "只能授权已发布的助手。"},
            )
    raw = f"rag_{secrets.token_urlsafe(32)}"
    record = ApiKey(
        name=payload.name,
        key_prefix=raw[:12],
        key_hash=hash_api_key(raw),
        key_hint=f"{raw[:8]}…{raw[-4:]}",
        allow_all_assistants=payload.allow_all_assistants,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        expires_at=payload.expires_at,
    )
    record.assistant_bindings = [ApiKeyAssistant(assistant_id=assistant_id) for assistant_id in assistant_ids]
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        key=raw,
        key_hint=record.key_hint,
        expires_at=record.expires_at,
        rate_limit_per_minute=record.rate_limit_per_minute,
    )


async def authenticate_api_key(session: AsyncSession, raw: str) -> ApiKey:
    record = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw)))
    now = datetime.now(UTC)
    if (
        not record
        or record.status is not ApiKeyStatus.ACTIVE
        or (record.expires_at and record.expires_at <= now)
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                    "message": "Invalid or expired API key.",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    record.last_used_at = now
    await session.commit()
    return record


async def enforce_rate_limit(record: ApiKey) -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    bucket = int(datetime.now(UTC).timestamp() // 60)
    key = f"rate-limit:api-key:{record.id}:{bucket}"
    try:
        async with redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, 120)
            count, _ = await pipeline.execute()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "type": "server_error",
                    "code": "rate_limiter_unavailable",
                    "message": "Rate limiter is temporarily unavailable.",
                }
            },
        ) from exc
    finally:
        await redis.aclose()
    if int(count) > record.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                    "message": "Rate limit exceeded.",
                }
            },
            headers={"Retry-After": "60"},
        )


async def api_key_can_use_assistant(session: AsyncSession, record: ApiKey, assistant_id: uuid.UUID) -> bool:
    if record.allow_all_assistants:
        return True
    return bool(
        await session.scalar(
            select(ApiKeyAssistant.id)
            .where(
                ApiKeyAssistant.api_key_id == record.id,
                ApiKeyAssistant.assistant_id == assistant_id,
            )
            .limit(1)
        )
    )
