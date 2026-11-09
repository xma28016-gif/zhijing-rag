"""Administrator-only management for external API credentials."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.api_key import ApiKey
from app.models.enums import ApiKeyStatus
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from app.services.api_keys import create_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])
AdminRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _read(record: ApiKey) -> ApiKeyRead:
    return ApiKeyRead(
        id=record.id,
        name=record.name,
        key_hint=record.key_hint,
        status=record.status,
        allow_all_assistants=record.allow_all_assistants,
        assistant_ids=[item.assistant_id for item in record.assistant_bindings],
        rate_limit_per_minute=record.rate_limit_per_minute,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(_: AdminRole, session: DbSession) -> list[ApiKeyRead]:
    records = (
        await session.scalars(
            select(ApiKey).options(selectinload(ApiKey.assistant_bindings)).order_by(ApiKey.created_at.desc())
        )
    ).all()
    return [_read(record) for record in records]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def issue_api_key(payload: ApiKeyCreate, _: AdminRole, session: DbSession) -> ApiKeyCreated:
    return await create_api_key(session, payload)


@router.post("/{api_key_id}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(api_key_id: uuid.UUID, _: AdminRole, session: DbSession) -> ApiKeyRead:
    record = await session.scalar(
        select(ApiKey).where(ApiKey.id == api_key_id).options(selectinload(ApiKey.assistant_bindings))
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "api_key_not_found", "message": "API Key 不存在。"}
        )
    record.status = ApiKeyStatus.REVOKED
    record.revoked_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(record)
    return _read(record)
