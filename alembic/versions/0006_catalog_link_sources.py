"""增加目录链接来源和文档目录身份。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_catalog_link_sources"
down_revision: str | None = "0005_knowledge_catalog_presence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kb_documents",
        sa.Column("catalog_id", sa.String(length=100), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE kb_documents
            SET catalog_id = CASE
                WHEN source_kind = 'api_markdown'
                  OR source_key LIKE 'databricks-api-%'
                THEN 'databricks-api'
                ELSE 'databricks-docs'
            END
            """
        )
    )
    op.alter_column(
        "kb_documents",
        "catalog_id",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.drop_constraint(
        "ck_kb_documents_source_kind",
        "kb_documents",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE kb_documents
            SET source_kind = 'catalog_link'
            WHERE source_url !~ '^https://docs[.]databricks[.]com(?:/|$)'
            """
        )
    )
    op.create_check_constraint(
        "ck_kb_documents_source_kind",
        "kb_documents",
        "source_kind IN ('general_html', 'api_markdown', 'catalog_link')",
    )
    op.create_index(
        "ix_kb_documents_catalog_id",
        "kb_documents",
        ["catalog_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_kb_documents_source_kind",
        "kb_documents",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE kb_documents
            SET source_kind = CASE
                WHEN catalog_id = 'databricks-api' THEN 'api_markdown'
                ELSE 'general_html'
            END
            WHERE source_kind = 'catalog_link'
            """
        )
    )
    op.create_check_constraint(
        "ck_kb_documents_source_kind",
        "kb_documents",
        "source_kind IN ('general_html', 'api_markdown')",
    )
    op.drop_index("ix_kb_documents_catalog_id", table_name="kb_documents")
    op.drop_column("kb_documents", "catalog_id")
