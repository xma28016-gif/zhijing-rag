"""Persist evaluation datasets and immutable online run snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261029_0005"
down_revision = "20261027_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "evaluation_samples",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "dataset_id",
            sa.UUID(),
            sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_run_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(10), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("ready_confirmed", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dataset_id", "source_run_id", name="uq_evaluation_sample_source"),
        sa.CheckConstraint("label IN ('good', 'bad')", name="ck_evaluation_samples_label_valid"),
        sa.CheckConstraint(
            "state IN ('draft', 'ready', 'archived')", name="ck_evaluation_samples_state_valid"
        ),
        sa.CheckConstraint("scope IN ('turn', 'history')", name="ck_evaluation_samples_scope_valid"),
        sa.CheckConstraint("revision >= 1", name="ck_evaluation_samples_revision_positive"),
    )
    op.create_index(
        "ix_evaluation_samples_dataset_created", "evaluation_samples", ["dataset_id", "created_at"]
    )


def downgrade():
    op.drop_table("evaluation_samples")
    op.drop_table("evaluation_datasets")
