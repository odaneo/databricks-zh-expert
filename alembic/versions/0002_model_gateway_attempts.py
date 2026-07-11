"""扩展模型调用尝试审计字段。"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_model_gateway_attempts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("invocation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("model_alias", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("attempt_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("retryable", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column("error_code", sa.String(length=100), nullable=True),
    )

    op.execute(
        """
        UPDATE model_calls
        SET invocation_id = id,
            model_alias = CASE model
                WHEN 'openai/gpt-5.5' THEN 'gpt5.5'
                WHEN 'openai/gpt-5.4-mini' THEN 'gpt5.4mini'
                WHEN 'deepseek/deepseek-v4-flash' THEN 'deepseek-v4-flash'
                WHEN 'deepseek/deepseek-v4-pro' THEN 'deepseek-v4-pro'
                ELSE model
            END,
            attempt_number = 1,
            retryable = false
        """
    )

    op.alter_column("model_calls", "invocation_id", nullable=False)
    op.alter_column("model_calls", "model_alias", nullable=False)
    op.alter_column("model_calls", "attempt_number", nullable=False)
    op.alter_column("model_calls", "retryable", nullable=False)
    op.create_check_constraint(
        "ck_model_calls_attempt_number",
        "model_calls",
        "attempt_number >= 1",
    )
    op.create_unique_constraint(
        "uq_model_calls_invocation_attempt",
        "model_calls",
        ["invocation_id", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_model_calls_invocation_attempt",
        "model_calls",
        type_="unique",
    )
    op.drop_constraint(
        "ck_model_calls_attempt_number",
        "model_calls",
        type_="check",
    )
    op.drop_column("model_calls", "error_code")
    op.drop_column("model_calls", "retryable")
    op.drop_column("model_calls", "attempt_number")
    op.drop_column("model_calls", "model_alias")
    op.drop_column("model_calls", "invocation_id")
