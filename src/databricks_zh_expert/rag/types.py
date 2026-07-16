from dataclasses import dataclass
from enum import StrEnum


class CatalogKind(StrEnum):
    DATABRICKS_DOCS = "databricks_llms_index"
    DATABRICKS_API = "databricks_api_llms_index"


class SourceKind(StrEnum):
    GENERAL_HTML = "general_html"
    API_MARKDOWN = "api_markdown"
    CATALOG_LINK = "catalog_link"


class FetchStatus(StrEnum):
    FETCHED = "fetched"
    NOT_MODIFIED = "not_modified"


class KnowledgeCategory(StrEnum):
    GENERAL = "general"
    ARCHITECTURE = "architecture"
    DELTA_LAKE = "delta_lake"
    DATA_ENGINEERING = "data_engineering"
    ORCHESTRATION = "orchestration"
    STREAMING = "streaming"
    GOVERNANCE = "governance"
    SQL = "sql"
    PERFORMANCE = "performance"
    COST = "cost"
    API = "api"


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    id: str
    kind: CatalogKind
    index_url: str
    cloud: str
    locale: str


@dataclass(frozen=True, slots=True)
class KnowledgeManifest:
    version: int
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    catalogs: tuple[SourceCatalog, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    source_key: str
    kind: SourceKind
    title: str
    url: str
    category: KnowledgeCategory
    catalog_id: str
    cloud: str
    locale: str
    topic: str
    summary: str | None


@dataclass(frozen=True, slots=True)
class CatalogDiscoveryResult:
    sources: tuple[DiscoveredSource, ...]
    external_links: tuple[DiscoveredSource, ...]
    duplicate_count: int

    @property
    def all_sources(self) -> tuple[DiscoveredSource, ...]:
        return (*self.sources, *self.external_links)


@dataclass(frozen=True, slots=True)
class FetchCondition:
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    source: DiscoveredSource
    status: FetchStatus
    final_url: str
    content_type: str | None
    body: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class CatalogFetchResult:
    catalog_id: str
    index_url: str
    final_url: str
    content_type: str
    content: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    source: DiscoveredSource
    title: str
    canonical_url: str
    normalized_content: str
    source_updated_at: str | None
    etag: str | None
    last_modified: str | None
    heading_anchors: tuple[str | None, ...] = ()
