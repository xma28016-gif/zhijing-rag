"""Initial 1.0 domain schema and built-in provider templates.

Revision ID: 20261026_0001
Revises: None
Create Date: 2026-10-26
"""

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "20261026_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # PostgreSQL 17 supplies gen_random_uuid natively. Use frozen historical
    # schema so later ORM additions cannot silently rewrite this revision.
    statements = json.loads(Path(__file__).with_name("schema_0001.json").read_text())
    for statement in statements:
        op.execute(statement)
    bind.execute(
        text("""
        INSERT INTO model_providers
            (key, name, description, api_style, base_url, capabilities,
             configuration_schema, default_headers, is_builtin, enabled, sort_order)
        VALUES
            ('openrouter', 'OpenRouter', 'OpenAI-compatible model gateway',
             'openai_compatible', 'https://openrouter.ai/api/v1',
             jsonb_build_object('llm', true, 'embedding', true, 'rerank', true),
             '{}'::jsonb, '{}'::jsonb,
             true, true, 10),
            ('aihubmix', 'AIHubMix', 'OpenAI-compatible model gateway',
             'openai_compatible', 'https://aihubmix.com/v1',
             jsonb_build_object('llm', true, 'embedding', true, 'rerank', true),
             '{}'::jsonb, '{}'::jsonb,
             true, true, 20),
            ('tongyi', '通义百炼', 'Alibaba Cloud Model Studio',
             'openai_compatible', 'https://dashscope.aliyuncs.com/compatible-mode/v1',
             jsonb_build_object('llm', true, 'embedding', true, 'rerank', true),
             '{}'::jsonb, '{}'::jsonb,
             true, true, 30)
        ON CONFLICT (key) DO NOTHING
    """)
    )


def downgrade() -> None:
    statements = json.loads(Path(__file__).with_name("schema_0001.json").read_text())
    import re

    for statement in reversed(statements):
        match = re.match(r"\s*CREATE TABLE (\w+)", statement)
        if match:
            op.execute(f"DROP TABLE IF EXISTS {match.group(1)} CASCADE")
    op.execute("DROP TYPE IF EXISTS metric_scope")
    op.execute("DROP TYPE IF EXISTS api_key_status")
    op.execute("DROP TYPE IF EXISTS usage_accuracy")
    op.execute("DROP TYPE IF EXISTS run_step_kind")
    op.execute("DROP TYPE IF EXISTS run_status")
    op.execute("DROP TYPE IF EXISTS run_channel")
    op.execute("DROP TYPE IF EXISTS chat_role")
    op.execute("DROP TYPE IF EXISTS experience_role")
    op.execute("DROP TYPE IF EXISTS assistant_status")
    op.execute("DROP TYPE IF EXISTS chunk_kind")
    op.execute("DROP TYPE IF EXISTS build_task_type")
    op.execute("DROP TYPE IF EXISTS build_status")
    op.execute("DROP TYPE IF EXISTS parser_kind")
    op.execute("DROP TYPE IF EXISTS document_source_type")
    op.execute("DROP TYPE IF EXISTS knowledge_base_status")
    op.execute("DROP TYPE IF EXISTS validation_status")
    op.execute("DROP TYPE IF EXISTS model_kind")
