"""Long-lived daily aggregation and detailed-log retention jobs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select

from app.db.session import AsyncSessionFactory
from app.models.enums import MetricScope, RunStatus
from app.models.metrics import DailyMetric
from app.models.run import RunRecord
from app.services.system_settings import get_system_settings


async def aggregate_recent_daily_metrics(days: int = 90) -> int:
    metric_date = func.date(func.timezone("Asia/Shanghai", RunRecord.started_at))
    dimensions = [
        (MetricScope.SYSTEM, None),
        (MetricScope.ASSISTANT, RunRecord.assistant_id),
        (MetricScope.API_KEY, RunRecord.api_key_id),
        (MetricScope.MODEL, RunRecord.llm_model_config_id),
    ]
    created = 0
    async with AsyncSessionFactory() as session:
        system_settings = await get_system_settings(session)
        if not system_settings.retain_daily_metrics:
            return 0
        # The oldest retained raw day can be partial after hourly retention.
        # Preserve its existing aggregate instead of replacing it with a fragment.
        window = min(max(1, days), system_settings.detailed_log_retention_days)
        since = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=window - 1)
        await session.execute(delete(DailyMetric).where(DailyMetric.metric_date >= since))
        for scope, column in dimensions:
            selected = [metric_date.label("metric_date"), RunRecord.channel]
            if column is not None:
                selected.append(column.label("scope_id"))
            statement = select(
                *selected,
                func.count(RunRecord.id),
                func.sum(case((RunRecord.status == RunStatus.SUCCEEDED, 1), else_=0)),
                func.sum(case((RunRecord.status == RunStatus.FAILED, 1), else_=0)),
                func.sum(case((RunRecord.status == RunStatus.INSUFFICIENT_EVIDENCE, 1), else_=0)),
                func.coalesce(func.sum(RunRecord.prompt_tokens), 0),
                func.coalesce(func.sum(RunRecord.completion_tokens), 0),
                func.coalesce(func.sum(RunRecord.total_tokens), 0),
                func.coalesce(func.sum(RunRecord.duration_ms), 0),
                func.coalesce(func.sum(RunRecord.retrieved_chunk_count), 0),
                func.coalesce(func.max(RunRecord.duration_ms), 0),
            ).where(metric_date >= since)
            groups = [metric_date, RunRecord.channel]
            if column is not None:
                statement = statement.where(column.is_not(None))
                groups.append(column)
            rows = (await session.execute(statement.group_by(*groups))).all()
            for row in rows:
                offset = 3 if column is not None else 2
                scope_id = row[2] if column is not None else None
                session.add(
                    DailyMetric(
                        metric_date=row[0],
                        scope=scope,
                        scope_id=scope_id,
                        channel=row[1].value if hasattr(row[1], "value") else str(row[1]),
                        request_count=int(row[offset]),
                        success_count=int(row[offset + 1] or 0),
                        error_count=int(row[offset + 2] or 0),
                        insufficient_evidence_count=int(row[offset + 3] or 0),
                        prompt_tokens=int(row[offset + 4] or 0),
                        completion_tokens=int(row[offset + 5] or 0),
                        total_tokens=int(row[offset + 6] or 0),
                        total_duration_ms=int(row[offset + 7] or 0),
                        total_retrieved_chunks=int(row[offset + 8] or 0),
                        max_duration_ms=int(row[offset + 9] or 0),
                    )
                )
                created += 1
        await session.commit()
    return created


async def purge_expired_runs() -> int:
    async with AsyncSessionFactory() as session:
        system_settings = await get_system_settings(session)
        cutoff = datetime.now(UTC) - timedelta(days=system_settings.detailed_log_retention_days)
        result = await session.execute(delete(RunRecord).where(RunRecord.started_at < cutoff))
        await session.commit()
        return int(result.rowcount or 0)


def run_aggregation() -> int:
    return asyncio.run(aggregate_recent_daily_metrics())


def run_purge() -> int:
    return asyncio.run(purge_expired_runs())
