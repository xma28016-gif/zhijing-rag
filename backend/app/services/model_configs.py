"""Persistence rules for provider credentials and model configurations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import CredentialCipher, mask_secret
from app.models.assistant import Assistant
from app.models.enums import ModelKind, ValidationStatus
from app.models.knowledge import KnowledgeBase
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelProviderCreate,
    ModelProviderUpdate,
)
from app.services.model_providers.templates import get_provider_template


def _not_found(resource: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": f"{resource}_not_found", "message": "请求的配置不存在。"},
    )


async def list_providers(session: AsyncSession) -> list[ModelProvider]:
    return list((await session.scalars(select(ModelProvider).order_by(ModelProvider.sort_order))).all())


async def create_provider(
    session: AsyncSession, payload: ModelProviderCreate, cipher: CredentialCipher
) -> ModelProvider:
    if await session.scalar(select(ModelProvider.id).where(ModelProvider.key == payload.key.value)):
        raise HTTPException(
            status_code=409,
            detail={"code": "provider_exists", "message": "该供应商配置已存在。"},
        )
    template = get_provider_template(payload.key)
    raw_key = payload.api_key.get_secret_value()
    provider = ModelProvider(
        key=payload.key.value,
        name=payload.name,
        description=payload.description,
        base_url=payload.base_url or template.default_base_url,
        encrypted_api_key=cipher.encrypt(raw_key),
        api_key_mask=mask_secret(raw_key),
        default_headers=payload.default_headers,
        capabilities={kind.value: True for kind in template.capabilities},
        enabled=payload.enabled,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


async def update_provider(
    session: AsyncSession, provider_id: uuid.UUID, payload: ModelProviderUpdate, cipher: CredentialCipher
) -> ModelProvider:
    provider = await session.get(ModelProvider, provider_id)
    if provider is None:
        raise _not_found("provider")
    values = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    connection_changed = payload.api_key is not None or any(
        key in values and values[key] != getattr(provider, key)
        for key in ("base_url", "default_headers", "enabled")
    )
    for key, value in values.items():
        setattr(provider, key, value)
    if payload.api_key is not None:
        raw_key = payload.api_key.get_secret_value()
        provider.encrypted_api_key = cipher.encrypt(raw_key)
        provider.api_key_mask = mask_secret(raw_key)
    if connection_changed:
        await session.execute(
            update(ModelConfig)
            .where(ModelConfig.provider_id == provider.id)
            .values(
                validation_status=ValidationStatus.UNTESTED,
                validated_at=None,
                validation_latency_ms=None,
                validation_error=None,
            )
        )
    await session.commit()
    await session.refresh(provider)
    return provider


async def list_model_configs(session: AsyncSession) -> list[ModelConfig]:
    statement = select(ModelConfig).order_by(ModelConfig.kind, ModelConfig.name)
    return list((await session.scalars(statement)).all())


async def ensure_model_available(
    session: AsyncSession,
    *,
    provider_id: uuid.UUID,
    kind: ModelKind,
    name: str,
    model_identifier: str,
    excluding_id: uuid.UUID | None = None,
) -> None:
    statement = select(ModelConfig).where(
        ModelConfig.provider_id == provider_id,
        ModelConfig.kind == kind,
        or_(ModelConfig.name == name, ModelConfig.model_id == model_identifier),
    )
    if excluding_id:
        statement = statement.where(ModelConfig.id != excluding_id)
    existing = await session.scalar(statement.limit(1))
    if existing:
        same_model = existing.model_id == model_identifier
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_config_exists" if same_model else "model_name_exists",
                "message": "该服务商下已配置此类型的模型 ID，请编辑已有配置。"
                if same_model
                else "该服务商下已存在同类型同名模型，请修改显示名称或编辑已有配置。",
            },
        )


async def create_model_config(
    session: AsyncSession, payload: ModelConfigCreate, cipher: CredentialCipher
) -> ModelConfig:
    if await session.get(ModelProvider, payload.provider_id) is None:
        raise _not_found("provider")
    await ensure_model_available(
        session,
        provider_id=payload.provider_id,
        kind=payload.kind,
        name=payload.name,
        model_identifier=payload.model_id,
    )
    values = payload.model_dump(exclude={"api_key"})
    raw_key = payload.api_key.get_secret_value() if payload.api_key else None
    model = ModelConfig(**values)
    if raw_key:
        model.encrypted_api_key = cipher.encrypt(raw_key)
        model.api_key_mask = mask_secret(raw_key)
    if payload.is_default:
        await session.execute(
            update(ModelConfig).where(ModelConfig.kind == payload.kind).values(is_default=False)
        )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


async def update_model_config(
    session: AsyncSession, model_id: uuid.UUID, payload: ModelConfigUpdate, cipher: CredentialCipher
) -> ModelConfig:
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise _not_found("model_config")
    values = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    connection_changed = payload.api_key is not None or any(
        key in values and values[key] != getattr(model, key)
        for key in ("model_id", "base_url", "extra_headers", "extra_config", "embedding_dimension")
    )
    if values.get("is_default"):
        provider = await session.get(ModelProvider, model.provider_id)
        if (
            connection_changed
            or not values.get("enabled", model.enabled)
            or model.validation_status is not ValidationStatus.VALID
            or provider is None
            or not provider.enabled
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "default_model_not_available",
                    "message": "请先启用服务商，并将模型测试通过，再设为默认模型。",
                },
            )
    await ensure_model_available(
        session,
        provider_id=model.provider_id,
        kind=model.kind,
        name=values.get("name") or model.name,
        model_identifier=values.get("model_id") or model.model_id,
        excluding_id=model.id,
    )
    new_dimension = values.get("embedding_dimension")
    changes_embedding_space = model.kind is ModelKind.EMBEDDING and (
        (new_dimension is not None and new_dimension != model.embedding_dimension)
        or any(key in values and values[key] != getattr(model, key) for key in ("model_id", "base_url"))
    )
    if changes_embedding_space:
        in_use = await session.scalar(
            select(KnowledgeBase.id).where(KnowledgeBase.embedding_model_config_id == model.id).limit(1)
        )
        if in_use:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "embedding_dimension_in_use",
                    "message": "该 Embedding 模型已被知识库使用，维度不可直接修改；请创建新配置并发起重建。",
                },
            )
    if values.get("is_default"):
        await session.execute(
            update(ModelConfig)
            .where(ModelConfig.kind == model.kind, ModelConfig.id != model.id)
            .values(is_default=False)
        )
    for key, value in values.items():
        setattr(model, key, value)
    if payload.api_key is not None:
        raw_key = payload.api_key.get_secret_value()
        model.encrypted_api_key = cipher.encrypt(raw_key)
        model.api_key_mask = mask_secret(raw_key)
    if connection_changed:
        model.validation_status = ValidationStatus.UNTESTED
        model.validated_at = None
        model.validation_latency_ms = None
        model.validation_error = None
    await session.commit()
    await session.refresh(model)
    return model


async def delete_model_config(session: AsyncSession, model_id: uuid.UUID) -> None:
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise _not_found("model_config")
    in_use = await session.scalar(
        select(KnowledgeBase.id).where(KnowledgeBase.embedding_model_config_id == model.id).limit(1)
    )
    if in_use or await session.scalar(
        select(Assistant.id)
        .where(or_(Assistant.llm_model_config_id == model.id, Assistant.rerank_model_config_id == model.id))
        .limit(1)
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "model_config_in_use", "message": "模型已被知识库使用，不能删除。"},
        )
    await session.execute(delete(ModelConfig).where(ModelConfig.id == model_id))
    await session.commit()


async def record_validation(
    session: AsyncSession,
    model: ModelConfig,
    *,
    ok: bool,
    latency_ms: int,
    error: str | None,
    dimensions: int | None,
    streaming: bool,
) -> None:
    model.validation_status = ValidationStatus.VALID if ok else ValidationStatus.INVALID
    model.validated_at = datetime.now(UTC)
    model.validation_latency_ms = latency_ms
    model.validation_error = error
    if ok:
        model.supports_streaming = streaming
        if dimensions:
            model.embedding_dimension = dimensions
    await session.commit()
