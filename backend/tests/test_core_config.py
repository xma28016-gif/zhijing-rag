from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def test_settings_are_loaded_from_rag_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENVIRONMENT", "test")
    monkeypatch.setenv("RAG_LOG_LEVEL", "debug")
    monkeypatch.setenv("RAG_CORS_ORIGINS", '["https://console.example.com/"]')
    monkeypatch.setenv("RAG_MINIO_SECURE", "true")

    configured = Settings(_env_file=None)

    assert configured.environment is Environment.TEST
    assert configured.log_level == "DEBUG"
    assert configured.cors_origins == ["https://console.example.com"]
    assert configured.minio_secure is True


def test_settings_reject_credentialed_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="cors_allow_credentials"):
        Settings(cors_origins=["*"], cors_allow_credentials=True, _env_file=None)


def test_api_prefix_is_normalized() -> None:
    configured = Settings(api_v1_prefix="/internal/v1/", _env_file=None)

    assert configured.api_v1_prefix == "/internal/v1"


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError, match="RAG_MASTER_KEY"):
        Settings(environment=Environment.PRODUCTION, _env_file=None)
