from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from databricks_zh_expert.db.models import (
    ChatSession,
    KnowledgeChunkRecord,
    KnowledgeDocument,
    KnowledgeIngestionRun,
    Message,
    ModelCall,
)
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


@pytest_asyncio.fixture
async def knowledge_repository(
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


def _document(
    source_key: str,
    *,
    content: str = "# Lakeflow Jobs\n\nReliable workflow guidance.\n",
) -> NormalizedDocument:
    source = DiscoveredSource(
        source_key=source_key,
        kind=SourceKind.GENERAL_HTML,
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/jobs/",
        category=KnowledgeCategory.ORCHESTRATION,
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary="Official workflow guidance.",
    )
    return NormalizedDocument(
        source=source,
        title="Lakeflow Jobs",
        canonical_url="https://docs.databricks.com/aws/en/jobs/",
        normalized_content=content,
        source_updated_at="2026-07-10T08:30:00Z",
        etag='"jobs-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
    )


def _chunk(index: int, content: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_index=index,
        heading_path=("Lakeflow Jobs",),
        content=content,
        content_hash=f"{index + 1:064x}",
        token_count=12,
        source_ref="https://docs.databricks.com/aws/en/jobs/#lakeflow-jobs",
    )


def _embedding(index: int, value: float) -> EmbeddingResult:
    return EmbeddingResult(index=index, embedding=(value,) * 1536)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_publishes_document_chunks_and_succeeded_run(
    knowledge_repository: KnowledgeRepository,
) -> None:
    run_id = await knowledge_repository.start_run("a" * 64)
    chunks = (
        _chunk(0, "# Lakeflow Jobs\n\nFirst chunk.\n"),
        _chunk(1, "# Lakeflow Jobs\n\nSecond chunk.\n"),
    )
    embeddings = (_embedding(0, 0.1), _embedding(1, 0.2))

    document_id = await knowledge_repository.publish_document(
        _document("docs-lakeflow-jobs"),
        content_hash="b" * 64,
        chunks=chunks,
        embeddings=embeddings,
        fetched_at=datetime(2026, 7, 13, 1, 2, tzinfo=UTC),
    )
    await knowledge_repository.finish_run(
        run_id,
        IngestionRunCompletion(
            status="succeeded",
            discovered_count=1,
            changed_count=1,
            skipped_count=0,
            failed_count=0,
            chunk_count=2,
            error_summary=(),
        ),
    )

    document = await knowledge_repository.get_document("docs-lakeflow-jobs")
    stored_chunks = await knowledge_repository.list_chunks("docs-lakeflow-jobs")
    run = await knowledge_repository.get_run(run_id)
    index_status = await knowledge_repository.get_index_status()

    assert document is not None
    assert document.id == document_id
    assert document.status == "active"
    assert document.chunk_count == 2
    assert document.content_hash == "b" * 64
    assert tuple(chunk.chunk_index for chunk in stored_chunks) == (0, 1)
    assert stored_chunks[0].heading_path == ["Lakeflow Jobs"]
    assert len(stored_chunks[0].embedding) == 1536
    assert stored_chunks[0].embedding_model == "text-embedding-3-small"
    assert run is not None
    assert run.status == "succeeded"
    assert run.completed_at is not None
    assert index_status.queryable is True
    assert index_status.active_document_count == 1
    assert index_status.chunk_count == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_transaction_failure_preserves_previous_document_and_chunks(
    knowledge_repository: KnowledgeRepository,
) -> None:
    await knowledge_repository.publish_document(
        _document("docs-lakeflow-jobs", content="# V1\n\nStable content.\n"),
        content_hash="1" * 64,
        chunks=(_chunk(0, "# V1\n\nStable chunk.\n"),),
        embeddings=(_embedding(0, 0.1),),
        fetched_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
    )
    duplicate_chunks = (
        _chunk(0, "# V2\n\nFirst replacement.\n"),
        _chunk(0, "# V2\n\nDuplicate replacement.\n"),
    )

    with pytest.raises(IntegrityError):
        await knowledge_repository.publish_document(
            _document("docs-lakeflow-jobs", content="# V2\n\nChanged content.\n"),
            content_hash="2" * 64,
            chunks=duplicate_chunks,
            embeddings=(_embedding(0, 0.2), _embedding(1, 0.3)),
            fetched_at=datetime(2026, 7, 13, 2, 0, tzinfo=UTC),
        )

    document = await knowledge_repository.get_document("docs-lakeflow-jobs")
    stored_chunks = await knowledge_repository.list_chunks("docs-lakeflow-jobs")

    assert document is not None
    assert document.content_hash == "1" * 64
    assert document.normalized_content == "# V1\n\nStable content.\n"
    assert tuple(chunk.content for chunk in stored_chunks) == ("# V1\n\nStable chunk.\n",)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disable_missing_sources_marks_rows_without_deleting_them(
    knowledge_repository: KnowledgeRepository,
) -> None:
    for source_key in ("docs-kept", "docs-removed"):
        await knowledge_repository.publish_document(
            _document(source_key),
            content_hash=source_key.removeprefix("docs-").ljust(64, "0"),
            chunks=(_chunk(0, f"# {source_key}\n\nContent.\n"),),
            embeddings=(_embedding(0, 0.1),),
            fetched_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        )

    disabled_count = await knowledge_repository.disable_missing_sources({"docs-kept"})

    kept = await knowledge_repository.get_document("docs-kept")
    removed = await knowledge_repository.get_document("docs-removed")
    removed_chunks = await knowledge_repository.list_chunks("docs-removed")

    assert disabled_count == 1
    assert kept is not None and kept.status == "active"
    assert removed is not None and removed.status == "disabled"
    assert len(removed_chunks) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_knowledge_repository_never_changes_business_table_counts(
    knowledge_repository: KnowledgeRepository,
    test_engine: AsyncEngine,
) -> None:
    async with test_engine.connect() as connection:
        before = (
            await connection.scalar(select(func.count()).select_from(ChatSession)),
            await connection.scalar(select(func.count()).select_from(Message)),
            await connection.scalar(select(func.count()).select_from(ModelCall)),
        )

    await knowledge_repository.publish_document(
        _document("docs-lakeflow-jobs"),
        content_hash="c" * 64,
        chunks=(_chunk(0, "# Lakeflow Jobs\n\nKnowledge only.\n"),),
        embeddings=(_embedding(0, 0.1),),
        fetched_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
    )
    await knowledge_repository.disable_missing_sources(set())

    async with test_engine.connect() as connection:
        after = (
            await connection.scalar(select(func.count()).select_from(ChatSession)),
            await connection.scalar(select(func.count()).select_from(Message)),
            await connection.scalar(select(func.count()).select_from(ModelCall)),
        )
        knowledge_count = await connection.scalar(
            select(func.count()).select_from(KnowledgeChunkRecord)
        )

    assert after == before
    assert knowledge_count == 1
