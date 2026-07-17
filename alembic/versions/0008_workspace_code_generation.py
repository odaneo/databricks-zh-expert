"""增加 Greenfield Workspace 与代码提案审计字段。"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_workspace_code_generation"
down_revision: str | None = "0007_expert_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTIFACT_CONSTRAINT = (
    "artifact_type IS NULL OR artifact_type IN "
    "('answer', 'sql', 'csv', 'pyspark', 'notebook', 'workflow_design', "
    "'document_summary', 'proposal', 'checklist')"
)
_PREVIOUS_ARTIFACT_CONSTRAINT = (
    "artifact_type IS NULL OR artifact_type IN "
    "('answer', 'sql', 'pyspark', 'workflow_design', "
    "'document_summary', 'proposal', 'checklist')"
)


def upgrade() -> None:
    op.drop_constraint("ck_messages_artifact_type", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_artifact_type",
        "messages",
        _ARTIFACT_CONSTRAINT,
    )
    op.add_column(
        "sessions",
        sa.Column("workspace_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("workspace_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("workspace_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("workspace_mode", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("workspace_source_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("workspace_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("project_fact_status", sa.String(length=30), nullable=True),
    )
    op.create_check_constraint(
        "ck_model_calls_workspace_mode",
        "model_calls",
        "workspace_mode IS NULL OR workspace_mode = 'greenfield'",
    )
    op.create_check_constraint(
        "ck_model_calls_project_fact_status",
        "model_calls",
        "project_fact_status IS NULL OR project_fact_status = 'proposal'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_calls_project_fact_status",
        "model_calls",
        type_="check",
    )
    op.drop_constraint("ck_model_calls_workspace_mode", "model_calls", type_="check")
    op.drop_column("model_calls", "project_fact_status")
    op.drop_column("model_calls", "workspace_context")
    op.drop_column("model_calls", "workspace_source_hash")
    op.drop_column("model_calls", "workspace_mode")
    op.drop_column("model_calls", "workspace_version")
    op.drop_column("model_calls", "workspace_id")
    op.drop_column("sessions", "workspace_id")
    op.drop_constraint("ck_messages_artifact_type", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_artifact_type",
        "messages",
        _PREVIOUS_ARTIFACT_CONSTRAINT,
    )
