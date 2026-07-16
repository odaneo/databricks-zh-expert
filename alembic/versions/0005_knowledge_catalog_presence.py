"""增加知识目录连续缺失确认状态。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_knowledge_catalog_presence"
down_revision: str | None = "0004_knowledge_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column(
            "missing_sync_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "kb_documents",
        sa.Column("missing_since_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_kb_documents_missing_sync_count",
        "kb_documents",
        "missing_sync_count >= 0 AND missing_sync_count <= 2",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_kb_documents_missing_sync_count",
        "kb_documents",
        type_="check",
    )
    op.drop_column("kb_documents", "missing_since_at")
    op.drop_column("kb_documents", "missing_sync_count")
