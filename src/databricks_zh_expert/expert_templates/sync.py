from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.expert_templates.constants import (
    EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS,
    EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateSource,
    ExpertTemplateSyncResult,
    PreparedTemplateSnapshot,
    PreparedTemplateVersion,
    SyncRunCompletion,
    TemplateVersionState,
)
from databricks_zh_expert.rag.constants import EMBEDDING_DIMENSIONS
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.search.markdown import (
    MarkdownChunk,
    MarkdownChunker,
    MarkdownSource,
)


class ExpertTemplateSyncError(RuntimeError):
    pass


class ExpertTemplateSyncRepository(Protocol):
    async def start_run(self, source_hash: str) -> UUID: ...

    async def finish_run(
        self,
        run_id: UUID,
        completion: SyncRunCompletion,
    ) -> None: ...

    async def get_active_states(self) -> Mapping[str, TemplateVersionState]: ...

    async def publish_snapshot(self, snapshot: PreparedTemplateSnapshot) -> None: ...


class ExpertTemplateEmbeddingClient(Protocol):
    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[EmbeddingResult, ...]: ...


class ExpertTemplateSyncService:
    def __init__(
        self,
        *,
        repository: ExpertTemplateSyncRepository,
        embedding_client: ExpertTemplateEmbeddingClient,
        chunker: MarkdownChunker | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._chunker = chunker or MarkdownChunker(
            chunk_size_tokens=EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS,
            chunk_overlap_tokens=EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS,
        )

    async def sync(
        self,
        registry: ExpertTemplateRegistry,
        *,
        dry_run: bool = False,
    ) -> ExpertTemplateSyncResult:
        active_states = await self._repository.get_active_states()
        active_template_ids = frozenset(source.template_id for source in registry.templates)
        new_sources: list[ExpertTemplateSource] = []
        skipped_count = 0
        run_id = None if dry_run else await self._repository.start_run(registry.source_hash)

        try:
            for source in registry.templates:
                state = active_states.get(source.template_id)
                if state is None:
                    new_sources.append(source)
                    continue
                if state.version == source.version:
                    if state.content_hash != source.content_hash:
                        raise ExpertTemplateSyncError(
                            f"模板 {source.template_id} 内容变化但版本未升级。"
                        )
                    skipped_count += 1
                    continue
                if _semantic_version(source.version) <= _semantic_version(state.version):
                    raise ExpertTemplateSyncError(
                        f"模板 {source.template_id} 的版本不能低于数据库中的当前版本。"
                    )
                new_sources.append(source)

            inactivated_count = sum(
                state.template_id not in active_template_ids
                or registry.get_template(state.template_id).version != state.version
                for state in active_states.values()
            )
            chunk_sets = tuple(self._chunk_source(source) for source in new_sources)
            chunk_count = sum(len(chunks) for chunks in chunk_sets)

            if dry_run:
                return _result(
                    run_id=None,
                    source_hash=registry.source_hash,
                    dry_run=True,
                    status="dry_run",
                    discovered_count=len(registry.templates),
                    inserted_count=len(new_sources),
                    activated_count=len(new_sources),
                    inactivated_count=inactivated_count,
                    skipped_count=skipped_count,
                    failed_count=0,
                    chunk_count=chunk_count,
                )

            prepared = await self._prepare_versions(new_sources, chunk_sets)
            has_active_changes = bool(new_sources) or set(active_states) != set(active_template_ids)
            if has_active_changes:
                await self._repository.publish_snapshot(
                    PreparedTemplateSnapshot(
                        source_hash=registry.source_hash,
                        templates=prepared,
                        active_template_ids=active_template_ids,
                        synced_at=datetime.now(UTC),
                    )
                )

            completion = SyncRunCompletion(
                status="succeeded",
                discovered_count=len(registry.templates),
                inserted_count=len(new_sources),
                activated_count=len(new_sources),
                inactivated_count=inactivated_count,
                skipped_count=skipped_count,
                failed_count=0,
                chunk_count=chunk_count,
                error_summary=(),
            )
            if run_id is None:
                raise AssertionError("正式同步缺少运行 ID。")
            await self._repository.finish_run(run_id, completion)
            return _result(
                run_id=run_id,
                source_hash=registry.source_hash,
                dry_run=False,
                status="succeeded",
                discovered_count=completion.discovered_count,
                inserted_count=completion.inserted_count,
                activated_count=completion.activated_count,
                inactivated_count=completion.inactivated_count,
                skipped_count=completion.skipped_count,
                failed_count=completion.failed_count,
                chunk_count=completion.chunk_count,
            )
        except ExpertTemplateSyncError as error:
            await self._record_failure(
                run_id,
                registry=registry,
                inserted_count=len(new_sources),
                skipped_count=skipped_count,
                error=error,
            )
            raise
        except Exception:
            error = ExpertTemplateSyncError("专家模板同步失败。")
            await self._record_failure(
                run_id,
                registry=registry,
                inserted_count=len(new_sources),
                skipped_count=skipped_count,
                error=error,
            )
            raise error from None

    def _chunk_source(self, source: ExpertTemplateSource) -> tuple[MarkdownChunk, ...]:
        chunks = self._chunker.split(
            MarkdownSource(
                title=source.name,
                source_ref=f"expert-template://{source.template_id}@{source.version}",
                content=source.content,
            )
        )
        if not chunks:
            raise ExpertTemplateSyncError(f"模板 {source.template_id} 没有可索引正文。")
        return chunks

    async def _prepare_versions(
        self,
        sources: Sequence[ExpertTemplateSource],
        chunk_sets: Sequence[tuple[MarkdownChunk, ...]],
    ) -> tuple[PreparedTemplateVersion, ...]:
        if not sources:
            return ()
        all_chunks = tuple(chunk for chunks in chunk_sets for chunk in chunks)
        results = await self._embedding_client.embed_documents(
            tuple(chunk.content for chunk in all_chunks)
        )
        _validate_embedding_batch(results, len(all_chunks))

        prepared: list[PreparedTemplateVersion] = []
        offset = 0
        for source, chunks in zip(sources, chunk_sets, strict=True):
            local_embeddings = tuple(
                EmbeddingResult(index=index, embedding=results[offset + index].embedding)
                for index in range(len(chunks))
            )
            offset += len(chunks)
            prepared.append(
                PreparedTemplateVersion(
                    source=source,
                    chunks=chunks,
                    embeddings=local_embeddings,
                )
            )
        return tuple(prepared)

    async def _record_failure(
        self,
        run_id: UUID | None,
        *,
        registry: ExpertTemplateRegistry,
        inserted_count: int,
        skipped_count: int,
        error: ExpertTemplateSyncError,
    ) -> None:
        if run_id is None:
            return
        await self._repository.finish_run(
            run_id,
            SyncRunCompletion(
                status="failed",
                discovered_count=len(registry.templates),
                inserted_count=inserted_count,
                activated_count=0,
                inactivated_count=0,
                skipped_count=skipped_count,
                failed_count=1,
                chunk_count=0,
                error_summary=(
                    {
                        "code": "expert_template_sync_failed",
                        "message": str(error),
                    },
                ),
            ),
        )


def _semantic_version(value: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = value.split(".", maxsplit=2)
        return int(major), int(minor), int(patch)
    except (TypeError, ValueError):
        raise ExpertTemplateSyncError("专家模板版本必须使用 MAJOR.MINOR.PATCH。") from None


def _validate_embedding_batch(
    results: Sequence[EmbeddingResult],
    expected_count: int,
) -> None:
    if len(results) != expected_count:
        raise ExpertTemplateSyncError("Chunk 与 Embedding 数量不一致。")
    for index, result in enumerate(results):
        if result.index != index:
            raise ExpertTemplateSyncError("Embedding index 与 Chunk 顺序不一致。")
        if len(result.embedding) != EMBEDDING_DIMENSIONS:
            raise ExpertTemplateSyncError("Embedding 维度不匹配。")
        if any(not isfinite(float(value)) for value in result.embedding):
            raise ExpertTemplateSyncError("Embedding 包含无效数值。")


def _result(
    *,
    run_id: UUID | None,
    source_hash: str,
    dry_run: bool,
    status: str,
    discovered_count: int,
    inserted_count: int,
    activated_count: int,
    inactivated_count: int,
    skipped_count: int,
    failed_count: int,
    chunk_count: int,
) -> ExpertTemplateSyncResult:
    if status not in {"succeeded", "failed", "dry_run"}:
        raise ValueError("专家模板同步结果状态无效。")
    normalized_status = (
        "succeeded" if status == "succeeded" else "failed" if status == "failed" else "dry_run"
    )
    return ExpertTemplateSyncResult(
        run_id=run_id,
        source_hash=source_hash,
        dry_run=dry_run,
        status=normalized_status,
        discovered_count=discovered_count,
        inserted_count=inserted_count,
        activated_count=activated_count,
        inactivated_count=inactivated_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        error_summary=(),
    )
