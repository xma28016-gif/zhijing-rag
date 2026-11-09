"""Administrator-only model provider and model configuration API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.crypto import CredentialCipher, SecretCryptoError
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.model_config import (
    ConnectionTestRequest,
    ConnectionTestResult,
    ModelConfigCreate,
    ModelConfigRead,
    ModelConfigUpdate,
    ModelProviderCreate,
    ModelProviderRead,
    ModelProviderUpdate,
    ProviderKind,
    ProviderTemplate,
)
from app.services import model_configs as service
from app.services.model_providers import list_provider_templates, test_model_connection
from app.services.model_runtime import ProviderCallError, resolve_credentials

router = APIRouter(prefix="/model-services", tags=["model-services"])
AdminRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _cipher() -> CredentialCipher:
    return CredentialCipher(get_settings().master_key)


@router.get("/templates", response_model=list[ProviderTemplate])
async def templates(_: AdminRole) -> list[ProviderTemplate]:
    return list_provider_templates()


@router.get("/providers", response_model=list[ModelProviderRead])
async def providers(_: AdminRole, session: DbSession) -> list[ModelProviderRead]:
    return [ModelProviderRead.model_validate(item) for item in await service.list_providers(session)]


@router.post("/providers", response_model=ModelProviderRead, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ModelProviderCreate, _: AdminRole, session: DbSession
) -> ModelProviderRead:
    return ModelProviderRead.model_validate(await service.create_provider(session, payload, _cipher()))


@router.patch("/providers/{provider_id}", response_model=ModelProviderRead)
async def update_provider(
    provider_id: uuid.UUID, payload: ModelProviderUpdate, _: AdminRole, session: DbSession
) -> ModelProviderRead:
    return ModelProviderRead.model_validate(
        await service.update_provider(session, provider_id, payload, _cipher())
    )


@router.get("/models", response_model=list[ModelConfigRead])
async def models(_: AdminRole, session: DbSession) -> list[ModelConfigRead]:
    return [ModelConfigRead.model_validate(item) for item in await service.list_model_configs(session)]


@router.post("/models", response_model=ModelConfigRead, status_code=status.HTTP_201_CREATED)
async def create_model(payload: ModelConfigCreate, _: AdminRole, session: DbSession) -> ModelConfigRead:
    cipher = _cipher()
    provider = await session.get(ModelProvider, payload.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "provider_not_found", "message": "请求的供应商配置不存在。"},
        )
    await service.ensure_model_available(
        session,
        provider_id=payload.provider_id,
        kind=payload.kind,
        name=payload.name,
        model_identifier=payload.model_id,
    )
    override_key = payload.api_key.get_secret_value() if payload.api_key else None
    if override_key:
        api_key = override_key
    elif provider.encrypted_api_key:
        try:
            api_key = cipher.decrypt(provider.encrypted_api_key)
        except SecretCryptoError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "provider_credential_unreadable",
                    "message": "无法读取已保存的供应商密钥，请重新填写 API Key。",
                },
            ) from exc
    else:
        raise HTTPException(
            status_code=422,
            detail={"code": "provider_key_missing", "message": "请先配置供应商 API Key。"},
        )
    probe = ConnectionTestRequest(
        provider=ProviderKind(provider.key),
        kind=payload.kind,
        model_id=payload.model_id,
        api_key=api_key,
        base_url=payload.base_url or provider.base_url,
        extra_headers={**provider.default_headers, **payload.extra_headers},
        expected_dimensions=payload.embedding_dimension,
    )
    result = await test_model_connection(probe)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "code": result.error_code,
                "message": result.error_message,
                "latency_ms": result.latency_ms,
            },
        )
    model = await service.create_model_config(session, payload, cipher)
    await service.record_validation(
        session,
        model,
        ok=True,
        latency_ms=result.latency_ms,
        error=None,
        dimensions=result.dimensions,
        streaming=result.supports_streaming,
    )
    await session.refresh(model)
    return ModelConfigRead.model_validate(model)


@router.patch("/models/{model_id}", response_model=ModelConfigRead)
async def update_model(
    model_id: uuid.UUID, payload: ModelConfigUpdate, _: AdminRole, session: DbSession
) -> ModelConfigRead:
    return ModelConfigRead.model_validate(
        await service.update_model_config(session, model_id, payload, _cipher())
    )


@router.post("/models/{model_id}/test", response_model=ConnectionTestResult)
async def test_saved_model(model_id: uuid.UUID, _: AdminRole, session: DbSession) -> ConnectionTestResult:
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(
            status_code=404, detail={"code": "model_config_not_found", "message": "请求的模型配置不存在。"}
        )
    provider = await session.get(ModelProvider, model.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=409, detail={"code": "provider_not_found", "message": "模型关联的供应商不存在。"}
        )
    try:
        credentials = resolve_credentials(model, provider, _cipher(), check_validation=False)
    except ProviderCallError as exc:
        await service.record_validation(
            session,
            model,
            ok=False,
            latency_ms=0,
            error=exc.safe_message,
            dimensions=None,
            streaming=False,
        )
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc
    probe = ConnectionTestRequest(
        provider=credentials.provider_kind,
        kind=model.kind,
        model_id=model.model_id,
        api_key=credentials.api_key,
        base_url=credentials.base_url,
        extra_headers=credentials.headers,
        expected_dimensions=(model.embedding_dimension if model.kind.value == "embedding" else None),
    )
    result = await test_model_connection(probe)
    await service.record_validation(
        session,
        model,
        ok=result.ok,
        latency_ms=result.latency_ms,
        error=result.error_message,
        dimensions=result.dimensions,
        streaming=result.supports_streaming,
    )
    return result


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: uuid.UUID, _: AdminRole, session: DbSession) -> Response:
    await service.delete_model_config(session, model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=ConnectionTestResult)
async def test_unsaved_model(payload: ConnectionTestRequest, _: AdminRole) -> ConnectionTestResult:
    return await test_model_connection(payload)
