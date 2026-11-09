"""Environment-backed application settings.

All deploy-time values use the ``RAG_`` prefix.  Keeping settings in one
Pydantic model gives the API, workers, and migration commands the same source
of truth while still allowing tests to instantiate an isolated configuration.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Validated configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=(Path(__file__).resolve().parents[3] / ".env", Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Enterprise Knowledge Hub API"
    version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    log_level: str = "INFO"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    cors_allow_credentials: bool = True

    master_key: SecretStr = SecretStr("development-only-change-me")
    database_url: str = "postgresql+psycopg://rag:rag@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("rag-minio")
    minio_secret_key: SecretStr = SecretStr("development-minio-secret")
    minio_secure: bool = False
    minio_bucket: str = "rag-documents"
    storage_backend: str = "minio"
    local_storage_path: Path = Path(".data/documents")
    queued_task_timeout_minutes: int = Field(default=5, ge=1, le=60)
    worker_heartbeat_seconds: int = Field(default=15, ge=5, le=60)

    docmind_access_key_id: SecretStr | None = None
    docmind_access_key_secret: SecretStr | None = None
    docmind_endpoint: str = "docmind-api.cn-hangzhou.aliyuncs.com"
    docmind_poll_interval_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    docmind_timeout_seconds: int = Field(default=7_200, ge=60, le=7_200)

    request_id_header: str = "X-Request-ID"
    experience_role_header: str = "X-Experience-Role"
    browser_session_days: int = Field(default=30, ge=1, le=365)
    detailed_log_retention_days: int = Field(default=90, ge=1, le=3650)
    build_task_stale_minutes: int = Field(default=180, ge=130, le=24 * 60)

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("api_v1_prefix must start with '/'")
        if value != "/":
            value = value.rstrip("/")
        return value

    @field_validator("storage_backend")
    @classmethod
    def validate_storage_backend(cls, value: str) -> str:
        if value not in {"local", "minio"}:
            raise ValueError("storage_backend must be local or minio")
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("log_level must be a standard Python logging level")
        return level

    @field_validator("cors_origins")
    @classmethod
    def normalize_cors_origins(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(origin.strip().rstrip("/") for origin in value if origin.strip()))

    @model_validator(mode="after")
    def validate_cors_credentials(self) -> Self:
        if "*" in self.cors_origins and self.cors_allow_credentials:
            raise ValueError("cors_allow_credentials cannot be true when cors_origins contains '*'")
        if self.environment is Environment.PRODUCTION:
            if self.master_key.get_secret_value() == "development-only-change-me":
                raise ValueError("RAG_MASTER_KEY must be replaced in production")
            if self.minio_secret_key.get_secret_value() == "development-minio-secret":
                raise ValueError("RAG_MINIO_SECRET_KEY must be replaced in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""

    return Settings()


# Compatibility export for modules that prefer an import-time singleton.
settings = get_settings()
