import asyncio
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from databricks_zh_expert.rag.constants import (
    KNOWLEDGE_CATALOG_MAX_BYTES,
    KNOWLEDGE_DOCUMENT_MAX_BYTES,
    KNOWLEDGE_FETCH_MAX_REDIRECTS,
    KNOWLEDGE_FETCH_MAX_RETRIES,
    KNOWLEDGE_FETCH_USER_AGENT,
)
from databricks_zh_expert.rag.types import (
    CatalogFetchResult,
    DiscoveredSource,
    FetchCondition,
    FetchResult,
    FetchStatus,
    SourceCatalog,
    SourceKind,
)
from databricks_zh_expert.rag.urls import UnsafeOfficialUrlError, validate_official_url

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class KnowledgeFetchError(RuntimeError):
    pass


class KnowledgeFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult:
        headers = self._base_headers()
        if condition is not None:
            if condition.etag:
                headers["If-None-Match"] = condition.etag
            if condition.last_modified:
                headers["If-Modified-Since"] = condition.last_modified

        response, final_url = await self._request(source.url, headers, source.source_key)
        try:
            if response.status_code == 304:
                return FetchResult(
                    source=source,
                    status=FetchStatus.NOT_MODIFIED,
                    final_url=final_url,
                    content_type=None,
                    body=None,
                    etag=response.headers.get("ETag") or (condition.etag if condition else None),
                    last_modified=response.headers.get("Last-Modified")
                    or (condition.last_modified if condition else None),
                )

            self._require_success(response, source.source_key)
            allowed_types = (
                {"text/html"}
                if source.kind is SourceKind.GENERAL_HTML
                else {"text/markdown", "text/plain"}
            )
            content_type, body = await self._read_text(
                response,
                allowed_types=allowed_types,
                max_bytes=KNOWLEDGE_DOCUMENT_MAX_BYTES,
                limit_label="2 MiB",
            )
            return FetchResult(
                source=source,
                status=FetchStatus.FETCHED,
                final_url=final_url,
                content_type=content_type,
                body=body,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
        finally:
            await response.aclose()

    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult:
        response, final_url = await self._request(
            catalog.index_url,
            self._base_headers(),
            catalog.id,
        )
        try:
            self._require_success(response, catalog.id)
            content_type, content = await self._read_text(
                response,
                allowed_types={"text/plain", "text/markdown"},
                max_bytes=KNOWLEDGE_CATALOG_MAX_BYTES,
                limit_label="5 MiB",
            )
            return CatalogFetchResult(
                catalog_id=catalog.id,
                index_url=catalog.index_url,
                final_url=final_url,
                content_type=content_type,
                content=content,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
        finally:
            await response.aclose()

    @staticmethod
    def _base_headers() -> dict[str, str]:
        return {
            "Accept": "text/html,text/markdown,text/plain;q=0.9",
            "User-Agent": KNOWLEDGE_FETCH_USER_AGENT,
        }

    async def _request(
        self,
        initial_url: str,
        headers: dict[str, str],
        source_key: str,
    ) -> tuple[httpx.Response, str]:
        try:
            current_url = validate_official_url(initial_url)
        except UnsafeOfficialUrlError as error:
            raise KnowledgeFetchError(str(error)) from None

        redirects = 0
        retry_number = 0
        while True:
            request = self._client.build_request("GET", current_url, headers=headers)
            try:
                response = await self._client.send(
                    request,
                    stream=True,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if retry_number >= KNOWLEDGE_FETCH_MAX_RETRIES:
                    raise KnowledgeFetchError(
                        f"抓取知识来源失败：{source_key}，网络请求重试已用尽。"
                    ) from None
                logger.warning(
                    "知识来源网络请求失败，将重试：source_key=%s attempt=%d",
                    source_key,
                    retry_number + 1,
                )
                await self._sleep(2.0**retry_number)
                retry_number += 1
                continue

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                await response.aclose()
                if not location:
                    raise KnowledgeFetchError(f"知识来源重定向缺少 Location：{source_key}。")
                redirects += 1
                if redirects > KNOWLEDGE_FETCH_MAX_REDIRECTS:
                    raise KnowledgeFetchError(f"知识来源重定向次数过多：{source_key}。")
                try:
                    current_url = validate_official_url(urljoin(current_url, location))
                except UnsafeOfficialUrlError as error:
                    raise KnowledgeFetchError(str(error)) from None
                retry_number = 0
                continue

            if response.status_code in _RETRYABLE_STATUSES:
                if retry_number >= KNOWLEDGE_FETCH_MAX_RETRIES:
                    return response, current_url
                delay = self._retry_delay(response, retry_number)
                logger.warning(
                    "知识来源暂时不可用，将重试：source_key=%s status=%d attempt=%d",
                    source_key,
                    response.status_code,
                    retry_number + 1,
                )
                await response.aclose()
                await self._sleep(delay)
                retry_number += 1
                continue

            return response, current_url

    @staticmethod
    def _retry_delay(response: httpx.Response, retry_number: int) -> float:
        value = response.headers.get("Retry-After")
        if value is not None:
            try:
                return max(0.0, float(value))
            except ValueError:
                pass
        return 2.0**retry_number

    @staticmethod
    def _require_success(response: httpx.Response, source_key: str) -> None:
        if 200 <= response.status_code < 300:
            return
        raise KnowledgeFetchError(f"抓取知识来源失败：{source_key}，HTTP {response.status_code}。")

    @staticmethod
    async def _read_text(
        response: httpx.Response,
        *,
        allowed_types: set[str],
        max_bytes: int,
        limit_label: str,
    ) -> tuple[str, str]:
        content_type = response.headers.get("Content-Type")
        media_type = content_type.split(";", maxsplit=1)[0].strip().lower() if content_type else ""
        if media_type not in allowed_types:
            raise KnowledgeFetchError(
                f"知识来源返回了不支持的 Content-Type：{content_type or 'missing'}。"
            )

        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    raise KnowledgeFetchError(f"知识来源正文超过 {limit_label} 限制。")
            except ValueError:
                pass

        payload = bytearray()
        async for chunk in response.aiter_bytes():
            if len(payload) + len(chunk) > max_bytes:
                raise KnowledgeFetchError(f"知识来源正文超过 {limit_label} 限制。")
            payload.extend(chunk)

        encoding = response.encoding or "utf-8"
        try:
            return content_type or media_type, payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            raise KnowledgeFetchError("知识来源正文无法按声明字符集解码。") from None
