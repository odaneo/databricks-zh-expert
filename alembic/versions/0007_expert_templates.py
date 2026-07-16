"""创建专家模板索引和审计字段。"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_expert_templates"
down_revision: str | None = "0006_catalog_link_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "expert_profile",
            sa.String(length=100),
            server_default=sa.text("'generic'"),
            nullable=False,
        ),
    )
    op.add_column(
        "model_calls",
        sa.Column("expert_profile", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "model_calls",
        sa.Column(
            "expert_template_selections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.create_table(
        "expert_template_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inactivated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "error_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_expert_template_sync_runs_status",
        ),
        sa.CheckConstraint(
            "discovered_count >= 0 AND inserted_count >= 0 "
            "AND activated_count >= 0 AND inactivated_count >= 0 "
            "AND skipped_count >= 0 AND failed_count >= 0 AND chunk_count >= 0",
            name="ck_expert_template_sync_runs_counts",
        ),
        sa.CheckConstraint(
            "embedding_dimensions > 0",
            name="ck_expert_template_sync_runs_embedding_dimensions",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_expert_template_sync_runs_started_at",
        "expert_template_sync_runs",
        ["started_at"],
    )

    op.create_table(
        "expert_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("layer", sa.String(length=100), nullable=False),
        sa.Column("profile_id", sa.String(length=100), nullable=True),
        sa.Column("cloud", sa.String(length=20), nullable=False),
        sa.Column(
            "prompt_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("extends_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column(
            "official_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'inactive'"),
            nullable=False,
        ),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("inactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('blueprint', 'decision_guide', 'code_pattern', 'checklist', 'deliverable')",
            name="ck_expert_templates_kind",
        ),
        sa.CheckConstraint(
            "category IN ('ingestion', 'medallion', 'pipeline', 'workflow', "
            "'governance', 'data_quality', 'sql', 'pyspark', 'performance', "
            "'cost', 'delivery')",
            name="ck_expert_templates_category",
        ),
        sa.CheckConstraint(
            "cloud IN ('neutral', 'aws')",
            name="ck_expert_templates_cloud",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_expert_templates_status",
        ),
        sa.CheckConstraint(
            "chunk_count >= 0",
            name="ck_expert_templates_chunk_count",
        ),
        sa.ForeignKeyConstraint(
            ["extends_id"],
            ["expert_templates.id"],
            name="fk_expert_templates_extends_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "version",
            name="uq_expert_templates_template_version",
        ),
    )
    op.create_index(
        "ix_expert_templates_active_template_id",
        "expert_templates",
        ["template_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "expert_template_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "heading_path",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_expert_template_chunks_chunk_index",
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name="ck_expert_template_chunks_token_count",
        ),
        sa.ForeignKeyConstraint(
            ["template_record_id"],
            ["expert_templates.id"],
            name="fk_expert_template_chunks_template_record_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_record_id",
            "chunk_index",
            name="uq_expert_template_chunks_template_chunk_index",
        ),
    )
    op.create_index(
        "ix_expert_template_chunks_template_record_id",
        "expert_template_chunks",
        ["template_record_id"],
    )
    op.create_index(
        "ix_expert_template_chunks_search_vector",
        "expert_template_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expert_template_chunks_search_vector",
        table_name="expert_template_chunks",
    )
    op.drop_index(
        "ix_expert_template_chunks_template_record_id",
        table_name="expert_template_chunks",
    )
    op.drop_table("expert_template_chunks")
    op.drop_index(
        "ix_expert_templates_active_template_id",
        table_name="expert_templates",
    )
    op.drop_table("expert_templates")
    op.drop_index(
        "ix_expert_template_sync_runs_started_at",
        table_name="expert_template_sync_runs",
    )
    op.drop_table("expert_template_sync_runs")
    op.drop_column("model_calls", "expert_template_selections")
    op.drop_column("model_calls", "expert_profile")
    op.drop_column("sessions", "expert_profile")
