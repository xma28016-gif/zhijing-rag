"""Effective runtime system settings."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models.enums import ExperienceRole


class SystemSettingsUpdate(BaseModel):
    docmind_access_key_id: SecretStr | None = Field(default=None, repr=False)
    docmind_access_key_secret: SecretStr | None = Field(default=None, repr=False)
    docmind_endpoint: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9.-]+$", max_length=255)
    file_size_limit_bytes: int | None = Field(default=None, ge=1024 * 1024, le=1024 * 1024 * 1024)
    page_limit: int | None = Field(default=None, ge=1, le=5_000)
    batch_file_limit: int | None = Field(default=None, ge=1, le=100)
    detailed_log_retention_days: int | None = Field(default=None, ge=1, le=3_650)
    retain_daily_metrics: bool | None = None
    browser_session_days: int | None = Field(default=None, ge=1, le=365)
    default_role: ExperienceRole | None = None

    @model_validator(mode="after")
    def validate_ocr_keys(self):
        if bool(self.docmind_access_key_id) != bool(self.docmind_access_key_secret):
            raise ValueError("DocMind AccessKey ID and Secret must be provided together")
        return self


class SystemSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_size_limit_bytes: int
    page_limit: int
    batch_file_limit: int
    detailed_log_retention_days: int
    retain_daily_metrics: bool
    browser_session_days: int
    default_role: ExperienceRole
    updated_at: datetime
    docmind_configured: bool = False
    docmind_access_key_mask: str | None = None
    docmind_endpoint: str = "docmind-api.cn-hangzhou.aliyuncs.com"
