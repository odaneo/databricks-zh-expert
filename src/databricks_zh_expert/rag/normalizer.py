from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from markdown_it import MarkdownIt
from markdownify import markdownify

from databricks_zh_expert.rag.constants import KNOWLEDGE_MIN_NORMALIZED_CHARS
from databricks_zh_expert.rag.types import (
    FetchResult,
    FetchStatus,
    NormalizedDocument,
    SourceKind,
)
from databricks_zh_expert.rag.urls import UnsafeOfficialUrlError, validate_official_url


class KnowledgeNormalizationError(ValueError):
    pass


class KnowledgeNormalizer:
    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark")

    def normalize(self, fetched: FetchResult) -> NormalizedDocument:
        if fetched.status is not FetchStatus.FETCHED or fetched.body is None:
            raise KnowledgeNormalizationError("只有成功抓取的正文可以规范化。")

        if fetched.source.kind is SourceKind.GENERAL_HTML:
            title, canonical_url, source_updated_at, content = self._normalize_html(fetched)
        else:
            title, canonical_url, source_updated_at, content = self._normalize_markdown(fetched)

        normalized_content = self._clean_markdown(content)
        if len(normalized_content.strip()) < KNOWLEDGE_MIN_NORMALIZED_CHARS:
            raise KnowledgeNormalizationError("规范化后的知识正文过短。")

        return NormalizedDocument(
            source=fetched.source,
            title=title,
            canonical_url=canonical_url,
            normalized_content=normalized_content,
            source_updated_at=source_updated_at,
            etag=fetched.etag,
            last_modified=fetched.last_modified,
        )

    def _normalize_html(
        self,
        fetched: FetchResult,
    ) -> tuple[str, str, str | None, str]:
        body = fetched.body
        if body is None:
            raise KnowledgeNormalizationError("Databricks HTML 页面缺少正文。")
        soup = BeautifulSoup(body, "html.parser")
        article = soup.select_one("article.theme-doc-markdown") or soup.find("article")
        if not isinstance(article, Tag):
            raise KnowledgeNormalizationError("Databricks HTML 页面缺少 article 正文。")

        for element in article.select(
            "script, style, nav, footer, aside, form, button, "
            "[class*='feedback'], [aria-label*='feedback' i]"
        ):
            element.decompose()

        heading = article.find("h1")
        title = (
            heading.get_text(" ", strip=True) if isinstance(heading, Tag) else fetched.source.title
        )
        canonical_url = self._canonical_url(soup, fetched.final_url)
        source_updated_at = self._source_updated_at(soup) or fetched.last_modified
        content = markdownify(
            str(article),
            heading_style="ATX",
            bullets="-",
            code_language_callback=self._code_language,
        )
        return title, canonical_url, source_updated_at, content

    def _normalize_markdown(
        self,
        fetched: FetchResult,
    ) -> tuple[str, str, str | None, str]:
        content = fetched.body or ""
        title = fetched.source.title
        tokens = self._markdown.parse(content)
        for index, token in enumerate(tokens):
            if token.type == "heading_open" and token.tag == "h1" and index + 1 < len(tokens):
                title = tokens[index + 1].content.strip() or title
                break
        try:
            canonical_url = validate_official_url(fetched.final_url)
        except UnsafeOfficialUrlError as error:
            raise KnowledgeNormalizationError(str(error)) from None
        return title, canonical_url, fetched.last_modified, content

    @staticmethod
    def _canonical_url(soup: BeautifulSoup, final_url: str) -> str:
        canonical = soup.select_one("link[rel='canonical']")
        href = canonical.get("href") if isinstance(canonical, Tag) else None
        candidate = urljoin(final_url, href) if isinstance(href, str) else final_url
        try:
            return validate_official_url(candidate)
        except UnsafeOfficialUrlError as error:
            raise KnowledgeNormalizationError(str(error)) from None

    @staticmethod
    def _source_updated_at(soup: BeautifulSoup) -> str | None:
        modified = soup.select_one("meta[property='article:modified_time']")
        content = modified.get("content") if isinstance(modified, Tag) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
        timestamp = soup.select_one("time[datetime]")
        datetime_value = timestamp.get("datetime") if isinstance(timestamp, Tag) else None
        if isinstance(datetime_value, str) and datetime_value.strip():
            return datetime_value.strip()
        return None

    @staticmethod
    def _code_language(element: Tag) -> str | None:
        code = element.find("code")
        language_element = code if isinstance(code, Tag) else element
        class_value = language_element.get("class")
        if isinstance(class_value, str):
            class_names = [class_value]
        elif isinstance(class_value, list):
            class_names = class_value
        else:
            class_names = []
        for class_name in class_names:
            if class_name.startswith("language-"):
                return class_name.removeprefix("language-")
        return None

    @staticmethod
    def _clean_markdown(content: str) -> str:
        lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        cleaned: list[str] = []
        blank_count = 0
        for line in lines:
            line = line.rstrip()
            if line:
                blank_count = 0
                cleaned.append(line)
                continue
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        return "\n".join(cleaned).strip() + "\n"
