"""Filtered run details and long-lived daily aggregates."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.roles import ExperienceRole
from app.db.session import get_db_session
from app.models.enums import MetricScope, RunChannel, RunStatus
from app.models.metrics import DailyMetric
from app.models.run import RunRecord
from app.schemas.logs import DailyMetricRead, RunDetail, RunRead, RunStepRead

router = APIRouter(prefix="/logs", tags=["logs"])
LogRole = Annotated[ExperienceRole, Depends(require_roles(ExperienceRole.ADMIN, ExperienceRole.MANAGER))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/runs", response_model=list[RunRead])
async def list_runs(
    _: LogRole,
    session: DbSession,
    assistant_id: uuid.UUID | None = None,
    run_status: RunStatus | None = None,
    channel: RunChannel | None = None,
    query: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunRead]:
    statement = select(RunRecord)
    if assistant_id:
        statement = statement.where(RunRecord.assistant_id == assistant_id)
    if run_status:
        statement = statement.where(RunRecord.status == run_status)
    if channel:
        statement = statement.where(RunRecord.channel == channel)
    if query:
        statement = statement.where(RunRecord.query_text.ilike(f"%{query}%"))
    if started_after:
        statement = statement.where(RunRecord.started_at >= started_after)
    if started_before:
        statement = statement.where(RunRecord.started_at <= started_before)
    records = (await session.scalars(statement.order_by(RunRecord.started_at.desc()).limit(limit))).all()
    return [RunRead.model_validate(record) for record in records]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def run_detail(run_id: uuid.UUID, _: LogRole, session: DbSession) -> RunDetail:
    record = await session.scalar(
        select(RunRecord).where(RunRecord.id == run_id).options(selectinload(RunRecord.steps))
    )
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "运行记录不存在。"})
    values = {name: getattr(record, name) for name in RunDetail.model_fields if name not in {"steps"}}
    return RunDetail(
        **values,
        steps=[RunStepRead.model_validate(step) for step in record.steps],
    )


@router.get("/daily", response_model=list[DailyMetricRead])
async def daily_metrics(
    _: LogRole,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[DailyMetricRead]:
    since = date.today() - timedelta(days=days - 1)
    records = (
        await session.scalars(
            select(DailyMetric)
            .where(
                DailyMetric.scope == MetricScope.SYSTEM,
                DailyMetric.metric_date >= since,
            )
            .order_by(DailyMetric.metric_date, DailyMetric.channel)
        )
    ).all()
    return [DailyMetricRead.model_validate(record, from_attributes=True) for record in records]
