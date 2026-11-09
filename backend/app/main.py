"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.api.external import router as external_router
from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import Environment, Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Build an application instance, optionally with isolated test settings."""

    resolved = app_settings or get_settings()
    configure_logging(resolved)

    application = FastAPI(
        title=resolved.app_name,
        version=resolved.version,
        debug=resolved.debug,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    application.state.settings = resolved
    application.state.readiness_checks = {}

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(request, exc):
        original = getattr(exc, "orig", None)
        sqlstate = getattr(original, "sqlstate", None)
        constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
        logging.getLogger(__name__).error(
            "database_operation_failed",
            extra={"error_type": type(exc).__name__, "sqlstate": sqlstate, "constraint": constraint},
        )
        status_code, code, message = (
            500,
            "database_operation_failed",
            "数据处理失败，请联系管理员检查后台日志。",
        )
        if isinstance(exc, IntegrityError):
            status_code, code, message = 409, "data_conflict", "相同配置已存在，请编辑已有项或修改名称。"
            if constraint == "uq_model_configs_provider_kind_name":
                code, message = "model_name_exists", "该服务商下已存在同类型同名模型，请修改显示名称。"
            elif constraint == "uq_model_configs_provider_kind_model":
                code, message = "model_config_exists", "该服务商下已配置此类型的模型 ID，请编辑已有配置。"
            elif sqlstate in {"23502", "23514"}:
                status_code, code, message = 422, "invalid_data", "配置不符合数据要求，请检查填写内容。"
            elif sqlstate == "23503":
                message = "关联的数据正在使用或已不存在，请刷新后重试。"
        elif isinstance(exc, OperationalError):
            status_code, code, message = (
                503,
                "database_unavailable",
                "数据服务暂不可用，请检查数据库连接或运行项目启动脚本。",
            )
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": {
                    "code": code,
                    "message": message,
                }
            },
        )

    if resolved.environment is not Environment.TEST:
        from app.services.readiness import database_ready, minio_ready, redis_ready, worker_ready

        application.state.readiness_checks = {
            "postgres": database_ready,
            "redis": redis_ready(resolved),
            "storage": minio_ready(resolved),
            "worker": worker_ready(resolved),
        }

    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=resolved.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[resolved.request_id_header, "X-Browser-Session"],
    )
    application.add_middleware(
        RequestContextMiddleware,
        header_name=resolved.request_id_header,
    )

    # Root probes are stable targets for Docker/Kubernetes.  The same handlers
    # are also available under /api/v1 for API clients and are documented there.
    application.include_router(health.router, include_in_schema=False)
    application.include_router(api_router, prefix=resolved.api_v1_prefix)
    application.include_router(external_router)
    return application


app = create_app()
