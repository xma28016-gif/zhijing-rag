"""Versioned API router."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    api_keys,
    assistants,
    chat,
    datasets,
    health,
    knowledge_bases,
    logs,
    model_configs,
    system_settings,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(model_configs.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(assistants.router)
api_router.include_router(chat.router)
api_router.include_router(api_keys.router)
api_router.include_router(logs.router)
api_router.include_router(datasets.router)
api_router.include_router(system_settings.router)
