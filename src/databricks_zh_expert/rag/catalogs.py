import hashlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from databricks_zh_expert.rag.types import (
    CatalogDiscoveryResult,
    CatalogKind,
    DiscoveredSource,
    KnowledgeCategory,
    SourceCatalog,
    SourceKind,
)
from databricks_zh_expert.rag.urls import UnsafeOfficialUrlError, validate_official_url


class CatalogDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _CatalogLink:
    topic: str
    title: str
    href: str
    summary: str | None


_GENERAL_TOPIC_CATEGORIES = {
    "overview and getting started": KnowledgeCategory.ARCHITECTURE,
    "core platform": KnowledgeCategory.ARCHITECTURE,
    "data sources and formats": KnowledgeCategory.DATA_ENGINEERING,
    "data engineering": KnowledgeCategory.DATA_ENGINEERING,
    "sql and analytics": KnowledgeCategory.SQL,
    "data governance and security": KnowledgeCategory.GOVERNANCE,
    "integrations and connectors": KnowledgeCategory.DATA_ENGINEERING,
    "migration and best practices": KnowledgeCategory.ARCHITECTURE,
}
_CATALOG_INDEX_URLS = frozenset(
    {
        "https://docs.databricks.com/llms.txt",
        "https://docs.databricks.com/api/llms.txt",
    }
)


class KnowledgeCatalogParser:
    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark")

    def discover(
        self,
        index_content: str,
        catalog: SourceCatalog,
    ) -> CatalogDiscoveryResult:
        links = self._parse_links(index_content)
        sources: list[DiscoveredSource] = []
        external_links: list[DiscoveredSource] = []
        seen_urls: set[str] = set()
        duplicate_count = 0

        for link in links:
            url, is_official = self._resolve_link(catalog.index_url, link.href)
            if url in seen_urls:
                duplicate_count += 1
                continue
            seen_urls.add(url)

            if not is_official:
                external_links.append(
                    DiscoveredSource(
                        source_key=self._source_key(catalog.id, url),
                        kind=SourceKind.CATALOG_LINK,
                        title=link.title,
                        url=url,
                        category=(
                            self._general_category(link.topic)
                            if catalog.kind is CatalogKind.DATABRICKS_DOCS
                            else KnowledgeCategory.API
                        ),
                        catalog_id=catalog.id,
                        cloud=catalog.cloud,
                        locale=catalog.locale,
                        topic=link.topic,
                        summary=link.summary,
                    )
                )
                continue
            if url in _CATALOG_INDEX_URLS or (
                catalog.kind is CatalogKind.DATABRICKS_DOCS
                and urlsplit(url).path.startswith("/api/")
            ):
                continue

            kind = (
                SourceKind.GENERAL_HTML
                if catalog.kind is CatalogKind.DATABRICKS_DOCS
                else SourceKind.API_MARKDOWN
            )
            category = (
                self._general_category(link.topic)
                if kind is SourceKind.GENERAL_HTML
                else KnowledgeCategory.API
            )
            sources.append(
                DiscoveredSource(
                    source_key=self._source_key(catalog.id, url),
                    kind=kind,
                    title=link.title,
                    url=url,
                    category=category,
                    catalog_id=catalog.id,
                    cloud=catalog.cloud,
                    locale=catalog.locale,
                    topic=link.topic,
                    summary=link.summary,
                )
            )

        return CatalogDiscoveryResult(
            sources=tuple(sources),
            external_links=tuple(external_links),
            duplicate_count=duplicate_count,
        )

    def _parse_links(self, content: str) -> tuple[_CatalogLink, ...]:
        tokens = self._markdown.parse(content)
        current_topic = ""
        links: list[_CatalogLink] = []

        for index, token in enumerate(tokens):
            if token.type == "heading_open":
                if token.tag in {"h2", "h3"} and index + 1 < len(tokens):
                    current_topic = tokens[index + 1].content.strip()
                continue
            if token.type != "inline" or (index > 0 and tokens[index - 1].type == "heading_open"):
                continue
            links.extend(self._inline_links(token, current_topic))
        return tuple(links)

    @staticmethod
    def _inline_links(token: Token, topic: str) -> tuple[_CatalogLink, ...]:
        children = token.children or []
        links: list[_CatalogLink] = []
        index = 0
        while index < len(children):
            child = children[index]
            if child.type != "link_open":
                index += 1
                continue

            href = child.attrGet("href")
            index += 1
            title_parts: list[str] = []
            while index < len(children) and children[index].type != "link_close":
                title_parts.append(children[index].content)
                index += 1
            index += 1

            summary_parts: list[str] = []
            while index < len(children) and children[index].type != "link_open":
                summary_parts.append(children[index].content)
                index += 1
            title = "".join(title_parts).strip()
            summary = "".join(summary_parts).strip().lstrip("-–— ").strip()
            if isinstance(href, str) and href and title:
                links.append(
                    _CatalogLink(
                        topic=topic,
                        title=title,
                        href=href,
                        summary=summary or None,
                    )
                )
        return tuple(links)

    @staticmethod
    def _resolve_link(index_url: str, href: str) -> tuple[str, bool]:
        absolute_url = urljoin(index_url, href)
        parsed = urlsplit(absolute_url)
        if parsed.scheme != "https":
            raise CatalogDiscoveryError("知识目录链接必须使用 HTTPS。")
        if parsed.hostname is None:
            raise CatalogDiscoveryError("知识目录链接缺少 host。")
        if parsed.username is not None or parsed.password is not None or parsed.port is not None:
            raise CatalogDiscoveryError("知识目录链接不能包含凭据或自定义端口。")

        is_official = parsed.hostname == "docs.databricks.com"
        if not is_official:
            return absolute_url, False

        normalized_url = urlunsplit(
            (
                "https",
                "docs.databricks.com",
                parsed.path,
                parsed.query,
                "",
            )
        )
        try:
            return validate_official_url(normalized_url), True
        except UnsafeOfficialUrlError as error:
            raise CatalogDiscoveryError(str(error)) from None

    @staticmethod
    def _source_key(catalog_id: str, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return f"{catalog_id}-{digest}"

    @staticmethod
    def _general_category(topic: str) -> KnowledgeCategory:
        return _GENERAL_TOPIC_CATEGORIES.get(topic.casefold(), KnowledgeCategory.GENERAL)
