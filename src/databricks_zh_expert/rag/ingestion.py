import asyncio
import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.rag.catalogs import KnowledgeCatalogParser
from databricks_zh_expert.rag.chunker import KnowledgeChunk, MarkdownChunker
from databricks_zh_expert.rag.embeddings import EmbeddingClient, EmbeddingResult
from databricks_zh_expert.rag.manifest import load_manifest
from databricks_zh_expert.rag.normalizer import KnowledgeNormalizer
from databricks_zh_expert.rag.repository import (
    CatalogPresenceResult,
    DocumentState,
    IngestionRunCompletion,
)
from databricks_zh_expert.rag.types import (
    CatalogDiscoveryResult,
    CatalogFetchResult,
    CatalogKind,
    DiscoveredSource,
    FetchCondition,
    FetchResult,
    FetchStatus,
    KnowledgeManifest,
    NormalizedDocument,
    SourceCatalog,
    SourceKind,
)

logger = logging.getLogger(__name__)
_SAFE_CODE_PATTERN = re.compile(r"^[a-z0-9_]{3,100}$")


class IngestionRepository(Protocol):
    async def start_run(self, manifest_hash: str) -> UUID: ...

    async def finish_run(
        self,
        run_id: UUID,
        completion: IngestionRunCompletion,
    ) -> None: ...

    async def get_document_state(self, source_key: str) -> DocumentState | None: ...

    async def reconcile_source_identities(
        self,
        sources: Sequence[DiscoveredSource],
    ) -> int: ...

    async def reconcile_catalog_presence(
        self,
        catalog_id: str,
        observed_source_keys: set[str],
        *,
        observed_at: datetime,
    ) -> CatalogPresenceResult: ...

    async def publish_document(
        self,
        document: NormalizedDocument,
        *,
        content_hash: str,
        chunks: tuple[KnowledgeChunk, ...],
        embeddings: tuple[EmbeddingResult, ...],
        fetched_at: datetime,
    ) -> UUID: ...

    async def mark_document_checked(
        self,
        source_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        fetched_at: datetime,
    ) -> None: ...


class IngestionFetcher(Protocol):
    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult: ...

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class CatalogSyncStats:
    catalog_id: str
    source_kind: str
    discovered_count: int
    duplicate_count: int
    external_link_count: int
    pending_missing_count: int
    disabled_count: int


@dataclass(frozen=True, slots=True)
class KnowledgeSyncResult:
    status: str
    run_id: UUID | None
    manifest_hash: str
    discovered_count: int
    changed_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    pending_missing_count: int
    disabled_count: int
    catalogs: tuple[CatalogSyncStats, ...]
    error_summary: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class _CatalogOutcome:
    catalog: SourceCatalog
    discovery: CatalogDiscoveryResult | None


class KnowledgeIngestionService:
    def __init__(
        self,
        *,
        repository: IngestionRepository,
        fetcher: IngestionFetcher,
        embedding_client: EmbeddingClient,
        catalog_parser: KnowledgeCatalogParser | None = None,
        normalizer: KnowledgeNormalizer | None = None,
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher
        self._embedding_client = embedding_client
        self._catalog_parser = catalog_parser or KnowledgeCatalogParser()
        self._normalizer = normalizer or KnowledgeNormalizer()

    async def sync(
        self,
        manifest_path: Path,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> KnowledgeSyncResult:
        manifest_bytes, manifest = await asyncio.to_thread(
            _load_manifest_asset,
            manifest_path,
        )
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        run_id = None if dry_run else await self._repository.start_run(manifest_hash)
        failures: list[dict[str, str]] = []
        catalog_outcomes = await self._discover_catalogs(manifest, failures)
        discovered = _flatten_sources(catalog_outcomes)

        if dry_run:
            skipped_count = await self._validate_fetches(discovered, failures)
            return KnowledgeSyncResult(
                status="dry_run",
                run_id=None,
                manifest_hash=manifest_hash,
                discovered_count=len(discovered),
                changed_count=0,
                skipped_count=skipped_count,
                failed_count=len(failures),
                chunk_count=0,
                pending_missing_count=0,
                disabled_count=0,
                catalogs=_catalog_stats(catalog_outcomes, {}),
                error_summary=tuple(failures),
            )

        chunker = MarkdownChunker(
            chunk_size_tokens=manifest.chunk_size_tokens,
            chunk_overlap_tokens=manifest.chunk_overlap_tokens,
        )
        changed_count = 0
        skipped_count = 0
        chunk_count = 0
        ready_sources: list[DiscoveredSource] = []
        presence_by_catalog: dict[str, CatalogPresenceResult] = {}
        observed_at = datetime.now(UTC)

        for outcome in catalog_outcomes:
            if outcome.discovery is None:
                continue
            catalog_sources = outcome.discovery.all_sources
            try:
                await self._repository.reconcile_source_identities(catalog_sources)
                presence = await self._repository.reconcile_catalog_presence(
                    outcome.catalog.id,
                    {source.source_key for source in catalog_sources},
                    observed_at=observed_at,
                )
            except Exception as error:
                failures.append(_safe_failure(outcome.catalog.id, error))
                logger.warning(
                    "知识目录状态协调失败：catalog_id=%s error_type=%s",
                    outcome.catalog.id,
                    type(error).__name__,
                )
                continue
            presence_by_catalog[outcome.catalog.id] = presence
            ready_sources.extend(catalog_sources)

        for source in ready_sources:
            try:
                outcome = await self._sync_source(source, chunker, force=force)
            except Exception as error:
                failures.append(_safe_failure(source.source_key, error))
                logger.warning(
                    "知识来源同步失败：source_key=%s error_type=%s",
                    source.source_key,
                    type(error).__name__,
                )
                continue
            if outcome is None:
                skipped_count += 1
            else:
                changed_count += 1
                chunk_count += outcome

        pending_missing_count = sum(
            presence.pending_missing_count for presence in presence_by_catalog.values()
        )
        disabled_count = sum(presence.disabled_count for presence in presence_by_catalog.values())

        status = _run_status(
            failed_count=len(failures),
            successful_count=changed_count + skipped_count,
        )
        completion = IngestionRunCompletion(
            status=status,
            discovered_count=len(discovered),
            changed_count=changed_count,
            skipped_count=skipped_count,
            failed_count=len(failures),
            chunk_count=chunk_count,
            error_summary=tuple(failures),
        )
        assert run_id is not None
        await self._repository.finish_run(run_id, completion)
        return KnowledgeSyncResult(
            status=status,
            run_id=run_id,
            manifest_hash=manifest_hash,
            discovered_count=len(discovered),
            changed_count=changed_count,
            skipped_count=skipped_count,
            failed_count=len(failures),
            chunk_count=chunk_count,
            pending_missing_count=pending_missing_count,
            disabled_count=disabled_count,
            catalogs=_catalog_stats(catalog_outcomes, presence_by_catalog),
            error_summary=tuple(failures),
        )

    async def _discover_catalogs(
        self,
        manifest: KnowledgeManifest,
        failures: list[dict[str, str]],
    ) -> tuple[_CatalogOutcome, ...]:
        outcomes: list[_CatalogOutcome] = []
        for catalog in manifest.catalogs:
            try:
                fetched = await self._fetcher.fetch_catalog(catalog)
                discovery = self._catalog_parser.discover(fetched.content, catalog)
            except Exception as error:
                failures.append(_safe_failure(catalog.id, error))
                logger.warning(
                    "知识目录同步失败：catalog_id=%s error_type=%s",
                    catalog.id,
                    type(error).__name__,
                )
                outcomes.append(_CatalogOutcome(catalog=catalog, discovery=None))
            else:
                outcomes.append(_CatalogOutcome(catalog=catalog, discovery=discovery))
        return tuple(outcomes)

    async def _validate_fetches(
        self,
        sources: Sequence[DiscoveredSource],
        failures: list[dict[str, str]],
    ) -> int:
        succeeded = 0
        for source in sources:
            if source.kind is SourceKind.CATALOG_LINK:
                succeeded += 1
                continue
            try:
                await self._fetcher.fetch(source, None)
            except Exception as error:
                failures.append(_safe_failure(source.source_key, error))
                logger.warning(
                    "知识来源 dry-run 失败：source_key=%s error_type=%s",
                    source.source_key,
                    type(error).__name__,
                )
            else:
                succeeded += 1
        return succeeded

    async def _sync_source(
        self,
        source: DiscoveredSource,
        chunker: MarkdownChunker,
        *,
        force: bool,
    ) -> int | None:
        state = await self._repository.get_document_state(source.source_key)
        fetched_at = datetime.now(UTC)
        if source.kind is SourceKind.CATALOG_LINK:
            document = self._normalizer.normalize_catalog_link(source)
            return await self._publish_if_changed(
                document,
                state,
                chunker,
                fetched_at=fetched_at,
                force=force,
            )

        condition = None
        if state is not None and state.status == "active" and not force:
            condition = FetchCondition(
                etag=state.etag,
                last_modified=state.last_modified,
            )
        fetched = await self._fetcher.fetch(source, condition)
        if fetched.status is FetchStatus.NOT_MODIFIED:
            if state is None:
                raise ValueError("未保存的知识来源不能返回 304。")
            if state.status != "active":
                raise ValueError("已禁用的知识来源必须重新抓取正文后才能恢复。")
            await self._repository.mark_document_checked(
                source.source_key,
                etag=fetched.etag,
                last_modified=fetched.last_modified,
                fetched_at=fetched_at,
            )
            return None

        document = self._normalizer.normalize(fetched)
        return await self._publish_if_changed(
            document,
            state,
            chunker,
            fetched_at=fetched_at,
            force=force,
        )

    async def _publish_if_changed(
        self,
        document: NormalizedDocument,
        state: DocumentState | None,
        chunker: MarkdownChunker,
        *,
        fetched_at: datetime,
        force: bool,
    ) -> int | None:
        content_hash = hashlib.sha256(document.normalized_content.encode("utf-8")).hexdigest()
        if state is not None and state.content_hash == content_hash and not force:
            await self._repository.mark_document_checked(
                document.source.source_key,
                etag=document.etag,
                last_modified=document.last_modified,
                fetched_at=fetched_at,
            )
            return None

        chunks = chunker.split(document)
        if not chunks:
            raise ValueError("规范化知识文档没有生成 Chunk。")
        embeddings = await self._embedding_client.embed_documents(
            tuple(chunk.content for chunk in chunks)
        )
        await self._repository.publish_document(
            document,
            content_hash=content_hash,
            chunks=chunks,
            embeddings=embeddings,
            fetched_at=fetched_at,
        )
        return len(chunks)


def _flatten_sources(outcomes: Sequence[_CatalogOutcome]) -> tuple[DiscoveredSource, ...]:
    return tuple(
        source
        for outcome in outcomes
        if outcome.discovery is not None
        for source in outcome.discovery.all_sources
    )


def _catalog_stats(
    outcomes: Sequence[_CatalogOutcome],
    presence_by_catalog: dict[str, CatalogPresenceResult],
) -> tuple[CatalogSyncStats, ...]:
    stats = []
    for outcome in outcomes:
        discovery = outcome.discovery
        presence = presence_by_catalog.get(outcome.catalog.id)
        stats.append(
            CatalogSyncStats(
                catalog_id=outcome.catalog.id,
                source_kind=_source_kind(outcome.catalog.kind).value,
                discovered_count=len(discovery.all_sources) if discovery is not None else 0,
                duplicate_count=discovery.duplicate_count if discovery is not None else 0,
                external_link_count=(len(discovery.external_links) if discovery is not None else 0),
                pending_missing_count=(
                    presence.pending_missing_count if presence is not None else 0
                ),
                disabled_count=presence.disabled_count if presence is not None else 0,
            )
        )
    return tuple(stats)


def _source_kind(catalog_kind: CatalogKind) -> SourceKind:
    if catalog_kind is CatalogKind.DATABRICKS_DOCS:
        return SourceKind.GENERAL_HTML
    return SourceKind.API_MARKDOWN


def _load_manifest_asset(path: Path) -> tuple[bytes, KnowledgeManifest]:
    return path.read_bytes(), load_manifest(path)


def _safe_failure(source_key: str, error: Exception) -> dict[str, str]:
    raw_code = getattr(error, "code", None)
    code = (
        raw_code
        if isinstance(raw_code, str) and _SAFE_CODE_PATTERN.fullmatch(raw_code)
        else "knowledge_source_failed"
    )
    return {
        "source_key": source_key,
        "code": code,
        "error_type": type(error).__name__,
    }


def _run_status(*, failed_count: int, successful_count: int) -> str:
    if failed_count == 0:
        return "succeeded"
    if successful_count > 0:
        return "partial"
    return "failed"
