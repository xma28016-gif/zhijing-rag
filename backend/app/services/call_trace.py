"""Request-scoped model accounting, including calls made before a pipeline fails."""

from __future__ import annotations

import asyncio
import functools
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ModelCall:
    kind: str
    model_id: Any
    model_name: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    usage: Any = None
    status: str = "running"
    error_code: str | None = None

    @property
    def duration_ms(self) -> int:
        return round(((self.finished_at or datetime.now(UTC)) - self.started_at).total_seconds() * 1000)


_trace: ContextVar[list[ModelCall] | None] = ContextVar("model_call_trace", default=None)
_current: ContextVar[ModelCall | None] = ContextVar("current_model_call", default=None)


def start_trace():
    return _trace.set([])


def finish_trace(token):
    _trace.reset(token)


def calls() -> list[ModelCall]:
    current = _trace.get()
    return current if current is not None else []


@contextmanager
def use_trace(rows):
    token = _trace.set(rows)
    try:
        yield
    finally:
        _trace.reset(token)


def record_usage(usage):
    call = _current.get()
    if call is not None:
        call.usage = usage


def observe(kind: str):
    def decorate(fn):
        def begin(model):
            call = ModelCall(kind, getattr(model, "id", None), model.model_id)
            trace = _trace.get()
            if trace is not None:
                trace.append(call)
            return call, _current.set(call)

        def end(call, token, exc=None):
            call.finished_at = datetime.now(UTC)
            call.status = (
                "cancelled" if isinstance(exc, asyncio.CancelledError) else ("failed" if exc else "succeeded")
            )
            call.error_code = getattr(exc, "code", type(exc).__name__) if exc else None
            _current.reset(token)

        if inspect.isasyncgenfunction(fn):

            @functools.wraps(fn)
            async def generator(model, *args, **kwargs):
                call, token = begin(model)
                error = None
                try:
                    async for event in fn(model, *args, **kwargs):
                        if event.usage:
                            call.usage = event.usage
                        yield event
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    end(call, token, error)

            return generator

        @functools.wraps(fn)
        async def invoke(model, *args, **kwargs):
            call, token = begin(model)
            error = None
            try:
                result = await fn(model, *args, **kwargs)
                if hasattr(result, "usage"):
                    call.usage = result.usage
                return result
            except BaseException as exc:
                error = exc
                raise
            finally:
                end(call, token, error)

        return invoke

    return decorate


def totals() -> tuple[int, int, bool]:
    rows = calls()
    prompt = sum(call.usage.prompt_tokens for call in rows if call.usage)
    completion = sum(call.usage.completion_tokens for call in rows if call.usage)
    return prompt, completion, all(call.usage is not None and call.usage.exact for call in rows)
