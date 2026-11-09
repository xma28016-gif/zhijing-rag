"""Allow display names to be shared across model types and providers."""

from sqlalchemy import text

from alembic import op

revision = "20261027_0004"
down_revision = "20261027_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_model_configs_name", "model_configs", type_="unique")
    op.create_unique_constraint(
        "uq_model_configs_provider_kind_name", "model_configs", ["provider_id", "kind", "name"]
    )


def downgrade():
    duplicate = (
        op.get_bind()
        .execute(text("SELECT name FROM model_configs GROUP BY name HAVING count(*) > 1 LIMIT 1"))
        .first()
    )
    if duplicate:
        raise RuntimeError("存在跨类型或服务商的同名模型，请先重命名再回退此迁移。")
    op.drop_constraint("uq_model_configs_provider_kind_name", "model_configs", type_="unique")
    op.create_unique_constraint("uq_model_configs_name", "model_configs", ["name"])
