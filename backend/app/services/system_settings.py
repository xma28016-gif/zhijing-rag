"""Access the singleton runtime configuration row."""

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import CredentialCipher
from app.models.system import SystemSetting


async def get_system_settings(session: AsyncSession) -> SystemSetting:
    record = await session.get(SystemSetting, 1)
    if record is None:
        record = SystemSetting(id=1)
        session.add(record)
        await session.flush()
    return record


async def get_parser_settings(session: AsyncSession):
    settings = get_settings()
    record = await get_system_settings(session)
    if not record.docmind_access_key_id_encrypted or not record.docmind_access_key_secret_encrypted:
        return settings
    cipher = CredentialCipher(settings.master_key)
    return settings.model_copy(
        update={
            "docmind_access_key_id": SecretStr(cipher.decrypt(record.docmind_access_key_id_encrypted)),
            "docmind_access_key_secret": SecretStr(
                cipher.decrypt(record.docmind_access_key_secret_encrypted)
            ),
            "docmind_endpoint": record.docmind_endpoint,
        }
    )


async def docmind_is_configured(session: AsyncSession) -> bool:
    record = await get_system_settings(session)
    settings = get_settings()
    return bool(
        (record.docmind_access_key_id_encrypted and record.docmind_access_key_secret_encrypted)
        or (settings.docmind_access_key_id and settings.docmind_access_key_secret)
    )
