import hashlib
import logging
from pathlib import Path

import httpx
import pytest

from databricks_zh_expert.rag.catalogs import (
    CatalogDiscoveryError,
    KnowledgeCatalogParser,
)
from databricks_zh_expert.rag.fetcher import KnowledgeFetcher, KnowledgeFetchError
from databricks_zh_expert.rag.normalizer import (
    KnowledgeNormalizationError,
    KnowledgeNormalizer,
)
from databricks_zh_expert.rag.types import (
    CatalogKind,
    DiscoveredSource,
    FetchCondition,
    FetchResult,
    FetchStatus,
    KnowledgeCategory,
    SourceCatalog,
    SourceKind,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _docs_catalog() -> SourceCatalog:
    return SourceCatalog(
        id="databricks-docs",
        kind=CatalogKind.DATABRICKS_DOCS,
        index_url="https://docs.databricks.com/llms.txt",
        cloud="aws",
        locale="en",
    )


def _api_catalog() -> SourceCatalog:
    return SourceCatalog(
        id="databricks-api",
        kind=CatalogKind.DATABRICKS_API,
        index_url="https://docs.databricks.com/api/llms.txt",
        cloud="aws",
        locale="en",
    )


def _expected_source_key(catalog_id: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"{catalog_id}-{digest}"


def _source(
    *,
    kind: SourceKind = SourceKind.GENERAL_HTML,
    url: str = "https://docs.databricks.com/jobs/",
) -> DiscoveredSource:
    return DiscoveredSource(
        source_key="docs-lakeflow-jobs" if kind is SourceKind.GENERAL_HTML else "api-jobs-create",
        kind=kind,
        title="Lakeflow Jobs" if kind is SourceKind.GENERAL_HTML else "Create a new job",
        url=url,
        category=(
            KnowledgeCategory.ORCHESTRATION
            if kind is SourceKind.GENERAL_HTML
            else KnowledgeCategory.API
        ),
        catalog_id="databricks-docs" if kind is SourceKind.GENERAL_HTML else "databricks-api",
        cloud="aws",
        locale="en",
        topic="Data engineering" if kind is SourceKind.GENERAL_HTML else "Jobs",
        summary="Official Databricks guidance.",
    )


def _fetched(
    *,
    source: DiscoveredSource | None = None,
    body: str | None = None,
    content_type: str | None = "text/html; charset=utf-8",
    final_url: str = "https://docs.databricks.com/aws/en/jobs/",
    status: FetchStatus = FetchStatus.FETCHED,
) -> FetchResult:
    return FetchResult(
        source=source or _source(),
        status=status,
        final_url=final_url,
        content_type=content_type,
        body=_fixture("docs_page.html") if body is None else body,
        etag='"jobs-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
    )


def test_general_catalog_returns_every_unique_official_page_and_external_links() -> None:
    catalog = _docs_catalog()

    result = KnowledgeCatalogParser().discover(_fixture("databricks_llms.txt"), catalog)

    assert tuple(source.url for source in result.sources) == (
        "https://docs.databricks.com/delta/",
        "https://docs.databricks.com/compute/",
        "https://docs.databricks.com/jobs/",
        "https://docs.databricks.com/ingestion/cloud-object-storage/auto-loader/",
        "https://docs.databricks.com/future/",
    )
    assert result.sources[0].source_key == _expected_source_key(
        "databricks-docs",
        "https://docs.databricks.com/delta/",
    )
    assert result.sources[0].title == "Delta Lake"
    assert result.sources[0].topic == "Core platform"
    assert result.sources[0].summary == "Delta Lake concepts and guidance."
    assert result.sources[0].kind is SourceKind.GENERAL_HTML
    assert result.sources[-1].category is KnowledgeCategory.GENERAL
    assert result.duplicate_count == 1
    assert tuple((link.title, link.url) for link in result.external_links) == (
        ("Pricing", "https://www.databricks.com/product/pricing"),
        ("Databricks Academy", "https://www.databricks.com/learn/training/home"),
    )
    pricing = result.external_links[0]
    assert pricing.source_key == _expected_source_key(
        "databricks-docs",
        "https://www.databricks.com/product/pricing",
    )
    assert pricing.kind is SourceKind.CATALOG_LINK
    assert pricing.category is KnowledgeCategory.GENERAL
    assert pricing.catalog_id == "databricks-docs"
    assert pricing.cloud == "aws"
    assert pricing.locale == "en"
    assert pricing.topic == "Additional resources"
    assert pricing.summary == "External resources are links only."
    assert result.all_sources == (*result.sources, *result.external_links)
    assert all(source.url != catalog.index_url for source in result.sources)
    assert all(
        not source.url.startswith("https://docs.databricks.com/api/") for source in result.sources
    )


def test_catalog_source_key_depends_on_catalog_and_normalized_url_only() -> None:
    catalog = _docs_catalog()
    first = KnowledgeCatalogParser().discover(
        "## Topic\n\n- [First title](https://docs.databricks.com/delta/#overview)",
        catalog,
    )
    second = KnowledgeCatalogParser().discover(
        "## Renamed topic\n\n- [Renamed title](https://docs.databricks.com/delta/)",
        catalog,
    )

    assert first.sources[0].source_key == second.sources[0].source_key
    assert first.sources[0].url == "https://docs.databricks.com/delta/"


def test_general_catalog_rejects_unsafe_official_page() -> None:
    catalog = _docs_catalog()

    with pytest.raises(CatalogDiscoveryError) as error:
        KnowledgeCatalogParser().discover(
            "## Topic\n\n- [Unsafe](http://docs.databricks.com/delta/)",
            catalog,
        )

    assert "HTTPS" in str(error.value)


@pytest.mark.parametrize(
    "url",
    (
        "http://www.databricks.com/product/pricing",
        "https://user:password@www.databricks.com/product/pricing",
        "https://www.databricks.com:8443/product/pricing",
    ),
)
def test_general_catalog_rejects_unsafe_external_link(url: str) -> None:
    with pytest.raises(CatalogDiscoveryError):
        KnowledgeCatalogParser().discover(
            f"## Resources\n\n- [Pricing]({url})",
            _docs_catalog(),
        )


def test_catalog_link_normalization_uses_only_directory_metadata() -> None:
    source = DiscoveredSource(
        source_key=_expected_source_key(
            "databricks-docs",
            "https://www.databricks.com/product/pricing",
        ),
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

    document = KnowledgeNormalizer().normalize_catalog_link(source)

    assert document.title == "Pricing"
    assert document.canonical_url == source.url
    assert document.etag is None
    assert document.last_modified is None
    assert document.source_updated_at is None
    assert document.normalized_content == (
        "资料类型：官方目录链接（未抓取目标正文）\n\n"
        "标题：Pricing\n\n"
        "目录摘要：Databricks pricing information.\n\n"
        "官方链接：https://www.databricks.com/product/pricing\n"
    )
    assert "$" not in document.normalized_content
    assert "DBU" not in document.normalized_content


def test_api_catalog_returns_every_operation_in_official_order() -> None:
    catalog = _api_catalog()

    result = KnowledgeCatalogParser().discover(_fixture("databricks_api_llms.txt"), catalog)

    assert tuple(source.title for source in result.sources) == (
        "Create a new job",
        "Get a single job",
        "Delete a job",
        "Create a pipeline",
        "Edit a pipeline",
        "Create a warehouse",
    )
    assert result.sources[0].topic == "Jobs"
    assert result.sources[0].url == ("https://docs.databricks.com/api/markdown/Jobs/Jobs/Create.md")
    assert result.sources[0].kind is SourceKind.API_MARKDOWN
    assert all(source.category is KnowledgeCategory.API for source in result.sources)
    assert result.external_links == ()
    assert result.duplicate_count == 0


def test_api_catalog_discovers_every_operation_in_current_format_fixture() -> None:
    result = KnowledgeCatalogParser().discover(
        _fixture("databricks_api_llms_current.txt"),
        _api_catalog(),
    )

    assert len(result.sources) == 7
    assert len({source.url for source in result.sources}) == 7
    assert len({source.source_key for source in result.sources}) == 7
    assert {"Jobs", "Pipelines", "Warehouses"} <= {source.topic for source in result.sources}


@pytest.mark.asyncio
async def test_fetch_sends_conditional_headers_and_handles_not_modified() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(304, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeFetcher(client).fetch(
            _source(),
            FetchCondition(etag='"jobs-v1"', last_modified="Fri, 10 Jul 2026 08:30:00 GMT"),
        )

    assert result.status is FetchStatus.NOT_MODIFIED
    assert result.body is None
    assert captured[0].headers["if-none-match"] == '"jobs-v1"'
    assert captured[0].headers["if-modified-since"] == "Fri, 10 Jul 2026 08:30:00 GMT"
    assert "databricks-zh-expert" in captured[0].headers["user-agent"]
    assert "authorization" not in captured[0].headers


@pytest.mark.asyncio
async def test_fetch_follows_same_host_https_redirect() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/jobs/":
            return httpx.Response(302, headers={"Location": "/aws/en/jobs/"}, request=request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=_fixture("docs_page.html"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeFetcher(client).fetch(_source(), None)

    assert requested_urls == [
        "https://docs.databricks.com/jobs/",
        "https://docs.databricks.com/aws/en/jobs/",
    ]
    assert result.status is FetchStatus.FETCHED
    assert result.final_url == "https://docs.databricks.com/aws/en/jobs/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "http://docs.databricks.com/aws/en/jobs/",
        "https://example.com/jobs/",
        "https://127.0.0.1/jobs/",
        "https://localhost/jobs/",
    ],
)
async def test_fetch_rejects_unsafe_redirect(location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeFetchError):
            await KnowledgeFetcher(client).fetch(_source(), None)


@pytest.mark.asyncio
async def test_fetch_rejects_unsafe_initial_url_before_request() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeFetchError):
            await KnowledgeFetcher(client).fetch(
                _source(url="http://docs.databricks.com/jobs/"),
                None,
            )

    assert request_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "content_type"),
    [
        (SourceKind.GENERAL_HTML, "application/json"),
        (SourceKind.API_MARKDOWN, "text/html"),
    ],
)
async def test_fetch_rejects_unexpected_content_type(
    kind: SourceKind,
    content_type: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": content_type},
            text="wrong content",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeFetchError) as error:
            await KnowledgeFetcher(client).fetch(_source(kind=kind), None)

    assert "Content-Type" in str(error.value)


@pytest.mark.asyncio
async def test_fetch_rejects_document_larger_than_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"x" * (5 * 1024 * 1024 + 1),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeFetchError) as error:
            await KnowledgeFetcher(client).fetch(_source(), None)

    assert "5 MiB" in str(error.value)


@pytest.mark.asyncio
async def test_fetch_retries_429_and_server_errors_at_most_twice() -> None:
    statuses = iter((429, 503, 200))
    attempts = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = next(statuses)
        return httpx.Response(
            status,
            headers={
                "Content-Type": "text/html",
                "Retry-After": "0",
            },
            text=_fixture("docs_page.html") if status == 200 else "temporary failure",
            request=request,
        )

    async def sleep(delay: float) -> None:
        waits.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeFetcher(client, sleep=sleep).fetch(_source(), None)

    assert result.status is FetchStatus.FETCHED
    assert attempts == 3
    assert waits == [0.0, 0.0]


@pytest.mark.asyncio
async def test_fetch_does_not_retry_client_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="unsafe body with openai-secret", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeFetchError):
            await KnowledgeFetcher(client).fetch(_source(), None)

    assert attempts == 1


@pytest.mark.asyncio
async def test_fetch_accepts_large_official_html_within_five_mib() -> None:
    payload = b"x" * (3 * 1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=payload,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeFetcher(client).fetch(_source(), None)

    assert result.body is not None
    assert len(result.body) == len(payload)


@pytest.mark.asyncio
async def test_fetch_logs_do_not_include_response_body_or_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Authorization: Bearer openai-secret", request=request)

    async def sleep(delay: float) -> None:
        del delay

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.WARNING), pytest.raises(KnowledgeFetchError):
            await KnowledgeFetcher(client, sleep=sleep).fetch(_source(), None)

    assert "openai-secret" not in caplog.text
    assert "Authorization" not in caplog.text


@pytest.mark.asyncio
async def test_fetch_catalog_accepts_plain_text_and_enforces_larger_limit() -> None:
    catalog = _docs_catalog()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain; charset=utf-8"},
            text=_fixture("databricks_llms.txt"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeFetcher(client).fetch_catalog(catalog)

    assert result.content == _fixture("databricks_llms.txt")
    assert result.final_url == catalog.index_url


def test_normalize_html_extracts_only_article_and_preserves_markdown() -> None:
    document = KnowledgeNormalizer().normalize(_fetched())

    assert document.title == "Lakeflow Jobs"
    assert document.canonical_url == "https://docs.databricks.com/aws/en/jobs/"
    assert document.source_updated_at == "2026-07-10T08:30:00Z"
    assert "# Lakeflow Jobs" in document.normalized_content
    assert "## Configure tasks" in document.normalized_content
    assert "- Use unique task keys." in document.normalized_content
    assert "| Setting | Purpose |" in document.normalized_content
    assert '```python\nprint("run job")\n```' in document.normalized_content
    assert "[Configure job tasks](https://docs.databricks.com/jobs/configure-task)" in (
        document.normalized_content
    )
    assert "[Apache Spark](https://spark.apache.org/docs/latest/)" in (document.normalized_content)
    assert "![Spark logo](https://spark.apache.org/images/spark-logo-trademark.png)" in (
        document.normalized_content
    )
    assert "Global navigation" not in document.normalized_content
    assert "Table of contents" not in document.normalized_content
    assert "Footer" not in document.normalized_content
    assert "feedback" not in document.normalized_content
    assert "secretNavigationState" not in document.normalized_content


def test_normalize_html_removes_heading_permalinks_and_preserves_official_anchors() -> None:
    body = (
        _fixture("docs_page.html")
        .replace(
            "<h1>Lakeflow Jobs</h1>",
            '<h1 id="lakeflow-jobs">Lakeflow Jobs'
            '<a href="#lakeflow-jobs" class="hash-link" '
            'aria-label="Direct link to Lakeflow Jobs" '
            'title="Direct link to Lakeflow Jobs">\u200b</a></h1>',
        )
        .replace(
            "<h2>Configure tasks</h2>",
            '<h2 id="configure-tasks">Configure tasks'
            '<a href="#configure-tasks" class="hash-link" '
            'aria-label="Direct link to Configure tasks" '
            'title="Direct link to Configure tasks">\u200b</a></h2>',
        )
    )

    document = KnowledgeNormalizer().normalize(_fetched(body=body))

    assert document.title == "Lakeflow Jobs"
    assert document.heading_anchors == ("lakeflow-jobs", "configure-tasks")
    assert "# Lakeflow Jobs\n" in document.normalized_content
    assert "## Configure tasks\n" in document.normalized_content
    assert "Direct link to" not in document.normalized_content
    assert "hash-link" not in document.normalized_content


def test_normalize_html_accepts_plain_article_fallback() -> None:
    body = _fixture("docs_page.html").replace(
        'class="theme-doc-markdown markdown"',
        'class="plain-article"',
    )

    document = KnowledgeNormalizer().normalize(_fetched(body=body))

    assert document.title == "Lakeflow Jobs"


def test_normalize_html_repairs_deeply_nested_table_markup() -> None:
    malformed_rows = "".join(
        f"<tr><td><p>System table {index}<td><p>Description {index}" for index in range(300)
    )
    body = (
        "<html><head>"
        '<link rel="canonical" href="https://docs.databricks.com/admin/system-tables/">'
        "</head><body>"
        '<article class="theme-doc-markdown markdown">'
        "<h1>System tables</h1>"
        "<p>Use system tables to observe account usage and operational data.</p>"
        f"<table><tbody>{malformed_rows}</tbody></table>"
        "</article></body></html>"
    )

    document = KnowledgeNormalizer().normalize(_fetched(body=body))

    assert document.title == "System tables"
    assert "System table 0" in document.normalized_content
    assert "Description 299" in document.normalized_content


def test_normalize_api_markdown_preserves_source_structure() -> None:
    source = _source(
        kind=SourceKind.API_MARKDOWN,
        url="https://docs.databricks.com/api/markdown/Jobs/Jobs/Create.md",
    )
    fetched = _fetched(
        source=source,
        body=_fixture("api_page.md"),
        content_type="text/markdown; charset=utf-8",
        final_url=source.url,
    )

    document = KnowledgeNormalizer().normalize(fetched)

    assert document.title == "Create a new job"
    assert document.canonical_url == source.url
    assert "| Field | Type | Description |" in document.normalized_content
    assert '```json\n{\n  "name": "daily-sales"' in document.normalized_content
    assert document.normalized_content.endswith("\n")


def test_normalize_rejects_missing_article() -> None:
    body = "<html><body><main><p>No article exists on this page.</p></main></body></html>"

    with pytest.raises(KnowledgeNormalizationError) as error:
        KnowledgeNormalizer().normalize(_fetched(body=body))

    assert "article" in str(error.value)


def test_normalize_rejects_short_content() -> None:
    body = "<html><body><article><h1>Short</h1><p>Too short.</p></article></body></html>"

    with pytest.raises(KnowledgeNormalizationError) as error:
        KnowledgeNormalizer().normalize(_fetched(body=body))

    assert "过短" in str(error.value)


def test_normalize_rejects_not_modified_result() -> None:
    with pytest.raises(KnowledgeNormalizationError):
        KnowledgeNormalizer().normalize(
            _fetched(status=FetchStatus.NOT_MODIFIED, body="", content_type=None)
        )
