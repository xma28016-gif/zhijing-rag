"""Encrypted cloud OCR configuration. Compatible with existing and fresh databases."""

from sqlalchemy import inspect

from alembic import op

revision = "20261027_0003"
down_revision = "20261027_0002"
branch_labels = None
depends_on = None


def upgrade():
    existing = {item["name"] for item in inspect(op.get_bind()).get_columns("system_settings")}
    definitions = {
        "docmind_access_key_id_encrypted": "text",
        "docmind_access_key_secret_encrypted": "text",
        "docmind_access_key_mask": "varchar(100)",
        "docmind_endpoint": "varchar(255) NOT NULL DEFAULT 'docmind-api.cn-hangzhou.aliyuncs.com'",
    }
    for column, sql_type in definitions.items():
        if column not in existing:
            op.execute(f"ALTER TABLE system_settings ADD COLUMN {column} {sql_type}")


def downgrade():
    for column in (
        "docmind_access_key_id_encrypted",
        "docmind_access_key_secret_encrypted",
        "docmind_access_key_mask",
        "docmind_endpoint",
    ):
        op.execute(f"ALTER TABLE system_settings DROP COLUMN IF EXISTS {column}")
