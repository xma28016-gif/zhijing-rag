"""Structured JSON logging with per-request correlation."""

from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


def bind_request_id(request_id: str) -> Token[str]:
    """Bind a request id to the current async context."""

    return request_id_context.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore the request id context after a request completes."""

    request_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Small dependency-free JSON formatter for container stdout logs."""

    _standard_record_fields = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }

        for key, value in record.__dict__.items():
            if key not in self._standard_record_fields and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    """Configure application and server loggers for JSON stdout output."""

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": "app.core.logging.JsonFormatter"}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["stdout"], "level": settings.log_level},
            "loggers": {
                "uvicorn": {"handlers": ["stdout"], "level": settings.log_level, "propagate": False},
                "uvicorn.error": {
                    "handlers": ["stdout"],
                    "level": settings.log_level,
                    "propagate": False,
                },
                # Access events are emitted by RequestContextMiddleware with a
                # consistent schema, so Uvicorn's text access log is disabled.
                "uvicorn.access": {"handlers": [], "propagate": False},
            },
        }
    )
