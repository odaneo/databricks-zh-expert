import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from databricks_zh_expert.db.models import (
    ExpertTemplateChunkRecord,
    ExpertTemplateRecord,
    ExpertTemplateSyncRun,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateSource,
    PreparedTemplateSnapshot,
    PreparedTemplateVersion,
    SyncRunCompletion,
    TemplateListQuery,
)
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.search.markdown import MarkdownChunk


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


@pytest_asyncio.fixture
async def expert_template_session_factory(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    await _clear_expert_template_tables(session_factory)
    try:
        yield session_factory
    finally:
        await _clear_expert_template_tables(session_factory)


@pytest_asyncio.fixture
async def repository(
    expert_template_session_factory: async_sessionmaker[AsyncSession],
    registry: ExpertTemplateRegistry,
) -> ExpertTemplateRepository:
    return ExpertTemplateRepository(expert_template_session_factory, registry=registry)


async def _clear_expert_template_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(update(ExpertTemplateRecord).values(extends_id=None))
        await session.execute(delete(ExpertTemplateChunkRecord))
        await session.execute(delete(ExpertTemplateRecord))
        await session.execute(delete(ExpertTemplateSyncRun))


def _prepared(source: ExpertTemplateSource) -> PreparedTemplateVersion:
    chunk_content = f"# {source.name}\n\n{source.content[:120].strip()}\n"
    chunk = MarkdownChunk(
        chunk_index=0,
        heading_path=(source.name,),
        content=chunk_content,
        content_hash=hashlib.sha256(chunk_content.encode("utf-8")).hexdigest(),
        token_count=20,
        source_ref=(
            f"expert-template://{source.template_id}@{source.version}#{source.template_id}"
        ),
    )
    return PreparedTemplateVersion(
        source=source,
        chunks=(chunk,),
        embeddings=(EmbeddingResult(index=0, embedding=(0.01,) * 1536),),
    )


def _snapshot(
    *,
    source_hash: str,
    prepared: tuple[PreparedTemplateVersion, ...],
    active_template_ids: frozenset[str] | None = None,
) -> PreparedTemplateSnapshot:
    return PreparedTemplateSnapshot(
        source_hash=source_hash,
        templates=prepared,
        active_template_ids=active_template_ids
        if active_template_ids is not None
        else frozenset(item.source.template_id for item in prepared),
        synced_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
    )


def _record_from_source(
    source: ExpertTemplateSource,
    *,
    version: str,
    status: str,
) -> ExpertTemplateRecord:
    return ExpertTemplateRecord(
        template_id=source.template_id,
        version=version,
        name=source.name,
        summary=source.summary,
        kind=source.kind.value,
        category=source.category.value,
        layer=source.layer,
        profile_id=source.profile_id,
        cloud=source.cloud,
        prompt_names=[item.value for item in source.prompt_names],
        tags=list(source.tags),
        extends_id=None,
        official_refs=list(source.official_refs),
        source_path=source.source_path,
        content=source.content,
        content_hash=source.content_hash,
        status=status,
        chunk_count=0,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_starts_and_finishes_sync_run(
    repository: ExpertTemplateRepository,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await repository.start_run("a" * 64)
    await repository.finish_run(
        run_id,
        SyncRunCompletion(
            status="succeeded",
            discovered_count=37,
            inserted_count=37,
            activated_count=37,
            inactivated_count=0,
            skipped_count=0,
            failed_count=0,
            chunk_count=37,
            error_summary=(),
        ),
    )

    async with expert_template_session_factory() as session:
        run = await session.get(ExpertTemplateSyncRun, run_id)

    assert run is not None
    assert run.status == "succeeded"
    assert run.discovered_count == 37
    assert run.completed_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_atomically_publishes_all_registry_templates(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    prepared = tuple(_prepared(source) for source in registry.templates)

    await repository.publish_snapshot(
        _snapshot(source_hash=registry.source_hash, prepared=prepared)
    )

    async with expert_template_session_factory() as session:
        template_count = await session.scalar(
            select(func.count()).select_from(ExpertTemplateRecord)
        )
        active_count = await session.scalar(
            select(func.count())
            .select_from(ExpertTemplateRecord)
            .where(ExpertTemplateRecord.status == "active")
        )
        chunk_count = await session.scalar(
            select(func.count()).select_from(ExpertTemplateChunkRecord)
        )
        models = tuple(
            (
                await session.scalars(select(ExpertTemplateChunkRecord.embedding_model).distinct())
            ).all()
        )

    assert template_count == 37
    assert active_count == 37
    assert chunk_count == 37
    assert models == ("text-embedding-3-small",)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_unique_index_rejects_two_active_versions(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = registry.templates[0]
    await repository.publish_snapshot(
        _snapshot(source_hash="1" * 64, prepared=(_prepared(source),))
    )

    with pytest.raises(IntegrityError):
        async with expert_template_session_factory.begin() as session:
            session.add(_record_from_source(source, version="2.0.0", status="active"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_version_upgrade_preserves_old_content_and_chunks(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = registry.get_template("medallion.standard")
    await repository.publish_snapshot(
        _snapshot(source_hash="1" * 64, prepared=(_prepared(source),))
    )
    upgraded = replace(
        source,
        version="2.0.0",
        content=source.content + "\n升级后的正文。\n",
        content_hash="2" * 64,
    )

    await repository.publish_snapshot(
        _snapshot(source_hash="2" * 64, prepared=(_prepared(upgraded),))
    )

    async with expert_template_session_factory() as session:
        records = tuple(
            (
                await session.scalars(
                    select(ExpertTemplateRecord)
                    .where(ExpertTemplateRecord.template_id == source.template_id)
                    .order_by(ExpertTemplateRecord.version)
                )
            ).all()
        )
        chunks = tuple(
            (
                await session.scalars(
                    select(ExpertTemplateChunkRecord)
                    .join(
                        ExpertTemplateRecord,
                        ExpertTemplateRecord.id == ExpertTemplateChunkRecord.template_record_id,
                    )
                    .where(ExpertTemplateRecord.template_id == source.template_id)
                )
            ).all()
        )

    assert tuple(record.status for record in records) == ("inactive", "active")
    assert records[0].content == source.content
    assert records[1].content == upgraded.content
    assert len(chunks) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_upgrade_rebinds_unchanged_overlay_to_new_active_parent(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    overlay = next(source for source in registry.templates if source.extends_template_id)
    parent = registry.get_template(overlay.extends_template_id or "")
    await repository.publish_snapshot(
        _snapshot(
            source_hash="3" * 64,
            prepared=(_prepared(parent), _prepared(overlay)),
        )
    )
    upgraded_parent = replace(
        parent,
        version="2.0.0",
        content_hash="4" * 64,
    )

    await repository.publish_snapshot(
        _snapshot(
            source_hash="4" * 64,
            prepared=(_prepared(upgraded_parent),),
            active_template_ids=frozenset({parent.template_id, overlay.template_id}),
        )
    )

    async with expert_template_session_factory() as session:
        active_parent = await session.scalar(
            select(ExpertTemplateRecord).where(
                ExpertTemplateRecord.template_id == parent.template_id,
                ExpertTemplateRecord.status == "active",
            )
        )
        active_overlay = await session.scalar(
            select(ExpertTemplateRecord).where(
                ExpertTemplateRecord.template_id == overlay.template_id,
                ExpertTemplateRecord.status == "active",
            )
        )

    assert active_parent is not None
    assert active_overlay is not None
    assert active_parent.version == "2.0.0"
    assert active_overlay.extends_id == active_parent.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_failure_rolls_back_entire_active_snapshot(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = registry.get_template("medallion.standard")
    await repository.publish_snapshot(
        _snapshot(source_hash="5" * 64, prepared=(_prepared(source),))
    )
    run_id = await repository.start_run("5" * 64)
    await repository.finish_run(
        run_id,
        SyncRunCompletion(
            status="succeeded",
            discovered_count=1,
            inserted_count=1,
            activated_count=1,
            inactivated_count=0,
            skipped_count=0,
            failed_count=0,
            chunk_count=1,
            error_summary=(),
        ),
    )
    invalid = replace(
        registry.templates[0],
        template_id="invalid.overlay",
        version="1.0.0",
        extends_template_id="missing.parent",
        content_hash="6" * 64,
    )

    with pytest.raises(ValueError, match="父模板"):
        await repository.publish_snapshot(
            _snapshot(
                source_hash="6" * 64,
                prepared=(_prepared(invalid),),
                active_template_ids=frozenset({source.template_id, invalid.template_id}),
            )
        )

    async with expert_template_session_factory() as session:
        active_ids = tuple(
            (
                await session.scalars(
                    select(ExpertTemplateRecord.template_id)
                    .where(ExpertTemplateRecord.status == "active")
                    .order_by(ExpertTemplateRecord.template_id)
                )
            ).all()
        )
        invalid_count = await session.scalar(
            select(func.count())
            .select_from(ExpertTemplateRecord)
            .where(ExpertTemplateRecord.template_id == invalid.template_id)
        )
        latest_succeeded = await session.scalar(
            select(ExpertTemplateSyncRun)
            .where(ExpertTemplateSyncRun.status == "succeeded")
            .order_by(ExpertTemplateSyncRun.started_at.desc())
            .limit(1)
        )

    assert active_ids == (source.template_id,)
    assert invalid_count == 0
    assert latest_succeeded is not None and latest_succeeded.id == run_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_status_requires_current_hash_model_dimensions_and_defaults(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
    expert_template_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await repository.publish_snapshot(
        _snapshot(
            source_hash=registry.source_hash,
            prepared=tuple(_prepared(source) for source in registry.templates),
        )
    )
    run_id = await repository.start_run(registry.source_hash)
    await repository.finish_run(
        run_id,
        SyncRunCompletion(
            status="succeeded",
            discovered_count=37,
            inserted_count=37,
            activated_count=37,
            inactivated_count=0,
            skipped_count=0,
            failed_count=0,
            chunk_count=37,
            error_summary=(),
        ),
    )

    ready = await repository.get_index_status(registry.source_hash)
    stale = await repository.get_index_status("0" * 64)

    assert ready.queryable is True
    assert ready.source_hash_matches is True
    assert ready.active_template_count == 37
    assert ready.chunk_count == 37
    assert stale.queryable is False
    assert stale.source_hash_matches is False

    async with expert_template_session_factory.begin() as session:
        await session.execute(
            update(ExpertTemplateSyncRun)
            .where(ExpertTemplateSyncRun.id == run_id)
            .values(embedding_dimensions=8)
        )
    assert (await repository.get_index_status(registry.source_hash)).queryable is False

    async with expert_template_session_factory.begin() as session:
        await session.execute(
            update(ExpertTemplateSyncRun)
            .where(ExpertTemplateSyncRun.id == run_id)
            .values(embedding_dimensions=1536)
        )
        await session.execute(
            update(ExpertTemplateChunkRecord).values(embedding_model="wrong-model")
        )
    assert (await repository.get_index_status(registry.source_hash)).queryable is False

    async with expert_template_session_factory.begin() as session:
        await session.execute(
            update(ExpertTemplateChunkRecord).values(embedding_model="text-embedding-3-small")
        )
        default_template_id = next(
            template_id
            for profile in registry.profiles
            for template_ids in profile.prompt_defaults.values()
            for template_id in template_ids
        )
        await session.execute(
            update(ExpertTemplateRecord)
            .where(ExpertTemplateRecord.template_id == default_template_id)
            .values(status="inactive")
        )
    assert (await repository.get_index_status(registry.source_hash)).queryable is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_active_templates_filters_by_profile_kind_and_category(
    repository: ExpertTemplateRepository,
    registry: ExpertTemplateRegistry,
) -> None:
    await repository.publish_snapshot(
        _snapshot(
            source_hash=registry.source_hash,
            prepared=tuple(_prepared(source) for source in registry.templates),
        )
    )

    generic = await repository.list_active_templates(
        TemplateListQuery(profile_id="generic", limit=100)
    )
    retail = await repository.list_active_templates(
        TemplateListQuery(profile_id="retail_sales_demo", limit=100)
    )

    assert generic
    assert all(item.layer == "core" for item in generic)
    assert retail
    assert {item.layer for item in retail} == {"core", "retail_sales_demo"}
