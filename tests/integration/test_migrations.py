import logging
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import inspect, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from databricks_zh_expert.core.config import get_settings

EXPECTED_TABLES = {
    "alembic_version",
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
        session_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("sessions")
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
    assert session_columns["expert_profile"]["nullable"] is False
    assert session_columns["workspace_id"]["nullable"] is True
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
    assert model_call_columns["expert_profile"]["nullable"] is True
    assert model_call_columns["expert_template_selections"]["nullable"] is True
    assert model_call_columns["workspace_id"]["nullable"] is True
    assert model_call_columns["workspace_version"]["nullable"] is True
    assert model_call_columns["workspace_mode"]["nullable"] is True
    assert model_call_columns["workspace_source_hash"]["nullable"] is True
    assert model_call_columns["workspace_context"]["nullable"] is True
    assert model_call_columns["project_fact_status"]["nullable"] is True
    assert "uq_model_calls_invocation_attempt" in unique_constraints
    assert "ck_model_calls_attempt_number" in check_constraints
    assert "ck_model_calls_workspace_mode" in check_constraints
    assert "ck_model_calls_project_fact_status" in check_constraints
    assert "ck_messages_artifact_type" in message_check_constraints


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expert_template_schema_contract(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        template_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("expert_templates")
            }
        )
        chunk_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("expert_template_chunks")
            }
        )
        template_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints("expert_templates")
            }
        )
        chunk_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints(
                    "expert_template_chunks"
                )
            }
        )
        run_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints(
                    "expert_template_sync_runs"
                )
            }
        )
        template_unique_constraints = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_unique_constraints(
                    "expert_templates"
                )
            }
        )
        template_foreign_keys = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_foreign_keys("expert_templates")
        )
        chunk_foreign_keys = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_foreign_keys(
                "expert_template_chunks"
            )
        )
        index_rows = await connection.execute(
            text(
                """
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename IN ('expert_templates', 'expert_template_chunks')
                ORDER BY tablename, indexname
                """
            )
        )

    index_definitions = {
        (table_name, index_name): definition
        for table_name, index_name, definition in index_rows.all()
    }
    rendered_indexes = "\n".join(index_definitions.values()).lower()

    assert template_columns["profile_id"]["nullable"] is True
    assert template_columns["extends_id"]["nullable"] is True
    assert template_columns["inactivated_at"]["nullable"] is True
    assert str(template_columns["prompt_names"]["type"]).upper() == "JSONB"
    assert str(chunk_columns["embedding"]["type"]).upper() == "VECTOR(1536)"
    assert str(chunk_columns["search_vector"]["type"]).upper() == "TSVECTOR"
    assert {
        "ck_expert_templates_kind",
        "ck_expert_templates_category",
        "ck_expert_templates_cloud",
        "ck_expert_templates_status",
        "ck_expert_templates_chunk_count",
    } <= template_checks
    assert {
        "ck_expert_template_chunks_chunk_index",
        "ck_expert_template_chunks_token_count",
    } <= chunk_checks
    assert {
        "ck_expert_template_sync_runs_status",
        "ck_expert_template_sync_runs_counts",
        "ck_expert_template_sync_runs_embedding_dimensions",
    } <= run_checks
    assert "uq_expert_templates_template_version" in template_unique_constraints
    assert template_foreign_keys == [
        {
            "name": "fk_expert_templates_extends_id",
            "constrained_columns": ["extends_id"],
            "referred_schema": None,
            "referred_table": "expert_templates",
            "referred_columns": ["id"],
            "options": {"ondelete": "RESTRICT"},
            "comment": None,
        }
    ]
    assert chunk_foreign_keys == [
        {
            "name": "fk_expert_template_chunks_template_record_id",
            "constrained_columns": ["template_record_id"],
            "referred_schema": None,
            "referred_table": "expert_templates",
            "referred_columns": ["id"],
            "options": {"ondelete": "CASCADE"},
            "comment": None,
        }
    ]
    active_index = index_definitions[
        ("expert_templates", "ix_expert_templates_active_template_id")
    ].lower()
    assert "unique index" in active_index
    assert "where" in active_index and "active" in active_index
    assert (
        "expert_template_chunks",
        "ix_expert_template_chunks_search_vector",
    ) in index_definitions
    assert (
        "using gin"
        in index_definitions[
            ("expert_template_chunks", "ix_expert_template_chunks_search_vector")
        ].lower()
    )
    assert "hnsw" not in rendered_indexes
    assert "ivfflat" not in rendered_indexes


@pytest.mark.integration
def test_expert_template_migration_preserves_history_and_round_trips(
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
    model_call_id = uuid4()

    try:
        command.downgrade(config, "0006_catalog_link_sources")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sessions (id, title) VALUES (%s, %s)",
                    (session_id, "专家模板迁移保护测试"),
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
                    VALUES (%s, %s, %s, 'deepseek', %s, %s, 1, 42, true, false)
                    """,
                    (
                        model_call_id,
                        session_id,
                        model_call_id,
                        "deepseek/deepseek-v4-flash",
                        "deepseek-v4-flash",
                    ),
                )

        for _ in range(2):
            command.upgrade(config, "head")
            with psycopg.connect(sync_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT expert_profile FROM sessions WHERE id = %s",
                        (session_id,),
                    )
                    assert cursor.fetchone() == ("generic",)
                    cursor.execute(
                        """
                        SELECT expert_profile, expert_template_selections
                        FROM model_calls
                        WHERE id = %s
                        """,
                        (model_call_id,),
                    )
                    assert cursor.fetchone() == (None, None)
                    cursor.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_name LIKE 'expert_template%'
                        ORDER BY table_name
                        """
                    )
                    assert {row[0] for row in cursor.fetchall()} == {
                        "expert_template_chunks",
                        "expert_template_sync_runs",
                        "expert_templates",
                    }

            command.downgrade(config, "0006_catalog_link_sources")
            with psycopg.connect(sync_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_name LIKE 'expert_template%'
                        """
                    )
                    assert cursor.fetchall() == []
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND (
                            (table_name = 'sessions' AND column_name = 'expert_profile')
                            OR (
                              table_name = 'model_calls'
                              AND column_name IN (
                                'expert_profile',
                                'expert_template_selections'
                              )
                            )
                          )
                        """
                    )
                    assert cursor.fetchall() == []
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        get_settings.cache_clear()


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
@pytest.mark.asyncio
async def test_knowledge_rag_schema_contract(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        message_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("messages")
            }
        )
        document_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("kb_documents")
            }
        )
        chunk_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in inspect(sync_connection).get_columns("kb_chunks")
            }
        )
        document_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints("kb_documents")
            }
        )
        chunk_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints("kb_chunks")
            }
        )
        run_checks = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_check_constraints(
                    "kb_ingestion_runs"
                )
            }
        )
        chunk_unique_constraints = await connection.run_sync(
            lambda sync_connection: {
                constraint["name"]
                for constraint in inspect(sync_connection).get_unique_constraints("kb_chunks")
            }
        )
        chunk_foreign_keys = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_foreign_keys("kb_chunks")
        )
        index_rows = await connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'kb_chunks'
                ORDER BY indexname
                """
            )
        )

    index_definitions = {name: definition for name, definition in index_rows.all()}
    rendered_indexes = "\n".join(index_definitions.values()).lower()

    assert message_columns["source_citations"]["nullable"] is True
    assert str(message_columns["source_citations"]["type"]).upper() == "JSONB"
    assert document_columns["normalized_content"]["nullable"] is False
    assert document_columns["content_hash"]["nullable"] is False
    assert document_columns["etag"]["nullable"] is True
    assert document_columns["last_modified"]["nullable"] is True
    assert document_columns["missing_sync_count"]["nullable"] is False
    assert document_columns["missing_since_at"]["nullable"] is True
    assert document_columns["source_updated_at"]["nullable"] is True
    assert document_columns["fetched_at"]["nullable"] is False
    assert str(chunk_columns["embedding"]["type"]).upper() == "VECTOR(1536)"
    assert str(chunk_columns["search_vector"]["type"]).upper() == "TSVECTOR"
    assert "ck_kb_documents_status" in document_checks
    assert "ck_kb_documents_chunk_count" in document_checks
    assert "ck_kb_documents_missing_sync_count" in document_checks
    assert "ck_kb_chunks_chunk_index" in chunk_checks
    assert "ck_kb_chunks_token_count" in chunk_checks
    assert "ck_kb_ingestion_runs_status" in run_checks
    assert "ck_kb_ingestion_runs_counts" in run_checks
    assert "uq_kb_chunks_document_chunk_index" in chunk_unique_constraints
    assert chunk_foreign_keys == [
        {
            "name": "fk_kb_chunks_document_id",
            "constrained_columns": ["document_id"],
            "referred_schema": None,
            "referred_table": "kb_documents",
            "referred_columns": ["id"],
            "options": {"ondelete": "CASCADE"},
            "comment": None,
        }
    ]
    assert "ix_kb_chunks_search_vector" in index_definitions
    assert "using gin" in index_definitions["ix_kb_chunks_search_vector"].lower()
    assert "hnsw" not in rendered_indexes
    assert "ivfflat" not in rendered_indexes


@pytest.mark.integration
def test_catalog_presence_migration_preserves_existing_knowledge_document(
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
    document_id = uuid4()

    try:
        command.downgrade(config, "0004_knowledge_rag")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_documents (
                        id,
                        source_key,
                        source_kind,
                        title,
                        source_url,
                        canonical_url,
                        category,
                        cloud,
                        locale,
                        normalized_content,
                        content_hash,
                        status,
                        chunk_count,
                        fetched_at
                    )
                    VALUES (
                        %s,
                        'docs-before-0005',
                        'general_html',
                        '迁移前文档',
                        'https://docs.databricks.com/migration-test/',
                        'https://docs.databricks.com/migration-test/',
                        'general',
                        'aws',
                        'en',
                        '# 迁移前文档',
                        %s,
                        'active',
                        0,
                        now()
                    )
                    """,
                    (document_id, "f" * 64),
                )

        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, source_key, status, missing_sync_count, missing_since_at
                    FROM kb_documents
                    WHERE id = %s
                    """,
                    (document_id,),
                )
                migrated = cursor.fetchone()

        assert migrated == (
            document_id,
            "docs-before-0005",
            "active",
            0,
            None,
        )
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM kb_documents WHERE id = %s", (document_id,))
        get_settings.cache_clear()


@pytest.mark.integration
def test_catalog_link_migration_backfills_existing_document_catalogs(
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
    docs_document_id = uuid4()
    api_document_id = uuid4()

    try:
        command.downgrade(config, "0005_knowledge_catalog_presence")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO kb_documents (
                        id,
                        source_key,
                        source_kind,
                        title,
                        source_url,
                        canonical_url,
                        category,
                        cloud,
                        locale,
                        normalized_content,
                        content_hash,
                        status,
                        chunk_count,
                        fetched_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'aws', 'en', %s, %s,
                            'active', 0, now())
                    """,
                    (
                        (
                            docs_document_id,
                            "databricks-docs-before-0006",
                            "general_html",
                            "Docs migration source",
                            "https://docs.databricks.com/migration-docs/",
                            "https://docs.databricks.com/migration-docs/",
                            "general",
                            "# Docs migration source",
                            "d" * 64,
                        ),
                        (
                            api_document_id,
                            "databricks-api-before-0006",
                            "api_markdown",
                            "API migration source",
                            "https://docs.databricks.com/api/markdown/Test/Get.md",
                            "https://docs.databricks.com/api/markdown/Test/Get.md",
                            "api",
                            "# API migration source",
                            "a" * 64,
                        ),
                    ),
                )

        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, catalog_id, source_kind
                    FROM kb_documents
                    WHERE id IN (%s, %s)
                    ORDER BY id
                    """,
                    (docs_document_id, api_document_id),
                )
                migrated = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
                cursor.execute(
                    """
                    SELECT is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'kb_documents'
                      AND column_name = 'catalog_id'
                    """
                )
                catalog_id_column = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'kb_documents'
                      AND indexname = 'ix_kb_documents_catalog_id'
                    """
                )
                catalog_index = cursor.fetchone()

        assert migrated == {
            docs_document_id: ("databricks-docs", "general_html"),
            api_document_id: ("databricks-api", "api_markdown"),
        }
        assert catalog_id_column == ("NO",)
        assert catalog_index == ("ix_kb_documents_catalog_id",)
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM kb_documents WHERE id IN (%s, %s)",
                    (docs_document_id, api_document_id),
                )
        get_settings.cache_clear()


@pytest.mark.integration
def test_knowledge_rag_migration_preserves_business_rows_and_downgrades_in_test_db(
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

    try:
        command.downgrade(config, "0003_prompt_artifacts")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_type = 'BASE TABLE'
                    """
                )
                tables_before = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    "INSERT INTO sessions (id, title) VALUES (%s, %s)",
                    (session_id, "知识迁移保护测试"),
                )
                cursor.execute(
                    """
                    INSERT INTO messages (id, session_id, role, content, artifact_type)
                    VALUES (%s, %s, 'assistant', '# 保留正文', 'answer')
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
                        retryable,
                        prompt_name,
                        prompt_version,
                        artifact_type,
                        artifact_valid
                    )
                    VALUES (%s, %s, %s, 'deepseek', %s, %s, 1, 88, true, false,
                            'workflow_design', '1.0.0', 'workflow_design', true)
                    """,
                    (
                        model_call_id,
                        session_id,
                        model_call_id,
                        "deepseek/deepseek-v4-flash",
                        "deepseek-v4-flash",
                    ),
                )

        command.upgrade(config, "0006_catalog_link_sources")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_type = 'BASE TABLE'
                    """
                )
                tables_after = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    "SELECT title FROM sessions WHERE id = %s",
                    (session_id,),
                )
                migrated_session = cursor.fetchone()
                cursor.execute(
                    "SELECT role, content, artifact_type, source_citations "
                    "FROM messages WHERE id = %s",
                    (message_id,),
                )
                migrated_message = cursor.fetchone()
                cursor.execute(
                    "SELECT provider, model_alias, success FROM model_calls WHERE id = %s",
                    (model_call_id,),
                )
                migrated_call = cursor.fetchone()

        assert tables_after - tables_before == {
            "kb_documents",
            "kb_chunks",
            "kb_ingestion_runs",
        }
        assert migrated_session == ("知识迁移保护测试",)
        assert migrated_message == ("assistant", "# 保留正文", "answer", None)
        assert migrated_call == ("deepseek", "deepseek-v4-flash", True)

        command.downgrade(config, "0003_prompt_artifacts")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name LIKE 'kb_%'
                    """
                )
                assert cursor.fetchall() == []
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'messages'
                      AND column_name = 'source_citations'
                    """
                )
                assert cursor.fetchone() is None
    finally:
        get_settings.cache_clear()
        command.upgrade(config, "head")
        with psycopg.connect(sync_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
        get_settings.cache_clear()


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
