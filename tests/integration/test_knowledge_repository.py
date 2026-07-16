from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
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


def _catalog_link_document(source_key: str) -> NormalizedDocument:
    source = DiscoveredSource(
        source_key=source_key,
        kind=SourceKind.CATALOG_LINK,
        title="Pricing",
        url="https://www.databricks.com/product/pricing",
        category=KnowledgeCategory.GENERAL,
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Additional resources",
        summary="Databricks pricing information.",
    )
    return NormalizedDocument(
        source=source,
        title="Pricing",
        canonical_url=source.url,
        normalized_content=(
            "资料类型：官方目录链接（未抓取目标正文）\n\n"
            "标题：Pricing\n\n"
            "目录摘要：Databricks pricing information.\n\n"
            f"官方链接：{source.url}\n"
        ),
        source_updated_at=None,
        etag=None,
        last_modified=None,
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


def _directional_embedding(
    index: int,
    *,
    first: float,
    second: float,
) -> EmbeddingResult:
    vector = [0.0] * 1536
    vector[0] = first
    vector[1] = second
    return EmbeddingResult(index=index, embedding=tuple(vector))


async def _publish_search_document(
    repository: KnowledgeRepository,
    *,
    source_key: str,
    content: str,
    first: float,
    second: float,
) -> None:
    await repository.publish_document(
        _document(source_key, content=content),
        content_hash=source_key.encode().hex().ljust(64, "0")[:64],
        chunks=(_chunk(0, content),),
        embeddings=(
            _directional_embedding(
                0,
                first=first,
                second=second,
            ),
        ),
        fetched_at=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
    )


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
    assert document.catalog_id == "databricks-docs"
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
async def test_repository_publishes_catalog_link_with_link_only_metadata(
    knowledge_repository: KnowledgeRepository,
) -> None:
    source_key = "databricks-docs-pricing-link"
    document = _catalog_link_document(source_key)
    chunk = KnowledgeChunk(
        chunk_index=0,
        heading_path=(),
        content=document.normalized_content,
        content_hash="c" * 64,
        token_count=40,
        source_ref=document.canonical_url,
    )

    await knowledge_repository.publish_document(
        document,
        content_hash="d" * 64,
        chunks=(chunk,),
        embeddings=(_embedding(0, 0.1),),
        fetched_at=datetime(2026, 7, 16, 1, 0, tzinfo=UTC),
    )

    stored = await knowledge_repository.get_document(source_key)
    chunks = await knowledge_repository.list_chunks(source_key)
    assert stored is not None
    assert stored.catalog_id == "databricks-docs"
    assert stored.source_kind == "catalog_link"
    assert stored.source_url == "https://www.databricks.com/product/pricing"
    assert chunks[0].source_ref == stored.source_url
    assert chunks[0].chunk_metadata == {
        "catalog_id": "databricks-docs",
        "topic": "Additional resources",
        "link_only": True,
    }


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
async def test_catalog_presence_disables_only_after_two_successful_missing_snapshots(
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

    first_observed_at = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
    first_result = await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        {"docs-kept"},
        observed_at=first_observed_at,
    )

    kept = await knowledge_repository.get_document("docs-kept")
    removed = await knowledge_repository.get_document("docs-removed")
    removed_chunks = await knowledge_repository.list_chunks("docs-removed")

    assert first_result.pending_missing_count == 1
    assert first_result.disabled_count == 0
    assert kept is not None and kept.status == "active"
    assert kept.missing_sync_count == 0
    assert kept.missing_since_at is None
    assert removed is not None and removed.status == "active"
    assert removed.missing_sync_count == 1
    assert removed.missing_since_at == first_observed_at
    assert len(removed_chunks) == 1

    second_result = await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        {"docs-kept"},
        observed_at=datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
    )
    removed = await knowledge_repository.get_document("docs-removed")

    assert second_result.pending_missing_count == 0
    assert second_result.disabled_count == 1
    assert removed is not None and removed.status == "disabled"
    assert removed.missing_sync_count == 2
    assert removed.missing_since_at == first_observed_at
    assert len(await knowledge_repository.list_chunks("docs-removed")) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reappearing_source_resets_missing_state_without_early_reactivation(
    knowledge_repository: KnowledgeRepository,
) -> None:
    await knowledge_repository.publish_document(
        _document("docs-reappearing"),
        content_hash="d" * 64,
        chunks=(_chunk(0, "# Reappearing\n\nContent.\n"),),
        embeddings=(_embedding(0, 0.1),),
        fetched_at=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
    )
    await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        set(),
        observed_at=datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
    )
    await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        set(),
        observed_at=datetime(2026, 7, 14, 3, 0, tzinfo=UTC),
    )

    result = await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        {"docs-reappearing"},
        observed_at=datetime(2026, 7, 14, 4, 0, tzinfo=UTC),
    )
    document = await knowledge_repository.get_document("docs-reappearing")

    assert result.pending_missing_count == 0
    assert result.disabled_count == 0
    assert document is not None and document.status == "disabled"
    assert document.missing_sync_count == 0
    assert document.missing_since_at is None

    await knowledge_repository.mark_document_checked(
        "docs-reappearing",
        etag='"reappearing-v1"',
        last_modified=None,
        fetched_at=datetime(2026, 7, 14, 4, 5, tzinfo=UTC),
    )
    document = await knowledge_repository.get_document("docs-reappearing")

    assert document is not None and document.status == "active"
    assert document.missing_sync_count == 0
    assert document.missing_since_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_source_identity_reconciliation_preserves_document_and_chunks(
    knowledge_repository: KnowledgeRepository,
) -> None:
    document_id = await knowledge_repository.publish_document(
        _document("docs-legacy-jobs"),
        content_hash="e" * 64,
        chunks=(_chunk(0, "# Legacy\n\nContent.\n"),),
        embeddings=(_embedding(0, 0.1),),
        fetched_at=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
    )
    discovered = replace(
        _document("databricks-docs-1234567890abcdef12345678").source,
        kind=SourceKind.CATALOG_LINK,
        category=KnowledgeCategory.GENERAL,
    )

    migrated_count = await knowledge_repository.reconcile_source_identities((discovered,))

    assert migrated_count == 1
    assert await knowledge_repository.get_document("docs-legacy-jobs") is None
    migrated = await knowledge_repository.get_document(discovered.source_key)
    chunks = await knowledge_repository.list_chunks(discovered.source_key)
    assert migrated is not None and migrated.id == document_id
    assert migrated.catalog_id == "databricks-docs"
    assert migrated.source_kind == "catalog_link"
    assert migrated.category == "general"
    assert len(chunks) == 1
    assert chunks[0].document_id == document_id


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
    await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        set(),
        observed_at=datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
    )

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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_candidates_use_exact_cosine_order_and_limit(
    knowledge_repository: KnowledgeRepository,
) -> None:
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-vector-best",
        content="# Best\n\nDelta Lake guidance.\n",
        first=1.0,
        second=0.0,
    )
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-vector-second",
        content="# Second\n\nLakeflow guidance.\n",
        first=0.8,
        second=0.6,
    )
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-vector-third",
        content="# Third\n\nUnity Catalog guidance.\n",
        first=0.0,
        second=1.0,
    )
    query = _directional_embedding(0, first=1.0, second=0.0).embedding

    candidates = await knowledge_repository.find_vector_candidates(query, limit=2)

    assert tuple(candidate.source_key for candidate in candidates) == (
        "docs-vector-best",
        "docs-vector-second",
    )
    assert candidates[0].vector_similarity == pytest.approx(1.0)
    assert candidates[1].vector_similarity == pytest.approx(0.8)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_candidates_only_include_active_documents(
    knowledge_repository: KnowledgeRepository,
) -> None:
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-active",
        content="# Active\n\nActive content.\n",
        first=0.8,
        second=0.6,
    )
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-disabled",
        content="# Disabled\n\nDisabled content.\n",
        first=1.0,
        second=0.0,
    )
    await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        {"docs-active"},
        observed_at=datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
    )
    await knowledge_repository.reconcile_catalog_presence(
        "databricks-docs",
        {"docs-active"},
        observed_at=datetime(2026, 7, 14, 3, 0, tzinfo=UTC),
    )
    query = _directional_embedding(0, first=1.0, second=0.0).embedding

    candidates = await knowledge_repository.find_vector_candidates(query, limit=30)

    assert tuple(candidate.source_key for candidate in candidates) == ("docs-active",)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_source_key"),
    [
        ("OPTIMIZE", "docs-optimize"),
        ("run_if", "docs-run-if"),
        ("/api/2.1/jobs/runs/submit", "docs-api-path"),
    ],
)
async def test_lexical_candidates_match_english_terms_sql_and_identifiers(
    knowledge_repository: KnowledgeRepository,
    query: str,
    expected_source_key: str,
) -> None:
    documents = (
        (
            "docs-optimize",
            "# SQL\n\nUse OPTIMIZE after large Delta Lake writes.\n",
        ),
        (
            "docs-run-if",
            "# Jobs\n\nSet run_if to ALL_SUCCESS for this task.\n",
        ),
        (
            "docs-api-path",
            "# API\n\nCall POST /api/2.1/jobs/runs/submit for a one-time run.\n",
        ),
    )
    for index, (source_key, content) in enumerate(documents):
        await _publish_search_document(
            knowledge_repository,
            source_key=source_key,
            content=content,
            first=1.0,
            second=float(index),
        )

    candidates = await knowledge_repository.find_lexical_candidates(query, limit=1)

    assert tuple(candidate.source_key for candidate in candidates) == (expected_source_key,)
    assert candidates[0].lexical_score is not None
    assert candidates[0].lexical_score > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exact_vector_search_works_without_ann_index(
    knowledge_repository: KnowledgeRepository,
    test_engine: AsyncEngine,
) -> None:
    await _publish_search_document(
        knowledge_repository,
        source_key="docs-exact-search",
        content="# Exact\n\nExact pgvector search.\n",
        first=1.0,
        second=0.0,
    )
    async with test_engine.connect() as connection:
        index_definitions = tuple(
            (
                await connection.scalars(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() AND tablename = 'kb_chunks'"
                    )
                )
            ).all()
        )
    query = _directional_embedding(0, first=1.0, second=0.0).embedding

    candidates = await knowledge_repository.find_vector_candidates(query, limit=1)

    normalized_indexes = " ".join(index_definitions).lower()
    assert "hnsw" not in normalized_indexes
    assert "ivfflat" not in normalized_indexes
    assert tuple(candidate.source_key for candidate in candidates) == ("docs-exact-search",)
