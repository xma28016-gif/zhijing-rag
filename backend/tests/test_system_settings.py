from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ExperienceRole
from app.schemas.system import SystemSettingsUpdate


def test_system_settings_accept_supported_runtime_values() -> None:
    payload = SystemSettingsUpdate(
        file_size_limit_bytes=200 * 1024 * 1024,
        page_limit=1_000,
        batch_file_limit=40,
        detailed_log_retention_days=180,
        retain_daily_metrics=False,
        browser_session_days=60,
        default_role=ExperienceRole.KNOWLEDGE_MANAGER,
    )

    assert payload.file_size_limit_bytes == 200 * 1024 * 1024
    assert payload.retain_daily_metrics is False
    assert payload.default_role is ExperienceRole.KNOWLEDGE_MANAGER


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_size_limit_bytes", 100),
        ("page_limit", 0),
        ("batch_file_limit", 101),
        ("detailed_log_retention_days", 0),
        ("browser_session_days", 366),
    ],
)
def test_system_settings_reject_unsafe_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        SystemSettingsUpdate(**{field: value})
