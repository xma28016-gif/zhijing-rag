"""Celery application for parsing, indexing, cleanup, and aggregation tasks."""

import socket
import time

from celery import Celery, signals
from redis import Redis

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "zhijing_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "purge-expired-detailed-logs": {
            "task": "app.worker.purge_expired_detailed_logs",
            "schedule": 24 * 60 * 60,
        },
        "aggregate-daily-metrics": {
            "task": "app.worker.aggregate_daily_metrics",
            "schedule": 60 * 60,
        },
        "recover-stale-build-tasks": {
            "task": "app.worker.recover_stale_build_tasks",
            "schedule": 60,
        },
    },
)


@signals.heartbeat_sent.connect
@signals.worker_ready.connect
def publish_worker_heartbeat(**kwargs):
    try:
        with Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as client:
            client.setex(f"rag:worker:{socket.gethostname()}", 60, str(time.time()))
    except Exception:
        # Readiness will expose a missing heartbeat; never kill the worker signal loop.
        return


@celery_app.task(name="app.worker.purge_expired_detailed_logs")
def purge_expired_detailed_logs() -> dict[str, int | str]:
    from app.services.log_retention import run_aggregation, run_purge

    run_aggregation()
    return {"status": "ok", "deleted": run_purge()}


@celery_app.task(name="app.worker.aggregate_daily_metrics")
def aggregate_daily_metrics() -> dict[str, int | str]:
    from app.services.log_retention import run_aggregation

    return {"status": "ok", "aggregates": run_aggregation()}


@celery_app.task(name="app.worker.recover_stale_build_tasks")
def recover_stale_build_tasks() -> dict[str, int | str]:
    from app.services.build_recovery import run_stale_build_recovery

    return {"status": "ok", "failed_tasks": run_stale_build_recovery()}


@celery_app.task(name="app.worker.parse_document", acks_late=True)
def parse_document(task_id: str) -> None:
    from app.services.ingestion import run_parse_task

    run_parse_task(task_id)


@celery_app.task(name="app.worker.index_document", acks_late=True)
def index_document(task_id: str) -> None:
    from app.services.indexing import run_index_task

    run_index_task(task_id)
