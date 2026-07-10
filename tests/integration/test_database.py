import pytest
from sqlalchemy import text

from databricks_zh_expert.db.session import Database


@pytest.mark.integration
@pytest.mark.asyncio
async def test_test_database_uses_isolated_schema_and_pgvector(
    test_database_url: str,
) -> None:
    database = Database(test_database_url)
    try:
        async with database.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        current_database(),
                        current_schema(),
                        (
                            SELECT namespace.nspname
                            FROM pg_extension AS extension
                            JOIN pg_namespace AS namespace
                                ON namespace.oid = extension.extnamespace
                            WHERE extension.extname = 'vector'
                        )
                    """
                )
            )
            database_name, schema_name, vector_schema = result.one()
    finally:
        await database.dispose()

    assert database_name == "databricks_agent_test"
    assert schema_name == "databricks_agent"
    assert vector_schema == "databricks_agent"
