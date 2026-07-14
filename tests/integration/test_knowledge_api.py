from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from databricks_zh_expert.db.models import KnowledgeDocument, KnowledgeIngestionRun
from databricks_zh_expert.rag.chunker import KnowledgeChunk
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.repository import (
    IngestionRunCompletion,
    KnowledgeRepository,
)
from databricks_zh_expert.rag.types import (
    DiscoveredSource,
    KnowledgeCategory,
    NormalizedDocument,
    SourceKind,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def knowledge_repository_for_api(
    test_engine: AsyncEngine,
) -> AsyncIterator[KnowledgeRepository]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory.begin() as session:
        await session.execute(delete(KnowledgeDocument))
        await session.execute(delete(KnowledgeIngestionRun))
    try:
        yield KnowledgeRepository(session_factory)
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(KnowledgeDocument))
            await session.execute(delete(KnowledgeIngestionRun))


def _document() -> NormalizedDocument:
    source = DiscoveredSource(
        source_key="docs-lakeflow-jobs",
        kind=SourceKind.GENERAL_HTML,
        title="Configure Lakeflow Jobs",
        url="https://docs.databricks.com/aws/en/jobs/",
        category=KnowledgeCategory.ORCHESTRATION,
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary="Official jobs guidance.",
    )
    return NormalizedDocument(
        source=source,
        title=source.title,
        canonical_url=source.url,
        normalized_content="# Configure Lakeflow Jobs\n\nRetry guidance.\n",
        source_updated_at=None,
        etag='"jobs-v1"',
        last_modified=None,
    )


async def _publish_document(repository: KnowledgeRepository) -> None:
    chunk = KnowledgeChunk(
        chunk_index=0,
        heading_path=("Configure Lakeflow Jobs",),
        content="# Configure Lakeflow Jobs\n\nRetry guidance.\n",
        content_hash="1" * 64,
        token_count=10,
        source_ref="https://docs.databricks.com/aws/en/jobs/#retries",
    )
    await repository.publish_document(
        _document(),
        content_hash="2" * 64,
        chunks=(chunk,),
        embeddings=(EmbeddingResult(index=0, embedding=(0.1,) * 1536),),
        fetched_at=datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
    )


async def _finish_run(
    repository: KnowledgeRepository,
    *,
    status: str,
) -> UUID:
    run_id = await repository.start_run("a" * 64)
    await repository.finish_run(
        run_id,
        IngestionRunCompletion(
            status=status,
            discovered_count=1,
            changed_count=1,
            skipped_count=0,
            failed_count=1 if status == "partial" else 0,
            chunk_count=1,
            error_summary=(
                ({"source_key": "docs-failed", "code": "knowledge_source_failed"},)
                if status == "partial"
                else ()
            ),
        ),
    )
    return run_id


async def test_knowledge_index_status_reports_uninitialized_index(
    client: AsyncClient,
    knowledge_repository_for_api: KnowledgeRepository,
) -> None:
    del knowledge_repository_for_api

    response = await client.get("/api/knowledge/index/status")

    assert response.status_code == 200
    assert response.json() == {
        "last_run_status": None,
        "active_document_count": 0,
        "chunk_count": 0,
        "embedding_model": None,
        "embedding_dimensions": None,
        "queryable": False,
    }


async def test_knowledge_index_status_reports_partial_but_queryable_index(
    client: AsyncClient,
    knowledge_repository_for_api: KnowledgeRepository,
) -> None:
    await _publish_document(knowledge_repository_for_api)
    await _finish_run(knowledge_repository_for_api, status="partial")

    response = await client.get("/api/knowledge/index/status")

    assert response.status_code == 200
    assert response.json() == {
        "last_run_status": "partial",
        "active_document_count": 1,
        "chunk_count": 1,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "queryable": True,
    }


async def test_knowledge_index_status_rejects_dimension_mismatch(
    client: AsyncClient,
    knowledge_repository_for_api: KnowledgeRepository,
    test_engine: AsyncEngine,
) -> None:
    await _publish_document(knowledge_repository_for_api)
    run_id = await _finish_run(knowledge_repository_for_api, status="succeeded")
    async_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session_factory.begin() as session:
        await session.execute(
            update(KnowledgeIngestionRun)
            .where(KnowledgeIngestionRun.id == run_id)
            .values(embedding_dimensions=1024)
        )

    response = await client.get("/api/knowledge/index/status")

    assert response.status_code == 200
    assert response.json()["embedding_dimensions"] == 1024
    assert response.json()["queryable"] is False


async def test_knowledge_api_does_not_expose_sources_or_sync_routes(
    client: AsyncClient,
) -> None:
    sources_response = await client.get("/api/knowledge/sources")
    sync_response = await client.post("/api/knowledge/sync")

    assert sources_response.status_code == 404
    assert sync_response.status_code == 404


async def test_ready_health_does_not_depend_on_knowledge_index(
    client: AsyncClient,
    knowledge_repository_for_api: KnowledgeRepository,
) -> None:
    del knowledge_repository_for_api

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
