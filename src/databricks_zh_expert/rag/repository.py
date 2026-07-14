from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from databricks_zh_expert.db.models import (
    KnowledgeChunkRecord,
    KnowledgeDocument,
    KnowledgeIngestionRun,
)
from databricks_zh_expert.rag.chunker import KnowledgeChunk
from databricks_zh_expert.rag.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.types import NormalizedDocument


@dataclass(frozen=True, slots=True)
class DocumentState:
    id: UUID
    source_key: str
    content_hash: str
    etag: str | None
    last_modified: str | None
    status: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class IngestionRunCompletion:
    status: str
    discovered_count: int
    changed_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    error_summary: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class KnowledgeIndexStatus:
    last_run_status: str | None
    active_document_count: int
    chunk_count: int
    embedding_model: str | None
    embedding_dimensions: int | None
    queryable: bool


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    chunk_id: UUID
    chunk_hash: str
    document_id: UUID
    source_key: str
    title: str
    canonical_url: str
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    token_count: int
    source_ref: str
    vector_similarity: float | None
    lexical_score: float | None


class KnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start_run(self, manifest_hash: str) -> UUID:
        run_id = uuid4()
        async with self._session_factory.begin() as session:
            session.add(
                KnowledgeIngestionRun(
                    id=run_id,
                    status="running",
                    manifest_hash=manifest_hash,
                    embedding_model=EMBEDDING_MODEL,
                    embedding_dimensions=EMBEDDING_DIMENSIONS,
                    discovered_count=0,
                    changed_count=0,
                    skipped_count=0,
                    failed_count=0,
                    chunk_count=0,
                    error_summary=[],
                )
            )
        return run_id

    async def finish_run(
        self,
        run_id: UUID,
        completion: IngestionRunCompletion,
    ) -> None:
        async with self._session_factory.begin() as session:
            updated_id = await session.scalar(
                update(KnowledgeIngestionRun)
                .where(KnowledgeIngestionRun.id == run_id)
                .values(
                    status=completion.status,
                    discovered_count=completion.discovered_count,
                    changed_count=completion.changed_count,
                    skipped_count=completion.skipped_count,
                    failed_count=completion.failed_count,
                    chunk_count=completion.chunk_count,
                    error_summary=list(completion.error_summary),
                    completed_at=datetime.now(UTC),
                )
                .returning(KnowledgeIngestionRun.id)
            )
            if updated_id is None:
                raise LookupError(f"知识同步运行不存在：{run_id}")

    async def get_run(self, run_id: UUID) -> KnowledgeIngestionRun | None:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(KnowledgeIngestionRun).where(KnowledgeIngestionRun.id == run_id)
            )
            return result.one_or_none()

    async def get_document(self, source_key: str) -> KnowledgeDocument | None:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.source_key == source_key)
            )
            return result.one_or_none()

    async def get_document_state(self, source_key: str) -> DocumentState | None:
        document = await self.get_document(source_key)
        if document is None:
            return None
        return DocumentState(
            id=document.id,
            source_key=document.source_key,
            content_hash=document.content_hash,
            etag=document.etag,
            last_modified=document.last_modified,
            status=document.status,
            chunk_count=document.chunk_count,
        )

    async def list_chunks(self, source_key: str) -> tuple[KnowledgeChunkRecord, ...]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(KnowledgeChunkRecord)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunkRecord.document_id,
                )
                .where(KnowledgeDocument.source_key == source_key)
                .order_by(KnowledgeChunkRecord.chunk_index.asc())
            )
            return tuple(result.all())

    async def publish_document(
        self,
        document: NormalizedDocument,
        *,
        content_hash: str,
        chunks: tuple[KnowledgeChunk, ...],
        embeddings: tuple[EmbeddingResult, ...],
        fetched_at: datetime,
    ) -> UUID:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk 与 Embedding 数量不一致。")
        if any(result.index != index for index, result in enumerate(embeddings)):
            raise ValueError("Embedding index 与 Chunk 顺序不一致。")

        async with self._session_factory() as session:
            async with session.begin():
                result = await session.scalars(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.source_key == document.source.source_key)
                    .with_for_update()
                )
                stored = result.one_or_none()
                if stored is None:
                    stored = KnowledgeDocument(
                        id=uuid4(),
                        source_key=document.source.source_key,
                        source_kind=document.source.kind.value,
                        title=document.title,
                        source_url=document.source.url,
                        canonical_url=document.canonical_url,
                        category=document.source.category.value,
                        cloud=document.source.cloud,
                        locale=document.source.locale,
                        normalized_content=document.normalized_content,
                        content_hash=content_hash,
                        etag=document.etag,
                        last_modified=document.last_modified,
                        status="active",
                        chunk_count=len(chunks),
                        source_updated_at=_parse_source_timestamp(document.source_updated_at),
                        fetched_at=fetched_at,
                    )
                    session.add(stored)
                    await session.flush()
                else:
                    stored.source_kind = document.source.kind.value
                    stored.title = document.title
                    stored.source_url = document.source.url
                    stored.canonical_url = document.canonical_url
                    stored.category = document.source.category.value
                    stored.cloud = document.source.cloud
                    stored.locale = document.source.locale
                    stored.normalized_content = document.normalized_content
                    stored.content_hash = content_hash
                    stored.etag = document.etag
                    stored.last_modified = document.last_modified
                    stored.status = "active"
                    stored.chunk_count = len(chunks)
                    stored.source_updated_at = _parse_source_timestamp(document.source_updated_at)
                    stored.fetched_at = fetched_at
                    stored.updated_at = datetime.now(UTC)
                    await session.execute(
                        delete(KnowledgeChunkRecord).where(
                            KnowledgeChunkRecord.document_id == stored.id
                        )
                    )

                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    session.add(
                        KnowledgeChunkRecord(
                            id=uuid4(),
                            document_id=stored.id,
                            chunk_index=chunk.chunk_index,
                            heading_path=list(chunk.heading_path),
                            content=chunk.content,
                            content_hash=chunk.content_hash,
                            token_count=chunk.token_count,
                            source_ref=chunk.source_ref,
                            chunk_metadata={
                                "catalog_id": document.source.catalog_id,
                                "topic": document.source.topic,
                            },
                            embedding=list(embedding.embedding),
                            embedding_model=EMBEDDING_MODEL,
                        )
                    )
                document_id = stored.id
            return document_id

    async def mark_document_checked(
        self,
        source_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        fetched_at: datetime,
    ) -> None:
        values: dict[str, object] = {
            "status": "active",
            "fetched_at": fetched_at,
            "updated_at": datetime.now(UTC),
        }
        if etag is not None:
            values["etag"] = etag
        if last_modified is not None:
            values["last_modified"] = last_modified
        async with self._session_factory.begin() as session:
            await session.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.source_key == source_key)
                .values(**values)
            )

    async def disable_missing_sources(self, active_source_keys: set[str]) -> int:
        predicate = KnowledgeDocument.status == "active"
        if active_source_keys:
            predicate = predicate & KnowledgeDocument.source_key.not_in(active_source_keys)
        async with self._session_factory.begin() as session:
            disabled_ids = await session.scalars(
                update(KnowledgeDocument)
                .where(predicate)
                .values(status="disabled", updated_at=datetime.now(UTC))
                .returning(KnowledgeDocument.id)
            )
            return len(disabled_ids.all())

    async def get_index_status(self) -> KnowledgeIndexStatus:
        async with self._session_factory() as session:
            last_run = await session.scalar(
                select(KnowledgeIngestionRun)
                .order_by(
                    KnowledgeIngestionRun.started_at.desc(),
                    KnowledgeIngestionRun.id.desc(),
                )
                .limit(1)
            )
            active_document_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.status == "active")
            )
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunkRecord)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunkRecord.document_id,
                )
                .where(KnowledgeDocument.status == "active")
            )
            models = tuple(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord.embedding_model)
                        .join(
                            KnowledgeDocument,
                            KnowledgeDocument.id == KnowledgeChunkRecord.document_id,
                        )
                        .where(KnowledgeDocument.status == "active")
                        .distinct()
                    )
                ).all()
            )

        active_count = int(active_document_count or 0)
        chunks = int(chunk_count or 0)
        embedding_model = models[0] if len(models) == 1 else None
        last_status = last_run.status if last_run is not None else None
        embedding_dimensions = (
            last_run.embedding_dimensions if last_run is not None and chunks > 0 else None
        )
        queryable = (
            active_count > 0
            and chunks > 0
            and embedding_model == EMBEDDING_MODEL
            and last_run is not None
            and last_run.embedding_model == EMBEDDING_MODEL
            and embedding_dimensions == EMBEDDING_DIMENSIONS
            and last_status in {"succeeded", "partial"}
        )
        return KnowledgeIndexStatus(
            last_run_status=last_status,
            active_document_count=active_count,
            chunk_count=chunks,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            queryable=queryable,
        )

    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]:
        vector = _validate_query_embedding(query_embedding)
        _validate_candidate_limit(limit)
        cosine_distance = KnowledgeChunkRecord.embedding.cosine_distance(vector).label(
            "cosine_distance"
        )
        statement = (
            select(KnowledgeChunkRecord, KnowledgeDocument, cosine_distance)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunkRecord.document_id,
            )
            .where(
                KnowledgeDocument.status == "active",
                KnowledgeChunkRecord.embedding_model == EMBEDDING_MODEL,
            )
            .order_by(
                cosine_distance.asc(),
                KnowledgeDocument.source_key.asc(),
                KnowledgeChunkRecord.chunk_index.asc(),
                KnowledgeChunkRecord.id.asc(),
            )
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        candidates: list[KnowledgeCandidate] = []
        for chunk, document, distance in rows:
            if distance is None:
                continue
            candidates.append(
                _knowledge_candidate(
                    chunk,
                    document,
                    vector_similarity=1.0 - float(distance),
                    lexical_score=None,
                )
            )
        return tuple(candidates)

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            return ()
        _validate_candidate_limit(limit)
        ts_query = func.websearch_to_tsquery("simple", normalized_query)
        lexical_score = func.ts_rank_cd(
            KnowledgeChunkRecord.search_vector,
            ts_query,
        ).label("lexical_score")
        statement = (
            select(KnowledgeChunkRecord, KnowledgeDocument, lexical_score)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunkRecord.document_id,
            )
            .where(
                KnowledgeDocument.status == "active",
                KnowledgeChunkRecord.search_vector.bool_op("@@")(ts_query),
            )
            .order_by(
                lexical_score.desc(),
                KnowledgeDocument.source_key.asc(),
                KnowledgeChunkRecord.chunk_index.asc(),
                KnowledgeChunkRecord.id.asc(),
            )
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        return tuple(
            _knowledge_candidate(
                chunk,
                document,
                vector_similarity=None,
                lexical_score=float(score),
            )
            for chunk, document, score in rows
        )


def _parse_source_timestamp(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validate_query_embedding(query_embedding: Sequence[float]) -> list[float]:
    vector = list(query_embedding)
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"查询 Embedding 必须是 {EMBEDDING_DIMENSIONS} 维。")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value))
        for value in vector
    ):
        raise ValueError("查询 Embedding 包含无效数值。")
    normalized = [float(value) for value in vector]
    if not any(value != 0.0 for value in normalized):
        raise ValueError("查询 Embedding 不能是零向量。")
    return normalized


def _validate_candidate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("候选数量上限必须是正整数。")


def _knowledge_candidate(
    chunk: KnowledgeChunkRecord,
    document: KnowledgeDocument,
    *,
    vector_similarity: float | None,
    lexical_score: float | None,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        chunk_id=chunk.id,
        chunk_hash=chunk.content_hash,
        document_id=document.id,
        source_key=document.source_key,
        title=document.title,
        canonical_url=document.canonical_url,
        chunk_index=chunk.chunk_index,
        heading_path=tuple(chunk.heading_path),
        content=chunk.content,
        token_count=chunk.token_count,
        source_ref=chunk.source_ref,
        vector_similarity=vector_similarity,
        lexical_score=lexical_score,
    )
