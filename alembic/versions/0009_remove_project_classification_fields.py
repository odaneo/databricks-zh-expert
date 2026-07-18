"""删除无业务意义的项目分类字段。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_drop_classification_fields"
down_revision: str | None = "0008_workspace_code_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_model_calls_workspace_mode", "model_calls", type_="check")
    op.drop_column("model_calls", "workspace_mode")
    op.drop_column("expert_templates", "is_mock")


def downgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("workspace_mode", sa.String(length=30), nullable=True),
    )
    op.execute(
        "UPDATE model_calls SET workspace_mode = 'greenfield' WHERE workspace_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_model_calls_workspace_mode",
        "model_calls",
        "workspace_mode IS NULL OR workspace_mode = 'greenfield'",
    )

    op.add_column(
        "expert_templates",
        sa.Column("is_mock", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE expert_templates SET is_mock = (layer <> 'core')")
    op.alter_column(
        "expert_templates",
        "is_mock",
        existing_type=sa.Boolean(),
        nullable=False,
    )
