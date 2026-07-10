import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

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

    assert EXPECTED_TABLES <= table_names
    assert public_table_names == set()


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
