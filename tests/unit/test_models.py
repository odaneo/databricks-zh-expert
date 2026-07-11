from typing import cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from databricks_zh_expert.db.base import Base
from databricks_zh_expert.db.models import ChatSession, Message, ModelCall


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
        "error_message",
        "created_at",
    }


def test_message_model_enforces_roles_and_session_ordering() -> None:
    message_table = cast(Table, Message.__table__)
    constraints = message_table.constraints
    role_constraint = next(
        constraint for constraint in constraints if isinstance(constraint, CheckConstraint)
    )
    session_foreign_key = next(
        constraint for constraint in constraints if isinstance(constraint, ForeignKeyConstraint)
    )

    assert role_constraint.name == "ck_messages_role"
    assert str(role_constraint.sqltext) == "role IN ('system', 'user', 'assistant')"
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
