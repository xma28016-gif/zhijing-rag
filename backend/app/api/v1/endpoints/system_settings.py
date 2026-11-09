"""Administrator-managed runtime defaults shared with workers."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.crypto import CredentialCipher, mask_secret
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.knowledge import KnowledgeBase
from app.schemas.system import SystemSettingsRead, SystemSettingsUpdate
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/system-settings", tags=["system-settings"])
AdminRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
logger = logging.getLogger(__name__)


@router.get("", response_model=SystemSettingsRead)
async def read_system_settings(_: AdminRole, session: DbSession) -> SystemSettingsRead:
    record = await get_system_settings(session)
    settings = get_settings()
    result = SystemSettingsRead.model_validate(record)
    return result.model_copy(
        update={
            "docmind_configured": bool(
                (record.docmind_access_key_id_encrypted and record.docmind_access_key_secret_encrypted)
                or (settings.docmind_access_key_id and settings.docmind_access_key_secret)
            )
        }
    )


@router.patch("", response_model=SystemSettingsRead)
async def update_system_settings(
    payload: SystemSettingsUpdate, _: AdminRole, session: DbSession
) -> SystemSettingsRead:
    record = await get_system_settings(session)
    changes = payload.model_dump(
        exclude_unset=True, exclude_none=True, exclude={"docmind_access_key_id", "docmind_access_key_secret"}
    )
    if payload.docmind_access_key_id and payload.docmind_access_key_secret:
        cipher = CredentialCipher(get_settings().master_key)
        record.docmind_access_key_id_encrypted = cipher.encrypt(
            payload.docmind_access_key_id.get_secret_value()
        )
        record.docmind_access_key_secret_encrypted = cipher.encrypt(
            payload.docmind_access_key_secret.get_secret_value()
        )
        record.docmind_access_key_mask = mask_secret(payload.docmind_access_key_id.get_secret_value())
    for key, value in changes.items():
        setattr(record, key, value)
    file_fields = {"file_size_limit_bytes", "page_limit", "batch_file_limit"}
    propagated = file_fields.intersection(changes)
    if propagated:
        await session.execute(update(KnowledgeBase).values(**{key: changes[key] for key in propagated}))
    await session.commit()
    await session.refresh(record)
    logger.info("system_settings_updated", extra={"changed_fields": sorted(changes)})
    return await read_system_settings(_, session)
