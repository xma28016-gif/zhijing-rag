"""Manual online case feedback backed by PostgreSQL, without model calls."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.assistant import Assistant
from app.models.chat import ChatMessage
from app.models.dataset import EvaluationDataset, EvaluationSample
from app.models.enums import RunStatus
from app.models.run import RunRecord
from app.schemas.dataset import (
    CaptureResult,
    DatasetCreate,
    DatasetRead,
    SampleCapture,
    SampleDetail,
    SamplePage,
    SampleSummary,
    SampleUpdate,
)
from app.schemas.logs import RunDetail, RunStepRead

router = APIRouter(prefix="/evaluation-datasets", tags=["evaluation-datasets"])
Curator = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN, ExperienceRole.MANAGER))]
Db = Annotated[AsyncSession, Depends(get_db_session)]


def scrub_secrets(value: Any) -> Any:
    """Never copy credential-bearing config fields into a long-lived case snapshot."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                part in key.lower()
                for part in (
                    "api_key",
                    "access_key",
                    "secret",
                    "password",
                    "authorization",
                    "credential",
                )
            )
            else scrub_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    return value


async def require_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> EvaluationDataset:
    dataset = await session.get(EvaluationDataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, detail={"code": "dataset_not_found", "message": "评测集不存在。"})
    return dataset


async def require_sample(
    session: AsyncSession, dataset_id: uuid.UUID, sample_id: uuid.UUID, *, lock: bool = False
) -> EvaluationSample:
    statement = select(EvaluationSample).where(
        EvaluationSample.id == sample_id,
        EvaluationSample.dataset_id == dataset_id,
    )
    if lock:
        statement = statement.with_for_update()
    sample = await session.scalar(statement)
    if sample is None:
        raise HTTPException(404, detail={"code": "case_not_found", "message": "Case 不存在。"})
    return sample


@router.get("", response_model=list[DatasetRead])
async def list_datasets(_: Curator, session: Db) -> list[DatasetRead]:
    datasets = (
        await session.scalars(select(EvaluationDataset).order_by(EvaluationDataset.created_at.desc()))
    ).all()
    counts = (
        await session.execute(
            select(
                EvaluationSample.dataset_id, EvaluationSample.label, EvaluationSample.state, func.count()
            ).group_by(EvaluationSample.dataset_id, EvaluationSample.label, EvaluationSample.state)
        )
    ).all()
    totals: dict[uuid.UUID, dict[str, int]] = {}
    for dataset_id, label, state, count in counts:
        item = totals.setdefault(dataset_id, {})
        item[f"{state}_count"] = item.get(f"{state}_count", 0) + count
        if state != "archived":
            item["total_count"] = item.get("total_count", 0) + count
            item[f"{label}_count"] = item.get(f"{label}_count", 0) + count
    return [DatasetRead.model_validate(row).model_copy(update=totals.get(row.id, {})) for row in datasets]


@router.post("", response_model=DatasetRead, status_code=201)
async def create_dataset(payload: DatasetCreate, _: Curator, session: Db) -> DatasetRead:
    row = EvaluationDataset(**payload.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return DatasetRead.model_validate(row)


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: uuid.UUID, _: Curator, session: Db) -> None:
    # The database cascades only this dataset's snapshots; original run logs are independent.
    # Repeating an already completed deletion remains successful.
    await session.execute(delete(EvaluationDataset).where(EvaluationDataset.id == dataset_id))
    await session.commit()


@router.get("/{dataset_id}/cases", response_model=SamplePage)
async def list_cases(
    dataset_id: uuid.UUID,
    _: Curator,
    session: Db,
    label: Literal["good", "bad"] | None = None,
    state: Literal["draft", "ready", "archived"] | None = None,
    query: Annotated[str, Query(max_length=200)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SamplePage:
    await require_dataset(session, dataset_id)
    filters = [EvaluationSample.dataset_id == dataset_id]
    if label:
        filters.append(EvaluationSample.label == label)
    filters.append(EvaluationSample.state == state if state else EvaluationSample.state != "archived")
    if query.strip():
        filters.append(EvaluationSample.question.icontains(query.strip(), autoescape=True))
    total = await session.scalar(select(func.count()).select_from(EvaluationSample).where(*filters))
    rows = (
        await session.scalars(
            select(EvaluationSample)
            .where(*filters)
            .order_by(EvaluationSample.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return SamplePage(items=[SampleSummary.model_validate(row) for row in rows], total=total or 0)


@router.post("/{dataset_id}/cases", response_model=CaptureResult)
async def capture_case(
    dataset_id: uuid.UUID, payload: SampleCapture, _: Curator, session: Db
) -> CaptureResult:
    await require_dataset(session, dataset_id)
    existing = await session.scalar(
        select(EvaluationSample).where(
            EvaluationSample.dataset_id == dataset_id,
            EvaluationSample.source_run_id == payload.source_run_id,
        )
    )
    if existing:
        return CaptureResult(sample=SampleSummary.model_validate(existing), already_exists=True)
    run = await session.scalar(
        select(RunRecord).where(RunRecord.id == payload.source_run_id).options(selectinload(RunRecord.steps))
    )
    if run is None:
        raise HTTPException(404, detail={"code": "run_not_found", "message": "来源日志已不存在，无法收录。"})
    if run.status == RunStatus.RUNNING:
        raise HTTPException(
            409, detail={"code": "run_in_progress", "message": "请等待本次运行结束后再收录。"}
        )
    detail = RunDetail(
        **{name: getattr(run, name) for name in RunDetail.model_fields if name != "steps"},
        steps=[RunStepRead.model_validate(step) for step in sorted(run.steps, key=lambda row: row.sequence)],
    )
    assistant = await session.get(Assistant, run.assistant_id)
    history = []
    history_truncated = False
    if payload.scope == "history" and run.conversation_id:
        messages = (
            await session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == run.conversation_id,
                    ChatMessage.created_at < run.started_at,
                )
                .order_by(ChatMessage.sequence.desc())
                .limit(21)
            )
        ).all()
        history_truncated = len(messages) > 20
        history = [
            {
                "role": message.role.value,
                "content": message.content,
                "sequence": message.sequence,
                "citations": deepcopy(message.citations),
            }
            for message in reversed(messages[:20])
            if message.run_id != run.id
        ]
    snapshot = scrub_secrets(
        {
            "schema_version": 1,
            "captured_at": datetime.now(UTC).isoformat(),
            "assistant_name": assistant.name if assistant else "未知助手",
            "run": detail.model_dump(mode="json"),
            "history": history,
            "history_truncated": history_truncated,
            "history_note": "收录运行开始前最多 20 条对话记录；模型实际使用的上下文以执行节点记录为准。",
        }
    )
    # PostgreSQL handles simultaneous double clicks without losing either request to a unique error.
    sample_id = await session.scalar(
        insert(EvaluationSample)
        .values(
            dataset_id=dataset_id,
            source_run_id=run.id,
            label=payload.label,
            scope=payload.scope,
            question=run.query_text,
            answer=run.answer_text or "",
            snapshot=snapshot,
            note=payload.note,
            state="draft",
            reference_answer="",
            rubric="",
            ready_confirmed=False,
            revision=1,
        )
        .on_conflict_do_nothing(constraint="uq_evaluation_sample_source")
        .returning(EvaluationSample.id)
    )
    await session.commit()
    sample = await session.scalar(
        select(EvaluationSample).where(
            EvaluationSample.dataset_id == dataset_id,
            EvaluationSample.source_run_id == run.id,
        )
    )
    return CaptureResult(sample=SampleSummary.model_validate(sample), already_exists=sample_id is None)


@router.get("/{dataset_id}/cases/{sample_id}", response_model=SampleDetail)
async def case_detail(dataset_id: uuid.UUID, sample_id: uuid.UUID, _: Curator, session: Db) -> SampleDetail:
    sample = await require_sample(session, dataset_id, sample_id)
    available = await session.scalar(select(RunRecord.id).where(RunRecord.id == sample.source_run_id))
    return SampleDetail(
        **SampleSummary.model_validate(sample).model_dump(),
        snapshot=sample.snapshot,
        source_available=available is not None,
    )


@router.patch("/{dataset_id}/cases/{sample_id}", response_model=SampleSummary)
async def update_case(
    dataset_id: uuid.UUID, sample_id: uuid.UUID, payload: SampleUpdate, _: Curator, session: Db
) -> SampleSummary:
    sample = await require_sample(session, dataset_id, sample_id, lock=True)
    if sample.revision != payload.revision:
        raise HTTPException(
            409,
            detail={
                "code": "case_revision_conflict",
                "message": "Case 已被更新，请关闭详情并重新打开后再编辑。",
            },
        )
    for name, value in payload.model_dump(exclude={"revision"}).items():
        setattr(sample, name, value)
    sample.revision += 1
    await session.commit()
    await session.refresh(sample)
    return SampleSummary.model_validate(sample)
