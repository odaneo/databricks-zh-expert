import logging
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import inspect, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from databricks_zh_expert.core.config import get_settings

EXPECTED_TABLES = {"alembic_version", "sessions", "messages", "model_calls"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_initial_migration_creates_expected_tables(
    test_engine: AsyncEngine,
) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
        public_table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names(schema="public"))
        )
        model_call_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("model_calls")
            }
        )
        unique_constraints = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_unique_constraints("model_calls")
            }
        )
        check_constraints = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints("model_calls")
            }
        )
        message_check_constraints = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints("messages")
            }
        )

    assert EXPECTED_TABLES <= table_names
    assert public_table_names == set()
    assert model_call_columns["invocation_id"]["nullable"] is False
    assert model_call_columns["model_alias"]["nullable"] is False
    assert model_call_columns["attempt_number"]["nullable"] is False
    assert model_call_columns["retryable"]["nullable"] is False
    assert model_call_columns["error_code"]["nullable"] is True
    assert model_call_columns["prompt_name"]["nullable"] is True
    assert model_call_columns["prompt_version"]["nullable"] is True
    assert model_call_columns["artifact_type"]["nullable"] is True
    assert model_call_columns["artifact_valid"]["nullable"] is True
    assert model_call_columns["artifact_error_code"]["nullable"] is True
    assert "uq_model_calls_invocation_attempt" in unique_constraints
    assert "ck_model_calls_attempt_number" in check_constraints
    assert "ck_messages_artifact_type" in message_check_constraints


@pytest.mark.integration
@pytest.mark.asyncio
async def test_test_database_uses_expected_pgvector_version(
    test_engine: AsyncEngine,
) -> None:
    async with test_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    assert result.scalar_one() == "0.8.5"


@pytest.mark.integration
def test_alembic_commands_preserve_application_loggers(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    logger = logging.getLogger("databricks_zh_expert.observability.model_trace")
    original_disabled = logger.disabled
    logger.disabled = False

    try:
        command.current(Config("alembic.ini"))

        assert logger.disabled is False
    finally:
        logger.disabled = original_disabled
        get_settings.cache_clear()


@pytest.mark.integration
def test_model_gateway_migration_backfills_historical_calls(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    sync_database_url = (
        make_url(test_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    session_id = uuid4()
    known_call_id = uuid4()
    legacy_call_id = uuid4()

    try:
        command.downgrade(config, "0001_initial")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sessions (id, title) VALUES (%s, %s)",
                    (session_id, "迁移回填测试"),
                )
                cursor.executemany(
                    """
                    INSERT INTO model_calls (
                        id,
                        session_id,
                        provider,
                        model,
                        prompt_tokens,
                        completion_tokens,
                        latency_ms,
                        success,
                        error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            known_call_id,
                            session_id,
                            "openai",
                            "openai/gpt-5.5",
                            10,
                            4,
                            120,
                            True,
                            None,
                        ),
                        (
                            legacy_call_id,
                            session_id,
                            "custom",
                            "custom/legacy-model",
                            None,
                            None,
                            300,
                            False,
                            "历史错误摘要",
                        ),
                    ],
                )

        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        invocation_id,
                        model_alias,
                        attempt_number,
                        retryable,
                        error_code
                    FROM model_calls
                    WHERE id IN (%s, %s)
                    """,
                    (known_call_id, legacy_call_id),
                )
                rows = {
                    row[0]: {
                        "invocation_id": row[1],
                        "model_alias": row[2],
                        "attempt_number": row[3],
                        "retryable": row[4],
                        "error_code": row[5],
                    }
                    for row in cursor.fetchall()
                }

        assert rows == {
            known_call_id: {
                "invocation_id": known_call_id,
                "model_alias": "gpt5.5",
                "attempt_number": 1,
                "retryable": False,
                "error_code": None,
            },
            legacy_call_id: {
                "invocation_id": legacy_call_id,
                "model_alias": "custom/legacy-model",
                "attempt_number": 1,
                "retryable": False,
                "error_code": None,
            },
        }
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        get_settings.cache_clear()


@pytest.mark.integration
def test_prompt_artifact_migration_backfills_historical_records(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    sync_database_url = (
        make_url(test_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    session_id = uuid4()
    message_id = uuid4()
    model_call_id = uuid4()
    invalid_message_id = uuid4()

    try:
        command.downgrade(config, "0002_model_gateway_attempts")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sessions (id, title) VALUES (%s, %s)",
                    (session_id, "Prompt Artifact 迁移测试"),
                )
                cursor.execute(
                    """
                    INSERT INTO messages (
                        id,
                        session_id,
                        role,
                        content,
                        artifact_type
                    )
                    VALUES (%s, %s, 'assistant', '# 历史回答', 'markdown')
                    """,
                    (message_id, session_id),
                )
                cursor.execute(
                    """
                    INSERT INTO model_calls (
                        id,
                        session_id,
                        invocation_id,
                        provider,
                        model,
                        model_alias,
                        attempt_number,
                        latency_ms,
                        success,
                        retryable
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        model_call_id,
                        session_id,
                        model_call_id,
                        "openai",
                        "openai/gpt-5.5",
                        "gpt5.5",
                        1,
                        120,
                        True,
                        False,
                    ),
                )

        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT artifact_type FROM messages WHERE id = %s",
                    (message_id,),
                )
                migrated_artifact_type = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT
                        prompt_name,
                        prompt_version,
                        artifact_type,
                        artifact_valid,
                        artifact_error_code
                    FROM model_calls
                    WHERE id = %s
                    """,
                    (model_call_id,),
                )
                historical_audit = cursor.fetchone()

        assert migrated_artifact_type == ("answer",)
        assert historical_audit == (None, None, None, None, None)

        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(sync_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO messages (
                            id,
                            session_id,
                            role,
                            content,
                            artifact_type
                        )
                        VALUES (%s, %s, 'assistant', '# 非法回答', 'unknown')
                        """,
                        (invalid_message_id, session_id),
                    )
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        get_settings.cache_clear()
