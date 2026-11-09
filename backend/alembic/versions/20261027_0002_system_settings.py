"""Add singleton runtime system settings.

Revision ID: 20261027_0002
Revises: 20261026_0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from sqlalchemy import inspect, text

from alembic import op

revision: str = "20261027_0002"
down_revision: str | Sequence[str] | None = "20261026_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("system_settings"):
        op.execute("""
            CREATE TABLE system_settings (
                id integer PRIMARY KEY,
                file_size_limit_bytes integer NOT NULL DEFAULT 104857600,
                page_limit integer NOT NULL DEFAULT 500,
                batch_file_limit integer NOT NULL DEFAULT 20,
                detailed_log_retention_days integer NOT NULL DEFAULT 90,
                retain_daily_metrics boolean NOT NULL DEFAULT true,
                browser_session_days integer NOT NULL DEFAULT 30,
                default_role experience_role NOT NULL DEFAULT 'user',
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT system_settings_singleton CHECK (id = 1),
                CONSTRAINT system_file_size_positive CHECK (file_size_limit_bytes > 0),
                CONSTRAINT system_page_limit_positive CHECK (page_limit > 0),
                CONSTRAINT system_batch_limit_positive CHECK (batch_file_limit > 0),
                CONSTRAINT system_retention_positive CHECK (detailed_log_retention_days > 0),
                CONSTRAINT system_browser_days_positive CHECK (browser_session_days > 0)
            )
        """)
    bind.execute(
        text("""
        INSERT INTO system_settings (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING
    """)
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_settings")
