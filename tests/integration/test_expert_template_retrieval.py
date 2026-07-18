import hashlib
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from databricks_zh_expert.db.models import (
    ExpertTemplateChunkRecord,
    ExpertTemplateRecord,
    ExpertTemplateSyncRun,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.retrieval import ExpertTemplateRetriever
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateSource,
    PreparedTemplateSnapshot,
    PreparedTemplateVersion,
)
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.search.markdown import MarkdownChunk


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


@pytest_asyncio.fixture
async def session_factory(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    await _clear_tables(factory)
    try:
        yield factory
    finally:
        await _clear_tables(factory)


@pytest_asyncio.fixture
async def repository(
    session_factory: async_sessionmaker[AsyncSession],
    registry: ExpertTemplateRegistry,
) -> ExpertTemplateRepository:
    return ExpertTemplateRepository(session_factory, registry=registry)


async def _clear_tables(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory.begin() as session:
        await session.execute(update(ExpertTemplateRecord).values(extends_id=None))
        await session.execute(delete(ExpertTemplateChunkRecord))
        await session.execute(delete(ExpertTemplateRecord))
        await session.execute(delete(ExpertTemplateSyncRun))


def _vector(first: float, second: float) -> tuple[float, ...]:
    values = [0.0] * 1536
    values[0] = first
    values[1] = second
    return tuple(values)


def _prepared(
    source: ExpertTemplateSource,
    embedding: tuple[float, ...],
) -> PreparedTemplateVersion:
    content = f"# {source.name}\n\n{source.summary}\n\n{source.content[:300].strip()}\n"
    chunk = MarkdownChunk(
        chunk_index=0,
        heading_path=(source.name,),
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        token_count=60,
        source_ref=f"expert-template://{source.template_id}@{source.version}",
    )
    return PreparedTemplateVersion(
        source=source,
        chunks=(chunk,),
        embeddings=(EmbeddingResult(index=0, embedding=embedding),),
    )


async def _publish_registry(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    vectors: Mapping[str, tuple[float, ...]],
) -> None:
    await repository.publish_snapshot(
        PreparedTemplateSnapshot(
            source_hash=registry.source_hash,
            templates=tuple(
                _prepared(source, vectors.get(source.template_id, _vector(0.0, 1.0)))
                for source in registry.templates
            ),
            active_template_ids=frozenset(source.template_id for source in registry.templates),
            synced_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_query_applies_profile_prompt_cloud_and_model_filters_in_sql(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _publish_registry(
        repository,
        registry,
        {
            "code.delta_merge_sql": _vector(1.0, 0.0),
            "ingestion.s3_auto_loader": _vector(0.99, 0.01),
            "retail.workflow_dag": _vector(0.98, 0.02),
        },
    )

    candidates = await repository.find_vector_candidates(
        _vector(1.0, 0.0),
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        limit=20,
    )

    assert candidates[0].template_id == "ingestion.s3_auto_loader"
    assert candidates[0].cloud == "aws"
    assert all(candidate.layer == "core" for candidate in candidates)
    assert "code.delta_merge_sql" not in {candidate.template_id for candidate in candidates}
    assert "retail.workflow_dag" not in {candidate.template_id for candidate in candidates}

    async with session_factory.begin() as session:
        await session.execute(
            update(ExpertTemplateChunkRecord)
            .where(ExpertTemplateChunkRecord.template_record_id == candidates[0].template_record_id)
            .values(embedding_model="wrong-model")
        )

    filtered = await repository.find_vector_candidates(
        _vector(1.0, 0.0),
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        limit=20,
    )
    assert "ingestion.s3_auto_loader" not in {candidate.template_id for candidate in filtered}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lexical_query_applies_prompt_and_generic_layer_filters(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
) -> None:
    await _publish_registry(repository, registry, {})

    candidates = await repository.find_lexical_candidates(
        "Kinesis",
        profile_id="generic",
        prompt_name=PromptName.PYSPARK_GENERATION,
        limit=20,
    )

    template_ids = {candidate.template_id for candidate in candidates}
    assert "ingestion.kinesis_streaming" in template_ids
    assert "code.kinesis_pyspark" in template_ids
    assert all(candidate.layer == "core" for candidate in candidates)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retail_retrieval_returns_overlay_with_active_core_parent(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
) -> None:
    await _publish_registry(
        repository,
        registry,
        {"retail.workflow_dag": _vector(1.0, 0.0)},
    )
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    bundle = await retriever.retrieve(
        "设计 AWS 零售销售工作流 DAG",
        query_embedding=_vector(1.0, 0.0),
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert [item.template_id for item in bundle.selected_templates][:2] == [
        "workflow.lakeflow_jobs",
        "retail.workflow_dag",
    ]
    assert bundle.selected_templates[0].reason == "inherited"
    assert "AWS 零售工作流 DAG" in bundle.context
    assert "knowledge/expert_templates" not in bundle.context
