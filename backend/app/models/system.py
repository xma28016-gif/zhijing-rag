"""Runtime settings shared by API and background workers."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ExperienceRole, database_enum
from app.models.mixins import TimestampMixin


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="system_settings_singleton"),
        CheckConstraint("file_size_limit_bytes > 0", name="system_file_size_positive"),
        CheckConstraint("page_limit > 0", name="system_page_limit_positive"),
        CheckConstraint("batch_file_limit > 0", name="system_batch_limit_positive"),
        CheckConstraint("detailed_log_retention_days > 0", name="system_retention_positive"),
        CheckConstraint("browser_session_days > 0", name="system_browser_days_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    docmind_access_key_id_encrypted: Mapped[str | None] = mapped_column(Text)
    docmind_access_key_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    docmind_access_key_mask: Mapped[str | None] = mapped_column(String(100))
    docmind_endpoint: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="docmind-api.cn-hangzhou.aliyuncs.com",
        server_default=text("'docmind-api.cn-hangzhou.aliyuncs.com'"),
    )
    file_size_limit_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100 * 1024 * 1024,
        server_default=text(str(100 * 1024 * 1024)),
    )
    page_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500, server_default=text("500"))
    batch_file_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default=text("20")
    )
    detailed_log_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90")
    )
    retain_daily_metrics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    browser_session_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    default_role: Mapped[ExperienceRole] = mapped_column(
        database_enum(ExperienceRole, name="experience_role"),
        nullable=False,
        default=ExperienceRole.USER,
        server_default=text("'user'"),
    )
