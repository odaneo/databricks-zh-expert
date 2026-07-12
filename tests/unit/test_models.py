from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.chat.schemas import MessageResponse
from databricks_zh_expert.db.base import Base
from databricks_zh_expert.db.models import ChatSession, Message, ModelCall


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
    assert set(Base.metadata.tables) == {"sessions", "messages", "model_calls"}
    assert set(ChatSession.__table__.columns.keys()) == {
        "id",
        "title",
        "created_at",
        "updated_at",
    }
    assert set(Message.__table__.columns.keys()) == {
        "id",
        "session_id",
        "role",
        "content",
        "artifact_type",
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
        "error_message",
        "created_at",
    }


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
        "('answer', 'sql', 'pyspark', 'workflow_design', "
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
