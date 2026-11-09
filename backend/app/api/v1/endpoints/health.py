"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])

ReadinessCheck = Callable[[], bool | Awaitable[bool]]


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] | None = None


@router.get("/live", response_model=HealthResponse, summary="Process liveness")
async def live() -> HealthResponse:
    """Confirm the API process can receive and answer requests."""

    return HealthResponse(status="ok")


async def _run_check(check: ReadinessCheck) -> bool:
    result = check()
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    summary="Service readiness",
)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    """Run registered dependency checks and report whether traffic is safe."""

    checks: dict[str, str] = {"application": "ok"}
    registered: dict[str, ReadinessCheck] = getattr(request.app.state, "readiness_checks", {})

    async def run(name, check):
        try:
            checks[name] = "ok" if await asyncio.wait_for(_run_check(check), 4) else "failed"
        except Exception:
            checks[name] = "failed"

    await asyncio.gather(*(run(name, check) for name, check in registered.items()))

    if any(value != "ok" for value in checks.values()):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=HealthResponse(status="not_ready", checks=checks).model_dump(),
        )
    return HealthResponse(status="ready", checks=checks)
