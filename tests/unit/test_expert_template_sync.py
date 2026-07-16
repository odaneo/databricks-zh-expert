from collections.abc import Mapping, Sequence
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.sync import (
    ExpertTemplateSyncError,
    ExpertTemplateSyncService,
)
from databricks_zh_expert.expert_templates.types import (
    PreparedTemplateSnapshot,
    SyncRunCompletion,
    TemplateVersionState,
)
from databricks_zh_expert.rag.embeddings import EmbeddingResult


class FakeExpertTemplateRepository:
    def __init__(
        self,
        active_states: Mapping[str, TemplateVersionState] | None = None,
    ) -> None:
        self.active_states = dict(active_states or {})
        self.run_ids: list[UUID] = []
        self.completions: list[tuple[UUID, SyncRunCompletion]] = []
        self.snapshots: list[PreparedTemplateSnapshot] = []

    @property
    def publish_calls(self) -> int:
        return len(self.snapshots)

    async def start_run(self, source_hash: str) -> UUID:
        del source_hash
        run_id = uuid4()
        self.run_ids.append(run_id)
        return run_id

    async def finish_run(
        self,
        run_id: UUID,
        completion: SyncRunCompletion,
    ) -> None:
        self.completions.append((run_id, completion))

    async def get_active_states(self) -> Mapping[str, TemplateVersionState]:
        return self.active_states

    async def publish_snapshot(self, snapshot: PreparedTemplateSnapshot) -> None:
        self.snapshots.append(snapshot)


class FakeEmbeddingClient:
    def __init__(
        self,
        *,
        index_offset: int = 0,
        dimensions: int = 1536,
        error: Exception | None = None,
    ) -> None:
        self.index_offset = index_offset
        self.dimensions = dimensions
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[EmbeddingResult, ...]:
        values = tuple(texts)
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return tuple(
            EmbeddingResult(
                index=index + self.index_offset,
                embedding=(0.01,) * self.dimensions,
            )
            for index in range(len(values))
        )


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


def _matching_states(
    registry: ExpertTemplateRegistry,
) -> dict[str, TemplateVersionState]:
    return {
        source.template_id: TemplateVersionState(
            record_id=uuid4(),
            template_id=source.template_id,
            version=source.version,
            content_hash=source.content_hash,
        )
        for source in registry.templates
    }


@pytest.mark.asyncio
async def test_sync_embeds_only_new_versions_and_publishes_once(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository()
    embedding_client = FakeEmbeddingClient()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = await service.sync(registry)

    assert result.discovered_count == 37
    assert result.inserted_count == 37
    assert result.activated_count == 37
    assert result.inactivated_count == 0
    assert result.failed_count == 0
    assert result.dry_run is False
    assert repository.publish_calls == 1
    assert len(embedding_client.calls) == 1
    assert len(embedding_client.calls[0]) == result.chunk_count
    assert result.chunk_count > 37
    assert repository.completions[0][1].status == "succeeded"


@pytest.mark.asyncio
async def test_sync_skips_unchanged_versions_without_embedding_or_publish(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository(_matching_states(registry))
    embedding_client = FakeEmbeddingClient()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = await service.sync(registry)

    assert result.skipped_count == 37
    assert result.inserted_count == 0
    assert result.chunk_count == 0
    assert embedding_client.calls == []
    assert repository.publish_calls == 0
    assert repository.completions[0][1].status == "succeeded"


@pytest.mark.asyncio
async def test_sync_rejects_same_version_with_changed_hash(
    registry: ExpertTemplateRegistry,
) -> None:
    source = registry.get_template("medallion.standard")
    repository = FakeExpertTemplateRepository(
        {
            source.template_id: TemplateVersionState(
                record_id=uuid4(),
                template_id=source.template_id,
                version=source.version,
                content_hash="0" * 64,
            )
        }
    )
    embedding_client = FakeEmbeddingClient()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    with pytest.raises(ExpertTemplateSyncError, match="内容变化但版本未升级"):
        await service.sync(registry)

    assert embedding_client.calls == []
    assert repository.publish_calls == 0
    assert repository.completions[0][1].status == "failed"


@pytest.mark.asyncio
async def test_sync_dry_run_never_writes_or_calls_embedding(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository()
    embedding_client = FakeEmbeddingClient()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = await service.sync(registry, dry_run=True)

    assert result.dry_run is True
    assert result.run_id is None
    assert result.inserted_count == 37
    assert result.chunk_count > 37
    assert repository.run_ids == []
    assert repository.completions == []
    assert repository.publish_calls == 0
    assert embedding_client.calls == []


@pytest.mark.asyncio
async def test_sync_embedding_failure_records_failed_run_without_publish(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository()
    embedding_client = FakeEmbeddingClient(error=RuntimeError("secret-api-key"))
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    with pytest.raises(ExpertTemplateSyncError, match="专家模板同步失败"):
        await service.sync(registry)

    assert repository.publish_calls == 0
    completion = repository.completions[0][1]
    assert completion.status == "failed"
    assert completion.failed_count == 1
    assert "secret-api-key" not in str(completion.error_summary)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index_offset", "dimensions", "message"),
    [
        (1, 1536, "顺序不一致"),
        (0, 8, "维度不匹配"),
    ],
)
async def test_sync_rejects_invalid_embedding_batch_before_publish(
    registry: ExpertTemplateRegistry,
    index_offset: int,
    dimensions: int,
    message: str,
) -> None:
    repository = FakeExpertTemplateRepository()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=FakeEmbeddingClient(
            index_offset=index_offset,
            dimensions=dimensions,
        ),
    )

    with pytest.raises(ExpertTemplateSyncError, match=message):
        await service.sync(registry)

    assert repository.publish_calls == 0
    assert repository.completions[0][1].status == "failed"


@pytest.mark.asyncio
async def test_sync_upgrades_version_and_inactivates_deleted_template(
    registry: ExpertTemplateRegistry,
) -> None:
    states = _matching_states(registry)
    upgraded = registry.get_template("medallion.standard")
    states[upgraded.template_id] = TemplateVersionState(
        record_id=uuid4(),
        template_id=upgraded.template_id,
        version="0.9.0",
        content_hash="9" * 64,
    )
    states["legacy.removed"] = TemplateVersionState(
        record_id=uuid4(),
        template_id="legacy.removed",
        version="1.0.0",
        content_hash="8" * 64,
    )
    repository = FakeExpertTemplateRepository(states)
    embedding_client = FakeEmbeddingClient()
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = await service.sync(registry)

    assert result.inserted_count == 1
    assert result.activated_count == 1
    assert result.inactivated_count == 2
    assert result.skipped_count == 36
    assert repository.publish_calls == 1
    snapshot = repository.snapshots[0]
    assert tuple(item.source.template_id for item in snapshot.templates) == ("medallion.standard",)
    assert "legacy.removed" not in snapshot.active_template_ids


@pytest.mark.asyncio
async def test_sync_rejects_version_downgrade(
    registry: ExpertTemplateRegistry,
) -> None:
    source = registry.get_template("medallion.standard")
    repository = FakeExpertTemplateRepository(
        {
            source.template_id: TemplateVersionState(
                record_id=uuid4(),
                template_id=source.template_id,
                version="9.0.0",
                content_hash="9" * 64,
            )
        }
    )
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=FakeEmbeddingClient(),
    )

    with pytest.raises(ExpertTemplateSyncError, match="不能低于数据库中的当前版本"):
        await service.sync(registry)

    assert repository.publish_calls == 0


def test_registry_fixture_remains_immutable(registry: ExpertTemplateRegistry) -> None:
    source = registry.templates[0]

    changed = replace(source, content_hash="f" * 64)

    assert changed.content_hash != source.content_hash
