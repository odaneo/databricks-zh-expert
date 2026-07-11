"""迁移 Prompt 和 Artifact 审计字段。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_prompt_artifacts"
down_revision: str | None = "0002_model_gateway_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE messages SET artifact_type = 'answer' WHERE artifact_type = 'markdown'")
    )
    op.create_check_constraint(
        "ck_messages_artifact_type",
        "messages",
        "artifact_type IS NULL OR artifact_type IN "
        "('answer', 'sql', 'pyspark', 'workflow_design', "
        "'document_summary', 'proposal', 'checklist')",
    )
    op.add_column(
        "model_calls",
        sa.Column("prompt_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("artifact_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("artifact_valid", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("artifact_error_code", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_calls", "artifact_error_code")
    op.drop_column("model_calls", "artifact_valid")
    op.drop_column("model_calls", "artifact_type")
    op.drop_column("model_calls", "prompt_version")
    op.drop_column("model_calls", "prompt_name")
    op.drop_constraint(
        "ck_messages_artifact_type",
        "messages",
        type_="check",
    )
