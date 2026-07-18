from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from databricks_zh_expert.db.models import (
    ExpertTemplateChunkRecord,
    ExpertTemplateRecord,
    ExpertTemplateSyncRun,
)
from databricks_zh_expert.expert_templates.context import ExpertTemplateDocument
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.types import (
    ExpertProfile,
    ExpertTemplateCategory,
    ExpertTemplateIndexStatus,
    ExpertTemplateKind,
    PreparedTemplateSnapshot,
    PreparedTemplateVersion,
    SyncRunCompletion,
    TemplateListQuery,
    TemplateVersionState,
)
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


@dataclass(frozen=True, slots=True)
class ExpertTemplateCandidate:
    chunk_id: UUID
    template_record_id: UUID
    template_id: str
    version: str
    name: str
    layer: str
    profile_id: str | None
    cloud: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    chunk_index: int
    content: str
    content_hash: str
    extends_record_id: UUID | None
    vector_similarity: float | None
    lexical_score: float | None


class ExpertTemplateRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        registry: ExpertTemplateRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._required_default_ids = frozenset(
            template_id
            for profile in registry.profiles
            for template_ids in profile.prompt_defaults.values()
            for template_id in template_ids
        )

    async def start_run(self, source_hash: str) -> UUID:
        run_id = uuid4()
        async with self._session_factory.begin() as session:
            session.add(
                ExpertTemplateSyncRun(
                    id=run_id,
                    status="running",
                    source_hash=source_hash,
                    embedding_model=EMBEDDING_MODEL,
                    embedding_dimensions=EMBEDDING_DIMENSIONS,
                    discovered_count=0,
                    inserted_count=0,
                    activated_count=0,
                    inactivated_count=0,
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
        completion: SyncRunCompletion,
    ) -> None:
        async with self._session_factory.begin() as session:
            updated_id = await session.scalar(
                update(ExpertTemplateSyncRun)
                .where(ExpertTemplateSyncRun.id == run_id)
                .values(
                    status=completion.status,
                    discovered_count=completion.discovered_count,
                    inserted_count=completion.inserted_count,
                    activated_count=completion.activated_count,
                    inactivated_count=completion.inactivated_count,
                    skipped_count=completion.skipped_count,
                    failed_count=completion.failed_count,
                    chunk_count=completion.chunk_count,
                    error_summary=list(completion.error_summary),
                    completed_at=datetime.now(UTC),
                )
                .returning(ExpertTemplateSyncRun.id)
            )
            if updated_id is None:
                raise LookupError(f"专家模板同步运行不存在：{run_id}")

    async def get_active_states(self) -> Mapping[str, TemplateVersionState]:
        async with self._session_factory() as session:
            records = tuple(
                (
                    await session.scalars(
                        select(ExpertTemplateRecord)
                        .where(ExpertTemplateRecord.status == "active")
                        .order_by(ExpertTemplateRecord.template_id.asc())
                    )
                ).all()
            )
        return {
            record.template_id: TemplateVersionState(
                record_id=record.id,
                template_id=record.template_id,
                version=record.version,
                content_hash=record.content_hash,
            )
            for record in records
        }

    async def publish_snapshot(self, snapshot: PreparedTemplateSnapshot) -> None:
        _validate_snapshot(snapshot)
        async with self._session_factory() as session:
            async with session.begin():
                active_records = tuple(
                    (
                        await session.scalars(
                            select(ExpertTemplateRecord)
                            .where(ExpertTemplateRecord.status == "active")
                            .with_for_update()
                        )
                    ).all()
                )
                active_by_template_id = {record.template_id: record for record in active_records}
                active_by_record_id = {record.id: record for record in active_records}

                existing_by_key = await _existing_versions(session, snapshot.templates)
                target_by_template_id: dict[str, ExpertTemplateRecord] = {}
                prepared_source_by_record_id = {}

                for prepared in snapshot.templates:
                    source = prepared.source
                    key = (source.template_id, source.version)
                    stored = existing_by_key.get(key)
                    if stored is not None:
                        if stored.content_hash != source.content_hash:
                            raise ValueError(f"模板 {source.template_id} 内容变化但版本未升级。")
                    else:
                        stored = _new_template_record(prepared)
                        session.add(stored)
                        await session.flush()
                        _add_chunks(session, stored.id, prepared)
                    target_by_template_id[source.template_id] = stored
                    prepared_source_by_record_id[stored.id] = source

                for template_id in snapshot.active_template_ids:
                    if template_id in target_by_template_id:
                        continue
                    stored = active_by_template_id.get(template_id)
                    if stored is None:
                        raise ValueError(f"当前快照缺少模板版本：{template_id}。")
                    target_by_template_id[template_id] = stored

                parent_template_id_by_record_id: dict[UUID, str | None] = {}
                for record in target_by_template_id.values():
                    prepared_source = prepared_source_by_record_id.get(record.id)
                    if prepared_source is not None:
                        parent_template_id_by_record_id[record.id] = (
                            prepared_source.extends_template_id
                        )
                        continue
                    if record.extends_id is None:
                        parent_template_id_by_record_id[record.id] = None
                        continue
                    parent = active_by_record_id.get(record.extends_id)
                    if parent is None:
                        parent = await session.get(ExpertTemplateRecord, record.extends_id)
                    if parent is None:
                        raise ValueError(f"模板 {record.template_id} 的父模板不存在。")
                    parent_template_id_by_record_id[record.id] = parent.template_id

                for record in target_by_template_id.values():
                    parent_template_id = parent_template_id_by_record_id[record.id]
                    if parent_template_id is None:
                        record.extends_id = None
                        continue
                    parent = target_by_template_id.get(parent_template_id)
                    if parent is None:
                        raise ValueError(f"模板 {record.template_id} 的父模板不在当前快照中。")
                    record.extends_id = parent.id

                target_record_ids = {record.id for record in target_by_template_id.values()}
                for record in active_records:
                    if record.id in target_record_ids:
                        continue
                    record.status = "inactive"
                    record.inactivated_at = snapshot.synced_at
                    record.updated_at = snapshot.synced_at
                await session.flush()

                for record in target_by_template_id.values():
                    record.status = "active"
                    record.inactivated_at = None
                    record.updated_at = snapshot.synced_at

    async def get_index_status(
        self,
        current_source_hash: str,
    ) -> ExpertTemplateIndexStatus:
        async with self._session_factory() as session:
            latest_run = await session.scalar(
                select(ExpertTemplateSyncRun)
                .order_by(
                    ExpertTemplateSyncRun.started_at.desc(),
                    ExpertTemplateSyncRun.id.desc(),
                )
                .limit(1)
            )
            active_template_ids = frozenset(
                (
                    await session.scalars(
                        select(ExpertTemplateRecord.template_id).where(
                            ExpertTemplateRecord.status == "active"
                        )
                    )
                ).all()
            )
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(ExpertTemplateChunkRecord)
                .join(
                    ExpertTemplateRecord,
                    ExpertTemplateRecord.id == ExpertTemplateChunkRecord.template_record_id,
                )
                .where(ExpertTemplateRecord.status == "active")
            )
            embedding_models = tuple(
                (
                    await session.scalars(
                        select(ExpertTemplateChunkRecord.embedding_model)
                        .join(
                            ExpertTemplateRecord,
                            ExpertTemplateRecord.id == ExpertTemplateChunkRecord.template_record_id,
                        )
                        .where(ExpertTemplateRecord.status == "active")
                        .distinct()
                    )
                ).all()
            )

        chunks = int(chunk_count or 0)
        latest_run_status = latest_run.status if latest_run is not None else None
        source_hash_matches = (
            latest_run is not None and latest_run.source_hash == current_source_hash
        )
        embedding_model = embedding_models[0] if len(embedding_models) == 1 else None
        embedding_dimensions = (
            latest_run.embedding_dimensions if latest_run is not None and chunks > 0 else None
        )
        defaults_ready = self._required_default_ids <= active_template_ids
        queryable = (
            latest_run_status == "succeeded"
            and source_hash_matches
            and bool(active_template_ids)
            and chunks > 0
            and embedding_model == EMBEDDING_MODEL
            and latest_run is not None
            and latest_run.embedding_model == EMBEDDING_MODEL
            and embedding_dimensions == EMBEDDING_DIMENSIONS
            and defaults_ready
        )
        return ExpertTemplateIndexStatus(
            latest_run_status=latest_run_status,
            source_hash_matches=source_hash_matches,
            active_template_count=len(active_template_ids),
            chunk_count=chunks,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            queryable=queryable,
        )

    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]:
        vector = _validate_query_embedding(query_embedding)
        _validate_candidate_limit(limit)
        profile = self._registry.get_profile(profile_id)
        cosine_distance = ExpertTemplateChunkRecord.embedding.cosine_distance(vector).label(
            "cosine_distance"
        )
        statement = (
            select(
                ExpertTemplateChunkRecord,
                ExpertTemplateRecord,
                cosine_distance,
            )
            .join(
                ExpertTemplateRecord,
                ExpertTemplateRecord.id == ExpertTemplateChunkRecord.template_record_id,
            )
            .where(*_candidate_conditions(profile, prompt_name))
            .order_by(
                cosine_distance.asc(),
                ExpertTemplateRecord.template_id.asc(),
                ExpertTemplateRecord.version.asc(),
                ExpertTemplateChunkRecord.chunk_index.asc(),
                ExpertTemplateChunkRecord.id.asc(),
            )
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        return tuple(
            _expert_template_candidate(
                chunk,
                template,
                vector_similarity=1.0 - float(distance),
                lexical_score=None,
            )
            for chunk, template, distance in rows
            if distance is not None
        )

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            return ()
        _validate_candidate_limit(limit)
        profile = self._registry.get_profile(profile_id)
        ts_query = func.websearch_to_tsquery("simple", normalized_query)
        lexical_score = func.ts_rank_cd(
            ExpertTemplateChunkRecord.search_vector,
            ts_query,
        ).label("lexical_score")
        statement = (
            select(
                ExpertTemplateChunkRecord,
                ExpertTemplateRecord,
                lexical_score,
            )
            .join(
                ExpertTemplateRecord,
                ExpertTemplateRecord.id == ExpertTemplateChunkRecord.template_record_id,
            )
            .where(
                *_candidate_conditions(profile, prompt_name),
                ExpertTemplateChunkRecord.search_vector.bool_op("@@")(ts_query),
            )
            .order_by(
                lexical_score.desc(),
                ExpertTemplateRecord.template_id.asc(),
                ExpertTemplateRecord.version.asc(),
                ExpertTemplateChunkRecord.chunk_index.asc(),
                ExpertTemplateChunkRecord.id.asc(),
            )
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        return tuple(
            _expert_template_candidate(
                chunk,
                template,
                vector_similarity=None,
                lexical_score=float(score),
            )
            for chunk, template, score in rows
        )

    async def get_active_template_documents(
        self,
        record_ids: Sequence[UUID],
    ) -> tuple[ExpertTemplateDocument, ...]:
        ordered_ids = tuple(dict.fromkeys(record_ids))
        if not ordered_ids:
            return ()
        async with self._session_factory() as session:
            records = tuple(
                (
                    await session.scalars(
                        select(ExpertTemplateRecord).where(
                            ExpertTemplateRecord.id.in_(ordered_ids),
                            ExpertTemplateRecord.status == "active",
                        )
                    )
                ).all()
            )
        by_id = {record.id: record for record in records}
        return tuple(
            _expert_template_document(by_id[value]) for value in ordered_ids if value in by_id
        )

    async def get_active_template_documents_by_template_ids(
        self,
        template_ids: Sequence[str],
    ) -> tuple[ExpertTemplateDocument, ...]:
        ordered_ids = tuple(dict.fromkeys(template_ids))
        if not ordered_ids:
            return ()
        async with self._session_factory() as session:
            records = tuple(
                (
                    await session.scalars(
                        select(ExpertTemplateRecord).where(
                            ExpertTemplateRecord.template_id.in_(ordered_ids),
                            ExpertTemplateRecord.status == "active",
                        )
                    )
                ).all()
            )
        by_template_id = {record.template_id: record for record in records}
        return tuple(
            _expert_template_document(by_template_id[value])
            for value in ordered_ids
            if value in by_template_id
        )

    async def list_active_templates(
        self,
        query: TemplateListQuery,
    ) -> tuple[ExpertTemplateRecord, ...]:
        if isinstance(query.limit, bool) or not 1 <= query.limit <= 100:
            raise ValueError("模板列表 limit 必须在 1 到 100 之间。")
        if isinstance(query.offset, bool) or query.offset < 0:
            raise ValueError("模板列表 offset 不能小于 0。")

        statement = select(ExpertTemplateRecord).where(ExpertTemplateRecord.status == "active")
        if query.profile_id is not None:
            profile = self._registry.get_profile(query.profile_id)
            statement = statement.where(ExpertTemplateRecord.layer.in_(profile.layers))
            if profile.cloud != "neutral":
                statement = statement.where(
                    or_(
                        ExpertTemplateRecord.cloud == "neutral",
                        ExpertTemplateRecord.cloud == profile.cloud,
                    )
                )
        if query.kind is not None:
            statement = statement.where(ExpertTemplateRecord.kind == query.kind.value)
        if query.category is not None:
            statement = statement.where(ExpertTemplateRecord.category == query.category.value)
        statement = (
            statement.order_by(
                ExpertTemplateRecord.template_id.asc(),
                ExpertTemplateRecord.version.asc(),
                ExpertTemplateRecord.id.asc(),
            )
            .limit(query.limit)
            .offset(query.offset)
        )

        async with self._session_factory() as session:
            return tuple((await session.scalars(statement)).all())


async def _existing_versions(
    session: AsyncSession,
    prepared_templates: tuple[PreparedTemplateVersion, ...],
) -> dict[tuple[str, str], ExpertTemplateRecord]:
    template_ids = tuple(item.source.template_id for item in prepared_templates)
    if not template_ids:
        return {}
    records = tuple(
        (
            await session.scalars(
                select(ExpertTemplateRecord).where(
                    ExpertTemplateRecord.template_id.in_(template_ids)
                )
            )
        ).all()
    )
    return {(record.template_id, record.version): record for record in records}


def _new_template_record(prepared: PreparedTemplateVersion) -> ExpertTemplateRecord:
    source = prepared.source
    return ExpertTemplateRecord(
        id=uuid4(),
        template_id=source.template_id,
        version=source.version,
        name=source.name,
        summary=source.summary,
        kind=source.kind.value,
        category=source.category.value,
        layer=source.layer,
        profile_id=source.profile_id,
        cloud=source.cloud,
        prompt_names=[prompt.value for prompt in source.prompt_names],
        tags=list(source.tags),
        extends_id=None,
        official_refs=list(source.official_refs),
        source_path=source.source_path,
        content=source.content,
        content_hash=source.content_hash,
        status="inactive",
        chunk_count=len(prepared.chunks),
    )


def _add_chunks(
    session: AsyncSession,
    template_record_id: UUID,
    prepared: PreparedTemplateVersion,
) -> None:
    for chunk, embedding in zip(prepared.chunks, prepared.embeddings, strict=True):
        session.add(
            ExpertTemplateChunkRecord(
                id=uuid4(),
                template_record_id=template_record_id,
                chunk_index=chunk.chunk_index,
                heading_path=list(chunk.heading_path),
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
                embedding=list(embedding.embedding),
                embedding_model=EMBEDDING_MODEL,
            )
        )


def _validate_snapshot(snapshot: PreparedTemplateSnapshot) -> None:
    if not snapshot.active_template_ids:
        raise ValueError("专家模板快照不能为空。")
    template_ids = tuple(item.source.template_id for item in snapshot.templates)
    if len(template_ids) != len(set(template_ids)):
        raise ValueError("专家模板快照包含重复模板 ID。")
    if not set(template_ids) <= snapshot.active_template_ids:
        raise ValueError("新增模板必须属于当前 active 快照。")

    for prepared in snapshot.templates:
        if len(prepared.chunks) != len(prepared.embeddings):
            raise ValueError("Chunk 与 Embedding 数量不一致。")
        if not prepared.chunks:
            raise ValueError("专家模板必须至少包含一个 Chunk。")
        for index, (chunk, embedding) in enumerate(
            zip(prepared.chunks, prepared.embeddings, strict=True)
        ):
            if chunk.chunk_index != index or embedding.index != index:
                raise ValueError("Embedding index 与 Chunk 顺序不一致。")
            if len(embedding.embedding) != EMBEDDING_DIMENSIONS:
                raise ValueError("Embedding 维度不匹配。")
            if any(not isfinite(float(value)) for value in embedding.embedding):
                raise ValueError("Embedding 包含无效数值。")


def _candidate_conditions(
    profile: ExpertProfile,
    prompt_name: PromptName,
) -> tuple[ColumnElement[bool], ...]:
    conditions: list[ColumnElement[bool]] = [
        ExpertTemplateRecord.status == "active",
        ExpertTemplateChunkRecord.embedding_model == EMBEDDING_MODEL,
        ExpertTemplateRecord.layer.in_(profile.layers),
        ExpertTemplateRecord.prompt_names.contains([prompt_name.value]),
    ]
    if profile.cloud != "neutral":
        conditions.append(
            or_(
                ExpertTemplateRecord.cloud == "neutral",
                ExpertTemplateRecord.cloud == profile.cloud,
            )
        )
    return tuple(conditions)


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
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("专家模板候选数量必须在 1 到 100 之间。")


def _expert_template_candidate(
    chunk: ExpertTemplateChunkRecord,
    template: ExpertTemplateRecord,
    *,
    vector_similarity: float | None,
    lexical_score: float | None,
) -> ExpertTemplateCandidate:
    return ExpertTemplateCandidate(
        chunk_id=chunk.id,
        template_record_id=template.id,
        template_id=template.template_id,
        version=template.version,
        name=template.name,
        layer=template.layer,
        profile_id=template.profile_id,
        cloud=template.cloud,
        kind=ExpertTemplateKind(template.kind),
        category=ExpertTemplateCategory(template.category),
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        content_hash=template.content_hash,
        extends_record_id=template.extends_id,
        vector_similarity=vector_similarity,
        lexical_score=lexical_score,
    )


def _expert_template_document(
    record: ExpertTemplateRecord,
) -> ExpertTemplateDocument:
    return ExpertTemplateDocument(
        record_id=record.id,
        template_id=record.template_id,
        version=record.version,
        name=record.name,
        summary=record.summary,
        kind=ExpertTemplateKind(record.kind),
        category=ExpertTemplateCategory(record.category),
        layer=record.layer,
        profile_id=record.profile_id,
        cloud=record.cloud,
        content_hash=record.content_hash,
        extends_record_id=record.extends_id,
        content=record.content,
        source_path=record.source_path,
        official_refs=tuple(record.official_refs),
    )
