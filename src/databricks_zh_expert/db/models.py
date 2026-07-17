from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from databricks_zh_expert.db.base import Base


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    expert_profile: Mapped[str] = mapped_column(
        String(100),
        default="generic",
        server_default=text("'generic'"),
        nullable=False,
    )
    workspace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_messages_role",
        ),
        CheckConstraint(
            "artifact_type IS NULL OR artifact_type IN "
            "('answer', 'sql', 'csv', 'pyspark', 'notebook', 'workflow_design', "
            "'document_summary', 'proposal', 'checklist')",
            name="ck_messages_artifact_type",
        ),
        Index("ix_messages_session_created_at", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_citations: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_model_calls_attempt_number"),
        CheckConstraint(
            "workspace_mode IS NULL OR workspace_mode = 'greenfield'",
            name="ck_model_calls_workspace_mode",
        ),
        CheckConstraint(
            "project_fact_status IS NULL OR project_fact_status = 'proposal'",
            name="ck_model_calls_project_fact_status",
        ),
        UniqueConstraint(
            "invocation_id",
            "attempt_number",
            name="uq_model_calls_invocation_attempt",
        ),
        Index("ix_model_calls_session_created_at", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    invocation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    artifact_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    artifact_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expert_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expert_template_selections: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    workspace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    workspace_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    workspace_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    workspace_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_context: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    project_fact_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('general_html', 'api_markdown', 'catalog_link')",
            name="ck_kb_documents_source_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_kb_documents_status",
        ),
        CheckConstraint("chunk_count >= 0", name="ck_kb_documents_chunk_count"),
        CheckConstraint(
            "missing_sync_count >= 0 AND missing_sync_count <= 2",
            name="ck_kb_documents_missing_sync_count",
        ),
        UniqueConstraint("source_key", name="uq_kb_documents_source_key"),
        Index("ix_kb_documents_catalog_id", "catalog_id"),
        Index("ix_kb_documents_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    catalog_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    cloud: Mapped[str] = mapped_column(String(20), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'active'"),
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    missing_sync_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    missing_since_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeChunkRecord(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_kb_chunks_chunk_index"),
        CheckConstraint("token_count > 0", name="ck_kb_chunks_token_count"),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_kb_chunks_document_chunk_index",
        ),
        Index("ix_kb_chunks_document_id", "document_id"),
        Index("ix_kb_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "kb_documents.id",
            ondelete="CASCADE",
            name="fk_kb_chunks_document_id",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeIngestionRun(Base):
    __tablename__ = "kb_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_kb_ingestion_runs_status",
        ),
        CheckConstraint(
            "discovered_count >= 0 AND changed_count >= 0 AND skipped_count >= 0 "
            "AND failed_count >= 0 AND chunk_count >= 0",
            name="ck_kb_ingestion_runs_counts",
        ),
        CheckConstraint(
            "embedding_dimensions > 0",
            name="ck_kb_ingestion_runs_embedding_dimensions",
        ),
        Index("ix_kb_ingestion_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    discovered_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    changed_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
        nullable=False,
    )
    error_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ExpertTemplateRecord(Base):
    __tablename__ = "expert_templates"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('blueprint', 'decision_guide', 'code_pattern', 'checklist', 'deliverable')",
            name="ck_expert_templates_kind",
        ),
        CheckConstraint(
            "category IN ('ingestion', 'medallion', 'pipeline', 'workflow', "
            "'governance', 'data_quality', 'sql', 'pyspark', 'performance', "
            "'cost', 'delivery')",
            name="ck_expert_templates_category",
        ),
        CheckConstraint(
            "cloud IN ('neutral', 'aws')",
            name="ck_expert_templates_cloud",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_expert_templates_status",
        ),
        CheckConstraint("chunk_count >= 0", name="ck_expert_templates_chunk_count"),
        UniqueConstraint(
            "template_id",
            "version",
            name="uq_expert_templates_template_version",
        ),
        Index(
            "ix_expert_templates_active_template_id",
            "template_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    layer: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cloud: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_names: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    extends_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "expert_templates.id",
            name="fk_expert_templates_extends_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    official_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'inactive'"),
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    inactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ExpertTemplateChunkRecord(Base):
    __tablename__ = "expert_template_chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_expert_template_chunks_chunk_index",
        ),
        CheckConstraint(
            "token_count > 0",
            name="ck_expert_template_chunks_token_count",
        ),
        UniqueConstraint(
            "template_record_id",
            "chunk_index",
            name="uq_expert_template_chunks_template_chunk_index",
        ),
        Index(
            "ix_expert_template_chunks_template_record_id",
            "template_record_id",
        ),
        Index(
            "ix_expert_template_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    template_record_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "expert_templates.id",
            name="fk_expert_template_chunks_template_record_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ExpertTemplateSyncRun(Base):
    __tablename__ = "expert_template_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_expert_template_sync_runs_status",
        ),
        CheckConstraint(
            "discovered_count >= 0 AND inserted_count >= 0 "
            "AND activated_count >= 0 AND inactivated_count >= 0 "
            "AND skipped_count >= 0 AND failed_count >= 0 AND chunk_count >= 0",
            name="ck_expert_template_sync_runs_counts",
        ),
        CheckConstraint(
            "embedding_dimensions > 0",
            name="ck_expert_template_sync_runs_embedding_dimensions",
        ),
        Index("ix_expert_template_sync_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    discovered_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    inserted_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    activated_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    inactivated_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    error_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
