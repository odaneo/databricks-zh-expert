from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from pgvector.sqlalchemy import Vector
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint
from sqlalchemy.schema import DefaultClause

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.chat.schemas import MessageResponse
from databricks_zh_expert.db.base import Base
from databricks_zh_expert.db.models import (
    ChatSession,
    ExpertTemplateChunkRecord,
    ExpertTemplateRecord,
    ExpertTemplateSyncRun,
    KnowledgeChunkRecord,
    KnowledgeDocument,
    KnowledgeIngestionRun,
    Message,
    ModelCall,
)


def test_message_response_uses_the_fixed_artifact_catalog() -> None:
    message_id = uuid4()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    response = MessageResponse.model_validate(
        {
            "id": message_id,
            "role": "assistant",
            "content": "```sql\nSELECT 1;\n```",
            "artifact_type": "sql",
            "created_at": created_at,
        }
    )

    assert response.artifact_type is ArtifactType.SQL
    with pytest.raises(ValidationError):
        MessageResponse.model_validate(
            {
                "id": message_id,
                "role": "assistant",
                "content": "历史回答",
                "artifact_type": "markdown",
                "created_at": created_at,
            }
        )


def test_models_register_expected_tables_and_columns() -> None:
    assert set(Base.metadata.tables) == {
        "sessions",
        "messages",
        "model_calls",
        "kb_documents",
        "kb_chunks",
        "kb_ingestion_runs",
        "expert_templates",
        "expert_template_chunks",
        "expert_template_sync_runs",
    }
    assert set(ChatSession.__table__.columns.keys()) == {
        "id",
        "title",
        "expert_profile",
        "workspace_id",
        "created_at",
        "updated_at",
    }
    assert set(Message.__table__.columns.keys()) == {
        "id",
        "session_id",
        "role",
        "content",
        "artifact_type",
        "source_citations",
        "created_at",
    }
    assert set(ModelCall.__table__.columns.keys()) == {
        "id",
        "session_id",
        "invocation_id",
        "provider",
        "model",
        "model_alias",
        "attempt_number",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "success",
        "retryable",
        "error_code",
        "prompt_name",
        "prompt_version",
        "artifact_type",
        "artifact_valid",
        "artifact_error_code",
        "expert_profile",
        "expert_template_selections",
        "workspace_id",
        "workspace_version",
        "workspace_source_hash",
        "workspace_context",
        "project_fact_status",
        "error_message",
        "created_at",
    }
    assert set(KnowledgeDocument.__table__.columns.keys()) == {
        "id",
        "source_key",
        "catalog_id",
        "source_kind",
        "title",
        "source_url",
        "canonical_url",
        "category",
        "cloud",
        "locale",
        "normalized_content",
        "content_hash",
        "etag",
        "last_modified",
        "status",
        "chunk_count",
        "missing_sync_count",
        "missing_since_at",
        "source_updated_at",
        "fetched_at",
        "created_at",
        "updated_at",
    }
    assert set(KnowledgeChunkRecord.__table__.columns.keys()) == {
        "id",
        "document_id",
        "chunk_index",
        "heading_path",
        "content",
        "content_hash",
        "token_count",
        "source_ref",
        "metadata",
        "embedding",
        "embedding_model",
        "search_vector",
        "created_at",
    }
    assert set(KnowledgeIngestionRun.__table__.columns.keys()) == {
        "id",
        "status",
        "manifest_hash",
        "embedding_model",
        "embedding_dimensions",
        "discovered_count",
        "changed_count",
        "skipped_count",
        "failed_count",
        "chunk_count",
        "error_summary",
        "started_at",
        "completed_at",
    }
    assert set(ExpertTemplateRecord.__table__.columns.keys()) == {
        "id",
        "template_id",
        "version",
        "name",
        "summary",
        "kind",
        "category",
        "layer",
        "profile_id",
        "cloud",
        "prompt_names",
        "tags",
        "extends_id",
        "official_refs",
        "source_path",
        "content",
        "content_hash",
        "status",
        "chunk_count",
        "created_at",
        "updated_at",
        "inactivated_at",
    }
    assert set(ExpertTemplateChunkRecord.__table__.columns.keys()) == {
        "id",
        "template_record_id",
        "chunk_index",
        "heading_path",
        "content",
        "content_hash",
        "token_count",
        "embedding",
        "embedding_model",
        "search_vector",
        "created_at",
    }
    assert set(ExpertTemplateSyncRun.__table__.columns.keys()) == {
        "id",
        "status",
        "source_hash",
        "embedding_model",
        "embedding_dimensions",
        "discovered_count",
        "inserted_count",
        "activated_count",
        "inactivated_count",
        "skipped_count",
        "failed_count",
        "chunk_count",
        "error_summary",
        "started_at",
        "completed_at",
    }


def test_expert_template_models_enforce_storage_contract() -> None:
    template_table = cast(Table, ExpertTemplateRecord.__table__)
    chunk_table = cast(Table, ExpertTemplateChunkRecord.__table__)
    run_table = cast(Table, ExpertTemplateSyncRun.__table__)

    assert ChatSession.__table__.c.expert_profile.nullable is False
    assert ChatSession.__table__.c.workspace_id.nullable is True
    session_profile_default = ChatSession.__table__.c.expert_profile.server_default
    assert isinstance(session_profile_default, DefaultClause)
    assert str(session_profile_default.arg) == "'generic'"
    assert ModelCall.__table__.c.expert_profile.nullable is True
    assert ModelCall.__table__.c.expert_template_selections.nullable is True
    assert ModelCall.__table__.c.workspace_id.nullable is True
    assert ModelCall.__table__.c.workspace_context.nullable is True
    assert ModelCall.__table__.c.project_fact_status.nullable is True
    embedding_type = cast(Vector, ExpertTemplateChunkRecord.__table__.c.embedding.type)
    assert embedding_type.dim == 1536
    assert ExpertTemplateChunkRecord.__table__.c.search_vector.computed is not None

    json_array_columns = (
        template_table.c.prompt_names,
        template_table.c.tags,
        template_table.c.official_refs,
        chunk_table.c.heading_path,
        run_table.c.error_summary,
    )
    for column in json_array_columns:
        assert column.nullable is False
        assert column.default is not None and column.default.is_callable
        assert isinstance(column.server_default, DefaultClause)
        assert str(column.server_default.arg) == "'[]'::jsonb"

    template_constraints = {constraint.name for constraint in template_table.constraints}
    assert {
        "ck_expert_templates_kind",
        "ck_expert_templates_category",
        "ck_expert_templates_cloud",
        "ck_expert_templates_status",
        "ck_expert_templates_chunk_count",
        "uq_expert_templates_template_version",
        "fk_expert_templates_extends_id",
    } <= template_constraints
    extends_foreign_key = next(
        constraint
        for constraint in template_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_expert_templates_extends_id"
    )
    assert extends_foreign_key.ondelete == "RESTRICT"

    active_index = next(
        index
        for index in template_table.indexes
        if index.name == "ix_expert_templates_active_template_id"
    )
    assert active_index.unique is True
    assert str(active_index.dialect_options["postgresql"]["where"]) == ("status = 'active'")
    assert {index.name for index in chunk_table.indexes} == {
        "ix_expert_template_chunks_template_record_id",
        "ix_expert_template_chunks_search_vector",
    }


def test_knowledge_document_supports_catalog_link_sources() -> None:
    document_table = cast(Table, KnowledgeDocument.__table__)
    source_kind_constraint = next(
        constraint
        for constraint in document_table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_kb_documents_source_kind"
    )

    assert KnowledgeDocument.__table__.c.catalog_id.nullable is False
    assert str(source_kind_constraint.sqltext) == (
        "source_kind IN ('general_html', 'api_markdown', 'catalog_link')"
    )
    assert "ix_kb_documents_catalog_id" in {index.name for index in document_table.indexes}


def test_message_model_enforces_roles_and_session_ordering() -> None:
    message_table = cast(Table, Message.__table__)
    constraints = message_table.constraints
    check_constraints = {
        constraint.name: constraint
        for constraint in constraints
        if isinstance(constraint, CheckConstraint)
    }
    session_foreign_key = next(
        constraint for constraint in constraints if isinstance(constraint, ForeignKeyConstraint)
    )

    assert str(check_constraints["ck_messages_role"].sqltext) == (
        "role IN ('system', 'user', 'assistant')"
    )
    assert str(check_constraints["ck_messages_artifact_type"].sqltext) == (
        "artifact_type IS NULL OR artifact_type IN "
        "('answer', 'sql', 'csv', 'pyspark', 'notebook', 'workflow_design', "
        "'document_summary', 'proposal', 'checklist')"
    )
    assert session_foreign_key.ondelete == "CASCADE"
    assert {index.name for index in message_table.indexes} == {"ix_messages_session_created_at"}


def test_model_call_model_cascades_and_indexes_by_session_time() -> None:
    model_call_table = cast(Table, ModelCall.__table__)
    session_foreign_key = next(
        constraint
        for constraint in model_call_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )

    assert session_foreign_key.ondelete == "CASCADE"
    constraint_names = {constraint.name for constraint in model_call_table.constraints}
    assert "uq_model_calls_invocation_attempt" in constraint_names
    assert "ck_model_calls_attempt_number" in constraint_names
    assert "ck_model_calls_workspace_mode" not in constraint_names
    assert "ck_model_calls_project_fact_status" in constraint_names
    attempt_constraint = next(
        constraint
        for constraint in model_call_table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_model_calls_attempt_number"
    )
    invocation_constraint = next(
        constraint
        for constraint in model_call_table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_model_calls_invocation_attempt"
    )

    assert str(attempt_constraint.sqltext) == "attempt_number >= 1"
    assert [column.name for column in invocation_constraint.columns] == [
        "invocation_id",
        "attempt_number",
    ]
    assert {index.name for index in model_call_table.indexes} == {
        "ix_model_calls_session_created_at"
    }
