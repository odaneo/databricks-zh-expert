import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.rag.chunker import KnowledgeChunk
from databricks_zh_expert.rag.cli import KnowledgeCliRuntime, create_parser, run_async
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.ingestion import KnowledgeIngestionService
from databricks_zh_expert.rag.repository import (
    CatalogPresenceResult,
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
    SourceKind,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge"
JOBS_URL = "https://docs.databricks.com/jobs/"
DELTA_URL = "https://docs.databricks.com/delta/"
JOBS_KEY = f"databricks-docs-{hashlib.sha256(JOBS_URL.encode()).hexdigest()[:24]}"
DELTA_KEY = f"databricks-docs-{hashlib.sha256(DELTA_URL.encode()).hexdigest()[:24]}"
API_CREATE_URL = "https://docs.databricks.com/api/markdown/Jobs/Jobs/Create.md"
API_CREATE_KEY = f"databricks-api-{hashlib.sha256(API_CREATE_URL.encode()).hexdigest()[:24]}"
PRICING_URL = "https://www.databricks.com/product/pricing"
PRICING_KEY = f"databricks-docs-{hashlib.sha256(PRICING_URL.encode()).hexdigest()[:24]}"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _manifest(tmp_path: Path, *, include_api: bool = False) -> Path:
    api_catalog = (
        """
  - id: databricks-api
    kind: databricks_api_llms_index
    index_url: https://docs.databricks.com/api/llms.txt
    cloud: aws
    locale: en
"""
        if include_api
        else ""
    )
    path = tmp_path / "sources.yml"
    path.write_text(
        f"""version: 2

ingestion:
  chunk_size_tokens: 120
  chunk_overlap_tokens: 20

catalogs:
  - id: databricks-docs
    kind: databricks_llms_index
    index_url: https://docs.databricks.com/llms.txt
    cloud: aws
    locale: en
{api_catalog}
""",
        encoding="utf-8",
    )
    return path


class _FakeFetcher:
    def __init__(
        self,
        *,
        include_delta: bool = False,
        include_external: bool = False,
        catalog_error: Exception | None = None,
        catalog_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.results: dict[str, FetchResult | Exception] = {}
        self.conditions: list[tuple[str, FetchCondition | None]] = []
        self.catalog_calls = 0
        self.catalog_error = catalog_error
        self.catalog_errors = catalog_errors or {}
        delta = f"- [Delta Lake]({DELTA_URL}) - Delta Lake guidance.\n" if include_delta else ""
        external = (
            f"- [Pricing]({PRICING_URL}) - Databricks pricing information.\n"
            if include_external
            else ""
        )
        self.catalog_content = (
            "# Databricks docs\n\n"
            "## Data engineering\n\n"
            f"- [Lakeflow Jobs]({JOBS_URL}) - Workflow guidance.\n"
            f"{delta}"
            f"{external}"
        )

    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult:
        self.catalog_calls += 1
        if self.catalog_error is not None:
            raise self.catalog_error
        if catalog.id in self.catalog_errors:
            raise self.catalog_errors[catalog.id]
        content = self.catalog_content
        if catalog.kind.value == "databricks_api_llms_index":
            content = (
                "# Databricks API\n\n"
                "## Jobs\n\n"
                "### Jobs\n\n"
                "- [Create](markdown/Jobs/Jobs/Create.md)\n"
            )
        return CatalogFetchResult(
            catalog_id=catalog.id,
            index_url=catalog.index_url,
            final_url=catalog.index_url,
            content_type="text/plain; charset=utf-8",
            content=content,
            etag='"catalog-v1"',
            last_modified="Fri, 10 Jul 2026 08:00:00 GMT",
        )

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult:
        self.conditions.append((source.source_key, condition))
        if source.kind is SourceKind.CATALOG_LINK:
            raise AssertionError(f"站外链接不得进入正文 fetcher：{source.url}")
        outcome = self.results.get(source.source_key)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        if source.kind is SourceKind.API_MARKDOWN:
            return FetchResult(
                source=source,
                status=FetchStatus.FETCHED,
                final_url=source.url,
                content_type="text/markdown; charset=utf-8",
                body=_fixture("api_page.md"),
                etag=f'"{source.source_key}-v1"',
                last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
            )
        title = source.title
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
    chunks: tuple[KnowledgeChunk, ...]


class _FakeRepository:
    def __init__(self) -> None:
        self.states: dict[str, DocumentState] = {}
        self.published: dict[str, _Published] = {}
        self.started_runs: list[tuple[UUID, str]] = []
        self.completions: list[tuple[UUID, IngestionRunCompletion]] = []
        self.checked: list[str] = []
        self.identity_batches: list[tuple[str, ...]] = []
        self.presence_calls: list[tuple[str, set[str]]] = []
        self.presence_result = CatalogPresenceResult(
            pending_missing_count=0,
            disabled_count=0,
        )
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

    async def reconcile_source_identities(
        self,
        sources: Sequence[DiscoveredSource],
    ) -> int:
        self.identity_batches.append(tuple(source.source_key for source in sources))
        self.write_count += 1
        return 0

    async def reconcile_catalog_presence(
        self,
        catalog_id: str,
        observed_source_keys: set[str],
        *,
        observed_at: object,
    ) -> CatalogPresenceResult:
        del observed_at
        self.presence_calls.append((catalog_id, set(observed_source_keys)))
        self.write_count += 1
        return self.presence_result

    async def publish_document(
        self,
        document: NormalizedDocument,
        *,
        content_hash: str,
        chunks: tuple[KnowledgeChunk, ...],
        embeddings: tuple[EmbeddingResult, ...],
        fetched_at: object,
    ) -> UUID:
        del fetched_at
        assert len(chunks) == len(embeddings)
        self.published[document.source.source_key] = _Published(
            document=document,
            content_hash=content_hash,
            chunk_count=len(chunks),
            chunks=chunks,
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

    title = source.title
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
    assert set(repository.published) == {JOBS_KEY}
    assert result.catalogs[0].discovered_count == 1
    assert result.catalogs[0].external_link_count == 0
    assert len(embeddings.calls) == 1
    assert repository.completions[0][1].status == "succeeded"


@pytest.mark.asyncio
async def test_catalog_link_is_published_without_fetching_target(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher(include_external=True)
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.status == "succeeded"
    assert result.discovered_count == 2
    assert result.changed_count == 2
    assert result.catalogs[0].discovered_count == 2
    assert result.catalogs[0].external_link_count == 1
    assert set(repository.published) == {JOBS_KEY, PRICING_KEY}
    assert tuple(source_key for source_key, _ in fetcher.conditions) == (JOBS_KEY,)
    assert repository.identity_batches == [(JOBS_KEY, PRICING_KEY)]
    assert repository.presence_calls == [
        ("databricks-docs", {JOBS_KEY, PRICING_KEY}),
    ]

    pricing = repository.published[PRICING_KEY]
    assert pricing.document.source.kind is SourceKind.CATALOG_LINK
    assert pricing.document.canonical_url == PRICING_URL
    assert pricing.chunk_count == 1
    assert pricing.chunks[0].source_ref == PRICING_URL
    assert "未抓取目标正文" in pricing.document.normalized_content
    assert len(embeddings.calls) == 2


@pytest.mark.asyncio
async def test_unchanged_catalog_link_skips_embedding_without_fetching_target(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    first_embeddings = _FakeEmbeddingClient()
    await _service(
        repository,
        _FakeFetcher(include_external=True),
        first_embeddings,
    ).sync(_manifest(tmp_path))
    repository.published.clear()
    repository.checked.clear()
    second_fetcher = _FakeFetcher(include_external=True)
    second_embeddings = _FakeEmbeddingClient()

    result = await _service(repository, second_fetcher, second_embeddings).sync(_manifest(tmp_path))

    assert result.changed_count == 0
    assert result.skipped_count == 2
    assert repository.published == {}
    assert set(repository.checked) == {JOBS_KEY, PRICING_KEY}
    assert tuple(source_key for source_key, _ in second_fetcher.conditions) == (JOBS_KEY,)
    assert second_embeddings.calls == []


@pytest.mark.asyncio
async def test_changed_catalog_link_summary_rebuilds_only_link(tmp_path: Path) -> None:
    repository = _FakeRepository()
    await _service(
        repository,
        _FakeFetcher(include_external=True),
        _FakeEmbeddingClient(),
    ).sync(_manifest(tmp_path))
    repository.published.clear()
    repository.checked.clear()
    changed_fetcher = _FakeFetcher(include_external=True)
    changed_fetcher.catalog_content = changed_fetcher.catalog_content.replace(
        "Databricks pricing information.",
        "Official Databricks pricing page.",
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, changed_fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.changed_count == 1
    assert result.skipped_count == 1
    assert set(repository.published) == {PRICING_KEY}
    assert repository.checked == [JOBS_KEY]
    assert len(embeddings.calls) == 1
    assert "Official Databricks pricing page." in embeddings.calls[0][0]


@pytest.mark.asyncio
async def test_dry_run_validates_catalog_link_without_fetching_target(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher(include_external=True)

    result = await _service(repository, fetcher, _FakeEmbeddingClient()).sync(
        _manifest(tmp_path),
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.discovered_count == 2
    assert result.skipped_count == 2
    assert tuple(source_key for source_key, _ in fetcher.conditions) == (JOBS_KEY,)
    assert repository.write_count == 0


@pytest.mark.asyncio
async def test_not_modified_skips_chunk_and_embedding(tmp_path: Path) -> None:
    repository = _FakeRepository()
    repository.states[JOBS_KEY] = DocumentState(
        id=uuid4(),
        source_key=JOBS_KEY,
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

    fetcher.results[JOBS_KEY] = await not_modified(
        DiscoveredSource(
            source_key=JOBS_KEY,
            kind=repository_state_source_kind(),
            title="Lakeflow Jobs",
            url=JOBS_URL,
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
    assert repository.checked == [JOBS_KEY]
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
        source_key=JOBS_KEY,
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url=JOBS_URL,
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
    assert repository.checked == [JOBS_KEY]


@pytest.mark.asyncio
async def test_disabled_source_requires_successful_body_fetch_before_reactivation(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    repository.states[JOBS_KEY] = DocumentState(
        id=uuid4(),
        source_key=JOBS_KEY,
        content_hash="old".ljust(64, "0"),
        etag='"existing"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        status="disabled",
        chunk_count=2,
    )
    fetcher = _FakeFetcher()
    fetcher.results[JOBS_KEY] = RuntimeError("temporary page failure")

    result = await _service(repository, fetcher, _FakeEmbeddingClient()).sync(_manifest(tmp_path))

    assert result.status == "failed"
    assert fetcher.conditions == [(JOBS_KEY, None)]
    assert repository.checked == []
    assert repository.published == {}


@pytest.mark.asyncio
async def test_disabled_source_reactivates_after_unchanged_body_is_verified(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    source = DiscoveredSource(
        source_key=JOBS_KEY,
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url=JOBS_URL,
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary=None,
    )
    repository.states[JOBS_KEY] = DocumentState(
        id=uuid4(),
        source_key=JOBS_KEY,
        content_hash=_normalized_hash(fetcher, source),
        etag='"existing"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
        status="disabled",
        chunk_count=2,
    )
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.skipped_count == 1
    assert fetcher.conditions == [(JOBS_KEY, None)]
    assert repository.checked == [JOBS_KEY]
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_only_changed_document_is_rebuilt(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    jobs_source = DiscoveredSource(
        source_key=JOBS_KEY,
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url=JOBS_URL,
        category=repository_state_category(),
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary=None,
    )
    delta_source = DiscoveredSource(
        source_key=DELTA_KEY,
        kind=repository_state_source_kind(),
        title="Delta Lake",
        url=DELTA_URL,
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

    result = await _service(repository, _FakeFetcher(include_delta=True), embeddings).sync(
        _manifest(tmp_path)
    )

    assert result.changed_count == 1
    assert result.skipped_count == 1
    assert set(repository.published) == {JOBS_KEY}
    assert len(embeddings.calls) == 1


@pytest.mark.asyncio
async def test_embedding_failure_preserves_old_document_and_marks_failed_run(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()
    old_state = DocumentState(
        id=uuid4(),
        source_key=JOBS_KEY,
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
            "source_key": JOBS_KEY,
            "code": "knowledge_source_failed",
            "error_type": "RuntimeError",
        },
    )


@pytest.mark.asyncio
async def test_partial_run_continues_after_one_source_fails(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher(include_delta=True)
    fetcher.results[DELTA_KEY] = RuntimeError("unsafe secret body")
    embeddings = _FakeEmbeddingClient()

    result = await _service(repository, fetcher, embeddings).sync(_manifest(tmp_path))

    assert result.status == "partial"
    assert result.changed_count == 1
    assert result.failed_count == 1
    assert set(repository.published) == {JOBS_KEY}
    assert "unsafe secret body" not in str(result)


@pytest.mark.asyncio
async def test_successful_catalog_reconciles_presence_from_discovered_urls(
    tmp_path: Path,
) -> None:
    repository = _FakeRepository()

    await _service(repository, _FakeFetcher(), _FakeEmbeddingClient()).sync(_manifest(tmp_path))

    assert repository.identity_batches == [(JOBS_KEY,)]
    assert repository.presence_calls == [("databricks-docs", {JOBS_KEY})]


@pytest.mark.asyncio
async def test_failed_catalog_does_not_reconcile_presence(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher(catalog_error=RuntimeError("temporary catalog failure"))

    result = await _service(repository, fetcher, _FakeEmbeddingClient()).sync(_manifest(tmp_path))

    assert result.status == "failed"
    assert result.failed_count == 1
    assert repository.identity_batches == []
    assert repository.presence_calls == []


@pytest.mark.parametrize(
    ("failed_catalog_id", "expected_catalog_id", "expected_source_keys"),
    (
        ("databricks-docs", "databricks-api", {API_CREATE_KEY}),
        ("databricks-api", "databricks-docs", {JOBS_KEY}),
    ),
)
@pytest.mark.asyncio
async def test_catalog_failure_does_not_block_other_catalog_presence_reconciliation(
    tmp_path: Path,
    failed_catalog_id: str,
    expected_catalog_id: str,
    expected_source_keys: set[str],
) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher(
        catalog_errors={failed_catalog_id: RuntimeError("temporary catalog failure")}
    )

    result = await _service(repository, fetcher, _FakeEmbeddingClient()).sync(
        _manifest(tmp_path, include_api=True)
    )

    assert result.status == "partial"
    assert result.failed_count == 1
    assert repository.presence_calls == [
        (expected_catalog_id, expected_source_keys),
    ]


@pytest.mark.asyncio
async def test_dry_run_fetches_all_discovered_sources_without_database_or_embedding_writes(
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
    assert tuple(source_key for source_key, _ in fetcher.conditions) == (JOBS_KEY,)
    assert repository.write_count == 0
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_force_rebuild_ignores_condition_and_equal_hash(tmp_path: Path) -> None:
    repository = _FakeRepository()
    fetcher = _FakeFetcher()
    source = DiscoveredSource(
        source_key=JOBS_KEY,
        kind=repository_state_source_kind(),
        title="Lakeflow Jobs",
        url=JOBS_URL,
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
    assert fetcher.conditions[0] == (JOBS_KEY, None)
    assert set(repository.published) == {JOBS_KEY}
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
    sync_payload = json.loads(output.splitlines()[0])
    assert sync_code == 0
    assert status_code == 0
    assert '"status": "dry_run"' in output
    assert '"queryable": false' in output
    assert sync_payload["catalogs"] == [
        {
            "catalog_id": "databricks-docs",
            "source_kind": "general_html",
            "discovered_count": 1,
            "duplicate_count": 0,
            "external_link_count": 0,
            "pending_missing_count": 0,
            "disabled_count": 0,
        }
    ]


def test_sync_cli_has_no_scope_or_all_mode() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(("sync", "--scope", "full"))
    with pytest.raises(SystemExit):
        parser.parse_args(("sync", "--all"))


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
