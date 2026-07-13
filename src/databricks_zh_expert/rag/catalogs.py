from dataclasses import dataclass
from urllib.parse import urljoin

from markdown_it import MarkdownIt
from markdown_it.token import Token

from databricks_zh_expert.rag.types import (
    CatalogKind,
    DiscoveredSource,
    SourceCatalog,
    SourceKind,
)
from databricks_zh_expert.rag.urls import validate_official_url


class CatalogDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _CatalogLink:
    topic: str
    title: str
    href: str
    summary: str | None


class KnowledgeCatalogParser:
    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark")

    def discover(
        self,
        index_content: str,
        catalog: SourceCatalog,
    ) -> tuple[DiscoveredSource, ...]:
        links = self._parse_links(index_content)
        if catalog.kind is CatalogKind.DATABRICKS_DOCS:
            return self._discover_general(links, catalog)
        return self._discover_api(links, catalog)

    def _parse_links(self, content: str) -> tuple[_CatalogLink, ...]:
        tokens = self._markdown.parse(content)
        current_topic = ""
        links: list[_CatalogLink] = []

        for index, token in enumerate(tokens):
            if token.type == "heading_open":
                if token.tag == "h2" and index + 1 < len(tokens):
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
    def _discover_general(
        links: tuple[_CatalogLink, ...],
        catalog: SourceCatalog,
    ) -> tuple[DiscoveredSource, ...]:
        selected_by_url = {document.url: document for document in catalog.documents}
        discovered: list[DiscoveredSource] = []
        found_keys: set[str] = set()

        for link in links:
            document = selected_by_url.get(link.href)
            if document is None or document.source_key in found_keys:
                continue
            validate_official_url(link.href)
            found_keys.add(document.source_key)
            discovered.append(
                DiscoveredSource(
                    source_key=document.source_key,
                    kind=SourceKind.GENERAL_HTML,
                    title=link.title,
                    url=link.href,
                    category=document.category,
                    catalog_id=catalog.id,
                    cloud=catalog.cloud,
                    locale=catalog.locale,
                    topic=link.topic,
                    summary=link.summary,
                )
            )

        KnowledgeCatalogParser._require_all_sources(catalog, found_keys)
        return tuple(discovered)

    @staticmethod
    def _discover_api(
        links: tuple[_CatalogLink, ...],
        catalog: SourceCatalog,
    ) -> tuple[DiscoveredSource, ...]:
        selected = {
            (module.name.casefold(), operation.title.casefold()): operation
            for module in catalog.modules
            for operation in module.operations
        }
        discovered: list[DiscoveredSource] = []
        found_keys: set[str] = set()

        for link in links:
            operation = selected.get((link.topic.casefold(), link.title.casefold()))
            if operation is None or operation.source_key in found_keys:
                continue
            url = validate_official_url(urljoin(catalog.index_url, link.href))
            found_keys.add(operation.source_key)
            discovered.append(
                DiscoveredSource(
                    source_key=operation.source_key,
                    kind=SourceKind.API_MARKDOWN,
                    title=link.title,
                    url=url,
                    category=operation.category,
                    catalog_id=catalog.id,
                    cloud=catalog.cloud,
                    locale=catalog.locale,
                    topic=link.topic,
                    summary=link.summary,
                )
            )

        KnowledgeCatalogParser._require_all_sources(catalog, found_keys)
        return tuple(discovered)

    @staticmethod
    def _require_all_sources(catalog: SourceCatalog, found_keys: set[str]) -> None:
        expected_keys = {document.source_key for document in catalog.documents}
        expected_keys.update(
            operation.source_key for module in catalog.modules for operation in module.operations
        )
        missing = sorted(expected_keys - found_keys)
        if missing:
            raise CatalogDiscoveryError("官方目录缺少清单指定的知识来源：" + ", ".join(missing))
