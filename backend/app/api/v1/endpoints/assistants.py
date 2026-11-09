"""Assistant CRUD with model-kind and knowledge-base validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ExperienceRoleDep, require_roles
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.api_key import ApiKeyAssistant
from app.models.assistant import Assistant, AssistantKnowledgeBase
from app.models.chat import BrowserSession
from app.models.enums import (
    AssistantStatus,
    KnowledgeBaseStatus,
    ModelKind,
    ValidationStatus,
)
from app.models.knowledge import KnowledgeBase
from app.models.provider import ModelConfig, ModelProvider
from app.schemas.assistant import (
    AssistantCreate,
    AssistantModelOption,
    AssistantRead,
    AssistantUpdate,
)

router = APIRouter(prefix="/assistants", tags=["assistants"])
ManagerRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN, ExperienceRole.MANAGER))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _load_options():
    return (
        selectinload(Assistant.llm_model),
        selectinload(Assistant.rerank_model),
        selectinload(Assistant.knowledge_base_bindings).selectinload(AssistantKnowledgeBase.knowledge_base),
    )


def _read(record: Assistant) -> AssistantRead:
    values = {
        name: getattr(record, name)
        for name in AssistantRead.model_fields
        if name not in {"knowledge_bases", "llm_model_name", "rerank_model_name"}
    }
    return AssistantRead(
        **values,
        llm_model_name=record.llm_model.name,
        rerank_model_name=record.rerank_model.name if record.rerank_model else None,
        knowledge_bases=[
            {
                "knowledge_base_id": item.knowledge_base_id,
                "priority": item.priority,
                "enabled": item.enabled,
                "knowledge_base_name": item.knowledge_base.name,
            }
            for item in record.knowledge_base_bindings
        ],
    )


async def _validate_models_and_knowledge_bases(
    session: AsyncSession,
    *,
    llm_id: uuid.UUID,
    rerank_id: uuid.UUID | None,
    knowledge_base_ids: list[uuid.UUID],
    require_ready: bool = False,
) -> None:
    llm = await session.get(ModelConfig, llm_id)
    llm_provider = await session.get(ModelProvider, llm.provider_id) if llm else None
    if (
        not llm
        or llm.kind is not ModelKind.LLM
        or not llm.enabled
        or llm.validation_status is not ValidationStatus.VALID
        or not llm_provider
        or not llm_provider.enabled
    ):
        raise HTTPException(
            status_code=422, detail={"code": "invalid_llm_model", "message": "请选择已启用的 LLM 模型。"}
        )
    if rerank_id:
        rerank = await session.get(ModelConfig, rerank_id)
        rerank_provider = await session.get(ModelProvider, rerank.provider_id) if rerank else None
        if (
            not rerank
            or rerank.kind is not ModelKind.RERANK
            or not rerank.enabled
            or rerank.validation_status is not ValidationStatus.VALID
            or not rerank_provider
            or not rerank_provider.enabled
        ):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_rerank_model", "message": "请选择已启用的 Rerank 模型。"},
            )
    records = (
        await session.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(knowledge_base_ids)))
    ).all()
    if {item.id for item in records} != set(knowledge_base_ids):
        raise HTTPException(
            status_code=422,
            detail={"code": "knowledge_base_not_found", "message": "一个或多个知识库不存在。"},
        )
    if require_ready and any(item.status is not KnowledgeBaseStatus.READY for item in records):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "knowledge_base_not_ready",
                "message": "发布助手前，绑定的知识库必须全部构建完成。",
            },
        )


@router.get("/model-options", response_model=list[AssistantModelOption])
async def model_options(_: ManagerRole, session: DbSession) -> list[AssistantModelOption]:
    rows = (
        await session.execute(
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.kind.in_([ModelKind.LLM, ModelKind.RERANK]),
                ModelConfig.enabled.is_(True),
                ModelConfig.validation_status == ValidationStatus.VALID,
                ModelProvider.enabled.is_(True),
            )
            .order_by(ModelConfig.kind, ModelConfig.is_default.desc(), ModelConfig.name)
        )
    ).all()
    return [
        AssistantModelOption(
            id=model.id,
            kind=model.kind,
            name=model.name,
            model_id=model.model_id,
            provider_name=provider.name,
            is_default=model.is_default,
        )
        for model, provider in rows
    ]


@router.get("", response_model=list[AssistantRead])
async def list_assistants(role: ExperienceRoleDep, session: DbSession) -> list[AssistantRead]:
    statement = (
        select(Assistant).where(Assistant.extra_config["deleted_at"].astext.is_(None))
        .options(*_load_options())
    )
    if role is ExperienceRole.USER:
        statement = statement.where(Assistant.status == AssistantStatus.ACTIVE)
    records = (await session.scalars(statement.order_by(Assistant.updated_at.desc()))).all()
    return [_read(record) for record in records]


@router.post("", response_model=AssistantRead, status_code=status.HTTP_201_CREATED)
async def create_assistant(payload: AssistantCreate, _: ManagerRole, session: DbSession) -> AssistantRead:
    if await session.scalar(select(Assistant.id).where(Assistant.alias == payload.alias)):
        raise HTTPException(
            status_code=409, detail={"code": "assistant_alias_exists", "message": "助手别名已存在。"}
        )
    await _validate_models_and_knowledge_bases(
        session,
        llm_id=payload.llm_model_config_id,
        rerank_id=payload.rerank_model_config_id,
        knowledge_base_ids=[item.knowledge_base_id for item in payload.knowledge_bases],
        require_ready=payload.status is AssistantStatus.ACTIVE,
    )
    values = payload.model_dump(exclude={"knowledge_bases", "relevance_threshold", "temperature"})
    assistant = Assistant(
        **values,
        relevance_threshold=Decimal(str(payload.relevance_threshold)),
        temperature=Decimal(str(payload.temperature)),
    )
    assistant.knowledge_base_bindings = [
        AssistantKnowledgeBase(**item.model_dump()) for item in payload.knowledge_bases
    ]
    session.add(assistant)
    await session.commit()
    record = await session.scalar(
        select(Assistant).where(Assistant.id == assistant.id).options(*_load_options())
    )
    return _read(record)


@router.patch("/{assistant_id}", response_model=AssistantRead)
async def update_assistant(
    assistant_id: uuid.UUID, payload: AssistantUpdate, _: ManagerRole, session: DbSession
) -> AssistantRead:
    assistant = await session.scalar(
        select(Assistant).where(Assistant.id == assistant_id).options(*_load_options())
        .with_for_update(of=Assistant).execution_options(populate_existing=True)
    )
    if assistant is None or assistant.extra_config.get("deleted_at"):
        raise HTTPException(
            status_code=404,
            detail={"code": "assistant_not_found", "message": "助手不存在。"},
        )
    values = payload.model_dump(
        exclude_unset=True, exclude={"knowledge_bases", "relevance_threshold", "temperature"}
    )
    llm_id = payload.llm_model_config_id or assistant.llm_model_config_id
    rerank_id = (
        payload.rerank_model_config_id
        if "rerank_model_config_id" in payload.model_fields_set
        else assistant.rerank_model_config_id
    )
    bindings = payload.knowledge_bases or [
        {"knowledge_base_id": item.knowledge_base_id, "priority": item.priority, "enabled": item.enabled}
        for item in assistant.knowledge_base_bindings
    ]
    binding_ids = [
        item.knowledge_base_id if hasattr(item, "knowledge_base_id") else item["knowledge_base_id"]
        for item in bindings
    ]
    await _validate_models_and_knowledge_bases(
        session,
        llm_id=llm_id,
        rerank_id=rerank_id,
        knowledge_base_ids=binding_ids,
        require_ready=(payload.status or assistant.status) is AssistantStatus.ACTIVE,
    )
    for key, value in values.items():
        setattr(assistant, key, value)
    if payload.relevance_threshold is not None:
        assistant.relevance_threshold = Decimal(str(payload.relevance_threshold))
    if payload.temperature is not None:
        assistant.temperature = Decimal(str(payload.temperature))
    if payload.knowledge_bases is not None:
        await session.execute(
            delete(AssistantKnowledgeBase).where(AssistantKnowledgeBase.assistant_id == assistant.id)
        )
        assistant.knowledge_base_bindings = [
            AssistantKnowledgeBase(**item.model_dump()) for item in payload.knowledge_bases
        ]
    await session.commit()
    record = await session.scalar(
        select(Assistant).where(Assistant.id == assistant.id).options(*_load_options())
    )
    return _read(record)


@router.delete("/{assistant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assistant(assistant_id: uuid.UUID, _: ManagerRole, session: DbSession) -> None:
    assistant = await session.scalar(
        select(Assistant).where(Assistant.id == assistant_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if assistant is None:
        raise HTTPException(
            status_code=404, detail={"code": "assistant_not_found", "message": "助手不存在。"}
        )
    if assistant.extra_config.get("deleted_at"):
        return
    # Preserve the row referenced by durable conversations and run records.
    assistant.status = AssistantStatus.DISABLED
    assistant.extra_config = {**assistant.extra_config, "deleted_at": datetime.now(UTC).isoformat()}
    await session.execute(
        delete(AssistantKnowledgeBase).where(AssistantKnowledgeBase.assistant_id == assistant_id)
    )
    await session.execute(delete(ApiKeyAssistant).where(ApiKeyAssistant.assistant_id == assistant_id))
    await session.execute(
        update(BrowserSession).where(BrowserSession.active_assistant_id == assistant_id)
        .values(active_assistant_id=None)
    )
    await session.commit()
