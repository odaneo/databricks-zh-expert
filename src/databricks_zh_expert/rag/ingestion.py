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
    DocumentState,
    IngestionRunCompletion,
)
from databricks_zh_expert.rag.types import (
    CatalogFetchResult,
    DiscoveredSource,
    FetchCondition,
    FetchResult,
    FetchStatus,
    KnowledgeManifest,
    NormalizedDocument,
    SourceCatalog,
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

    async def disable_missing_sources(self, active_source_keys: set[str]) -> int: ...


class IngestionFetcher(Protocol):
    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult: ...

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult: ...


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
    disabled_count: int
    error_summary: tuple[dict[str, str], ...]


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
        discovered = await self._discover_sources(manifest, failures)
        expected_source_keys = _manifest_source_keys(manifest)

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
                disabled_count=0,
                error_summary=tuple(failures),
            )

        chunker = MarkdownChunker(
            chunk_size_tokens=manifest.chunk_size_tokens,
            chunk_overlap_tokens=manifest.chunk_overlap_tokens,
        )
        changed_count = 0
        skipped_count = 0
        chunk_count = 0

        for source in discovered:
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

        disabled_count = 0
        try:
            disabled_count = await self._repository.disable_missing_sources(expected_source_keys)
        except Exception as error:
            failures.append(_safe_failure("manifest", error))
            logger.warning(
                "知识来源禁用同步失败：error_type=%s",
                type(error).__name__,
            )

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
            disabled_count=disabled_count,
            error_summary=tuple(failures),
        )

    async def _discover_sources(
        self,
        manifest: KnowledgeManifest,
        failures: list[dict[str, str]],
    ) -> tuple[DiscoveredSource, ...]:
        discovered: list[DiscoveredSource] = []
        for catalog in manifest.catalogs:
            try:
                fetched = await self._fetcher.fetch_catalog(catalog)
                discovered.extend(self._catalog_parser.discover(fetched.content, catalog))
            except Exception as error:
                failures.append(_safe_failure(catalog.id, error))
                logger.warning(
                    "知识目录同步失败：catalog_id=%s error_type=%s",
                    catalog.id,
                    type(error).__name__,
                )
        return tuple(discovered)

    async def _validate_fetches(
        self,
        sources: Sequence[DiscoveredSource],
        failures: list[dict[str, str]],
    ) -> int:
        succeeded = 0
        for source in sources:
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
        condition = None
        if state is not None and not force:
            condition = FetchCondition(
                etag=state.etag,
                last_modified=state.last_modified,
            )
        fetched = await self._fetcher.fetch(source, condition)
        fetched_at = datetime.now(UTC)
        if fetched.status is FetchStatus.NOT_MODIFIED:
            if state is None:
                raise ValueError("未保存的知识来源不能返回 304。")
            await self._repository.mark_document_checked(
                source.source_key,
                etag=fetched.etag,
                last_modified=fetched.last_modified,
                fetched_at=fetched_at,
            )
            return None

        document = self._normalizer.normalize(fetched)
        content_hash = hashlib.sha256(document.normalized_content.encode("utf-8")).hexdigest()
        if state is not None and state.content_hash == content_hash and not force:
            await self._repository.mark_document_checked(
                source.source_key,
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


def _manifest_source_keys(manifest: KnowledgeManifest) -> set[str]:
    source_keys = {
        document.source_key for catalog in manifest.catalogs for document in catalog.documents
    }
    source_keys.update(
        operation.source_key
        for catalog in manifest.catalogs
        for module in catalog.modules
        for operation in module.operations
    )
    return source_keys


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
