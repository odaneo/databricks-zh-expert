import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.rag.cli import KnowledgeCliRuntime, run_async
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.ingestion import KnowledgeIngestionService
from databricks_zh_expert.rag.repository import (
    DocumentState,
    IngestionRunCompletion,
    KnowledgeIndexStatus,
)
from databricks_zh_expert.rag.types import (
    CatalogFetchResult,
    DiscoveredSource,
    FetchCondition,
    FetchResult,
    FetchStatus,
    NormalizedDocument,
    SourceCatalog,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _manifest(tmp_path: Path, *, include_delta: bool = False) -> Path:
    documents = (
        """
      - source_key: docs-delta-lake
        url: https://docs.databricks.com/delta/
        category: delta_lake
"""
        if include_delta
        else ""
    )
    path = tmp_path / "sources.yml"
    path.write_text(
        f"""version: 1

ingestion:
  chunk_size_tokens: 120
  chunk_overlap_tokens: 20

catalogs:
  - id: databricks-docs
    kind: databricks_llms_index
    index_url: https://docs.databricks.com/llms.txt
    cloud: aws
    locale: en
    include_urls:
      - source_key: docs-lakeflow-jobs
        url: https://docs.databricks.com/jobs/
        category: orchestration
{documents}
""",
        encoding="utf-8",
    )
    return path


class _FakeFetcher:
    def __init__(self) -> None:
        self.results: dict[str, FetchResult | Exception] = {}
        self.conditions: list[tuple[str, FetchCondition | None]] = []
        self.catalog_calls = 0

    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult:
        self.catalog_calls += 1
        return CatalogFetchResult(
            catalog_id=catalog.id,
            index_url=catalog.index_url,
            final_url=catalog.index_url,
            content_type="text/plain; charset=utf-8",
            content=_fixture("databricks_llms.txt"),
            etag='"catalog-v1"',
            last_modified="Fri, 10 Jul 2026 08:00:00 GMT",
        )

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult:
        self.conditions.append((source.source_key, condition))
        outcome = self.results.get(source.source_key)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        title = "Delta Lake" if source.source_key == "docs-delta-lake" else "Lakeflow Jobs"
        body = _fixture("docs_page.html").replace("Lakeflow Jobs", title)
        return FetchResult(
            source=source,
            status=FetchStatus.FETCHED,
            final_url=source.url,
            content_type="text/html; charset=utf-8",
            body=body,
            etag=f'"{source.source_key}-v1"',
            last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        )


class _FakeEmbeddingClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []

    async def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingResult, ...]:
        self.calls.append(tuple(texts))
        if self.fail:
            raise RuntimeError("provider secret must not escape")
        return tuple(
            EmbeddingResult(index=index, embedding=(float(index + 1),) * 1536)
            for index in range(len(texts))
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        del text
        raise AssertionError("同步不应调用 embed_query")


@dataclass(slots=True)
class _Published:
    document: NormalizedDocument
    content_hash: str
    chunk_count: int


class _FakeRepository:
    def __init__(self) -> None:
        self.states: dict[str, DocumentState] = {}
        self.published: dict[str, _Published] = {}
        self.started_runs: list[tuple[UUID, str]] = []
        self.completions: list[tuple[UUID, IngestionRunCompletion]] = []
        self.checked: list[str] = []
        self.disabled_keys: set[str] = set()
        self.write_count = 0

    async def start_run(self, manifest_hash: str) -> UUID:
        run_id = uuid4()
        self.started_runs.append((run_id, manifest_hash))
        self.write_count += 1
        return run_id

    async def finish_run(self, run_id: UUID, completion: IngestionRunCompletion) -> None:
        self.completions.append((run_id, completion))
        self.write_count += 1

    async def get_document_state(self, source_key: str) -> DocumentState | None:
        return self.states.get(source_key)

    async def publish_document(
        self,
        document: NormalizedDocument,
        *,
        content_hash: str,
        chunks: tuple[object, ...],
        embeddings: tuple[EmbeddingResult, ...],
        fetched_at: object,
    ) -> UUID:
        del fetched_at
        assert len(chunks) == len(embeddings)
        self.published[document.source.source_key] = _Published(
            document=document,
            content_hash=content_hash,
            chunk_count=len(chunks),
        )
        self.states[document.source.source_key] = DocumentState(
            id=uuid4(),
            source_key=document.source.source_key,
            content_hash=content_hash,
            etag=document.etag,
            last_modified=document.last_modified,
            status="active",
            chunk_count=len(chunks),
        )
        self.write_count += 1
        return self.states[document.source.source_key].id

    async def mark_document_checked(
        self,
        source_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        fetched_at: object,
    ) -> None:
        del etag, last_modified, fetched_at
        self.checked.append(source_key)
        self.write_count += 1

    async def disable_missing_sources(self, active_source_keys: set[str]) -> int:
        self.disabled_keys = set(self.states) - active_source_keys
        self.write_count += 1
        return len(self.disabled_keys)

    async def get_index_status(self) -> KnowledgeIndexStatus:
        return KnowledgeIndexStatus(
            last_run_status="succeeded",
            active_document_count=len(self.states),
            chunk_count=sum(state.chunk_count for state in self.states.values()),
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            queryable=bool(self.states),
        )


def _service(
    repository: _FakeRepository,
    fetcher: _FakeFetcher,
    embeddings: _FakeEmbeddingClient,
) -> KnowledgeIngestionService:
    return KnowledgeIngestionService(
        repository=repository,
        fetcher=fetcher,
        embedding_client=embeddings,
    )


def _normalized_hash(fetcher: _FakeFetcher, source: DiscoveredSource) -> str:
    from databricks_zh_expert.rag.normalizer import KnowledgeNormalizer

    title = "Delta Lake" if source.source_key == "docs-delta-lake" else "Lakeflow Jobs"
    fetched = FetchResult(
        source=source,
        status=FetchStatus.FETCHED,
        final_url=source.url,
        content_type="text/html; charset=utf-8",
        body=_fixture("docs_page.html").replace("Lakeflow Jobs", title),
        etag=f'"{source.source_key}-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
    )
    del fetcher
    content = KnowledgeNormalizer().normalize(fetched).normalized_content
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_first_sync_publishes_document_and_succeeded_run(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.status == "succeeded"
    assert result.discovered_count == 1
    assert result.changed_count == 1
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert result.chunk_count > 0
    assert set(repository.published) == {"docs-lakeflow-jobs"}
    assert len(embeddings.calls) == 1
    assert repository.completions[0][1].status == "succeeded"


@pytest.mark.asyncio
async def test_not_modified_skips_chunk_and_embedding(tmp_path: Path) -> None:
    repository = _FakeRepository()
    repository.states["docs-lakeflow-jobs"] = DocumentState(
        id=uuid4(),
        source_key="docs-lakeflow-jobs",
        content_hash="a" * 64,
        etag='"jobs-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        status="active",
        chunk_count=2,
    )
    fetcher = _FakeFetcher()

    async def not_modified(source: DiscoveredSource) -> FetchResult:
        return FetchResult(
            source=source,
            status=FetchStatus.NOT_MODIFIED,
            final_url=source.url,
            content_type=None,
            body=None,
            etag='"jobs-v1"',
            last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        )

    fetcher.results["docs-lakeflow-jobs"] = await not_modified(
        DiscoveredSource(
            source_key="docs-lakeflow-jobs",
            kind=repository_state_source_kind(),
            title="Lakeflow Jobs",
            url="https://docs.databricks.com/jobs/",
            category=repository_state_category(),
            catalog_id="databricks-docs",
            cloud="aws",
            locale="en",
            topic="Data engineering",
            summary=None,
        )
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.skipped_count == 1
    assert embeddings.calls == []
    assert repository.published == {}
    assert repository.checked == ["docs-lakeflow-jobs"]
    assert fetcher.conditions[0][1] == FetchCondition(
        etag='"jobs-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
    )


def repository_state_source_kind():
    from databricks_zh_expert.rag.types import SourceKind

    return SourceKind.GENERAL_HTML


def repository_state_category():
    from databricks_zh_expert.rag.types import KnowledgeCategory

    return KnowledgeCategory.ORCHESTRATION


@pytest.mark.asyncio
async def test_same_normalized_hash_skips_embedding(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    source = DiscoveredSource(
        source_key="docs-lakeflow-jobs",
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/jobs/",
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary=None,
    )
    repository.states[source.source_key] = DocumentState(
        id=uuid4(),
        source_key=source.source_key,
        content_hash=_normalized_hash(fetcher, source),
        etag='"old"',
        last_modified=None,
        status="active",
        chunk_count=3,
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.skipped_count == 1
    assert embeddings.calls == []
    assert repository.published == {}
    assert repository.checked == ["docs-lakeflow-jobs"]


@pytest.mark.asyncio
async def test_only_changed_document_is_rebuilt(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    jobs_source = DiscoveredSource(
        source_key="docs-lakeflow-jobs",
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/jobs/",
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary=None,
    )
    delta_source = DiscoveredSource(
        source_key="docs-delta-lake",
        kind=repository_state_source_kind(),
        title="Delta Lake",
        url="https://docs.databricks.com/delta/",
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Core platform",
        summary=None,
    )
    repository.states[jobs_source.source_key] = DocumentState(
        id=uuid4(),
        source_key=jobs_source.source_key,
        content_hash="old".ljust(64, "0"),
        etag=None,
        last_modified=None,
        status="active",
        chunk_count=1,
    )
    repository.states[delta_source.source_key] = DocumentState(
        id=uuid4(),
        source_key=delta_source.source_key,
        content_hash=_normalized_hash(fetcher, delta_source),
        etag=None,
        last_modified=None,
        status="active",
        chunk_count=2,
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(
        _manifest(tmp_path, include_delta=True)
    )

    assert result.changed_count == 1
    assert result.skipped_count == 1
    assert set(repository.published) == {"docs-lakeflow-jobs"}
    assert len(embeddings.calls) == 1


@pytest.mark.asyncio
async def test_embedding_failure_preserves_old_document_and_marks_failed_run(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    old_state = DocumentState(
        id=uuid4(),
        source_key="docs-lakeflow-jobs",
        content_hash="old".ljust(64, "0"),
        etag=None,
        last_modified=None,
        status="active",
        chunk_count=2,
    )
    repository.states[old_state.source_key] = old_state
    embeddings = _FakeEmbeddingClient(fail=True)

    result = await _service(repository, _FakeFetcher(), embeddings).sync(_manifest(tmp_path))

    assert result.status == "failed"
    assert result.failed_count == 1
    assert repository.states[old_state.source_key] == old_state
    assert repository.published == {}
    assert repository.completions[0][1].error_summary == (
        {
            "source_key": "docs-lakeflow-jobs",
            "code": "knowledge_source_failed",
            "error_type": "RuntimeError",
        },
    )


@pytest.mark.asyncio
async def test_partial_run_continues_after_one_source_fails(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    fetcher.results["docs-delta-lake"] = RuntimeError("unsafe secret body")
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(
        _manifest(tmp_path, include_delta=True)
    )

    assert result.status == "partial"
    assert result.changed_count == 1
    assert result.failed_count == 1
    assert set(repository.published) == {"docs-lakeflow-jobs"}
    assert "unsafe secret body" not in str(result)


@pytest.mark.asyncio
async def test_removed_manifest_source_is_disabled_not_deleted(tmp_path: Path) -> None:
    repository = _FakeRepository()
    repository.states["docs-removed"] = DocumentState(
        id=uuid4(),
        source_key="docs-removed",
        content_hash="a" * 64,
        etag=None,
        last_modified=None,
        status="active",
        chunk_count=4,
    )

    await _service(repository, _FakeFetcher(), _FakeEmbeddingClient()).sync(_manifest(tmp_path))

    assert repository.disabled_keys == {"docs-removed"}
    assert "docs-removed" in repository.states


@pytest.mark.asyncio
async def test_dry_run_fetches_allowlisted_sources_without_database_or_embedding_writes(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(
        _manifest(tmp_path),
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.discovered_count == 1
    assert fetcher.catalog_calls == 1
    assert tuple(source_key for source_key, _ in fetcher.conditions) == ("docs-lakeflow-jobs",)
    assert repository.write_count == 0
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_force_rebuild_ignores_condition_and_equal_hash(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    source = DiscoveredSource(
        source_key="docs-lakeflow-jobs",
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/jobs/",
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary=None,
    )
    repository.states[source.source_key] = DocumentState(
        id=uuid4(),
        source_key=source.source_key,
        content_hash=_normalized_hash(fetcher, source),
        etag='"existing"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        status="active",
        chunk_count=2,
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(
        _manifest(tmp_path),
        force=True,
    )

    assert result.changed_count == 1
    assert fetcher.conditions[0] == ("docs-lakeflow-jobs", None)
    assert set(repository.published) == {"docs-lakeflow-jobs"}
    assert len(embeddings.calls) == 1


@pytest.mark.asyncio
async def test_cli_dry_run_and_status_use_injected_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _FakeRepository()
    service = _service(repository, _FakeFetcher(), _FakeEmbeddingClient())
    runtime = KnowledgeCliRuntime(
        service=service,
        repository=repository,
        manifest_path=_manifest(tmp_path),
    )

    sync_code = await run_async(("sync", "--dry-run"), runtime)
    status_code = await run_async(("status",), runtime)

    output = capsys.readouterr().out
    assert sync_code == 0
    assert status_code == 0
    assert '"status": "dry_run"' in output
    assert '"queryable": false' in output


@pytest.mark.asyncio
async def test_cli_invalid_manifest_returns_exit_two_without_database_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid_manifest = tmp_path / "invalid.yml"
    invalid_manifest.write_text("version: invalid\n", encoding="utf-8")
    repository = _FakeRepository()
    runtime = KnowledgeCliRuntime(
        service=_service(repository, _FakeFetcher(), _FakeEmbeddingClient()),
        repository=repository,
        manifest_path=invalid_manifest,
    )

    exit_code = await run_async(("sync",), runtime)

    output = capsys.readouterr()
    assert exit_code == 2
    assert "知识来源清单无效" in output.err
    assert repository.write_count == 0
