from collections.abc import Sequence
from math import isfinite
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.expert_templates.constants import (
    EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K,
    EXPERT_TEMPLATE_MIN_VECTOR_SCORE,
    EXPERT_TEMPLATE_VECTOR_CANDIDATE_K,
)
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextBuilder,
    ExpertTemplateContextNotFoundError,
    ExpertTemplateDocument,
    ExpertTemplateRetrievalBundle,
    RankedExpertTemplateCandidate,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateCandidate
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.constants import EMBEDDING_DIMENSIONS
from databricks_zh_expert.search.hybrid import (
    extract_lexical_query,
    reciprocal_rank_fusion_ids,
)


class ExpertTemplateCandidateRepository(Protocol):
    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]: ...

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]: ...

    async def get_active_template_documents(
        self,
        record_ids: Sequence[UUID],
    ) -> tuple[ExpertTemplateDocument, ...]: ...

    async def get_active_template_documents_by_template_ids(
        self,
        template_ids: Sequence[str],
    ) -> tuple[ExpertTemplateDocument, ...]: ...


class ExpertTemplateRetriever:
    def __init__(
        self,
        *,
        repository: ExpertTemplateCandidateRepository,
        registry: ExpertTemplateRegistry,
        context_builder: ExpertTemplateContextBuilder | None = None,
        min_vector_score: float = EXPERT_TEMPLATE_MIN_VECTOR_SCORE,
    ) -> None:
        if (
            isinstance(min_vector_score, bool)
            or not isinstance(min_vector_score, int | float)
            or not 0 <= min_vector_score <= 1
        ):
            raise ValueError("专家模板最低向量分数必须在 0 到 1 之间。")
        self._repository = repository
        self._registry = registry
        self._context_builder = context_builder or ExpertTemplateContextBuilder()
        self._min_vector_score = float(min_vector_score)

    async def retrieve(
        self,
        query: str,
        *,
        query_embedding: Sequence[float],
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle:
        normalized_query = query.strip() if isinstance(query, str) else ""
        if not normalized_query:
            raise ValueError("专家模板检索问题不能为空。")
        vector = _validate_query_embedding(query_embedding)
        profile = self._registry.get_profile(profile_id)

        vector_candidates = await self._repository.find_vector_candidates(
            vector,
            profile_id=profile.id,
            prompt_name=prompt_name,
            limit=EXPERT_TEMPLATE_VECTOR_CANDIDATE_K,
        )
        lexical_query = extract_lexical_query(normalized_query)
        lexical_candidates = (
            await self._repository.find_lexical_candidates(
                lexical_query,
                profile_id=profile.id,
                prompt_name=prompt_name,
                limit=EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K,
            )
            if lexical_query
            else ()
        )

        if lexical_candidates or _best_vector_score(vector_candidates) >= self._min_vector_score:
            ranked_candidates = reciprocal_rank_fusion_templates(
                vector_candidates,
                lexical_candidates,
            )
            if ranked_candidates:
                try:
                    documents = await self._load_candidate_documents(ranked_candidates)
                    return self._context_builder.build(
                        normalized_query,
                        profile_id=profile.id,
                        prompt_name=prompt_name,
                        ranked_candidates=ranked_candidates,
                        documents=documents,
                    )
                except ExpertTemplateContextNotFoundError:
                    pass

        return await self._build_default_bundle(
            normalized_query,
            profile_id=profile.id,
            prompt_name=prompt_name,
        )

    async def _load_candidate_documents(
        self,
        candidates: Sequence[RankedExpertTemplateCandidate],
    ) -> dict[UUID, ExpertTemplateDocument]:
        record_ids = tuple(
            dict.fromkeys(
                record_id
                for candidate in candidates
                for record_id in (
                    candidate.template_record_id,
                    candidate.extends_record_id,
                )
                if record_id is not None
            )
        )
        documents = await self._repository.get_active_template_documents(record_ids)
        return await self._load_parent_documents(documents)

    async def _load_parent_documents(
        self,
        initial: Sequence[ExpertTemplateDocument],
    ) -> dict[UUID, ExpertTemplateDocument]:
        documents = {item.record_id: item for item in initial}
        while True:
            pending = tuple(
                dict.fromkeys(
                    item.extends_record_id
                    for item in documents.values()
                    if item.extends_record_id is not None
                    and item.extends_record_id not in documents
                )
            )
            if not pending:
                return documents
            loaded = await self._repository.get_active_template_documents(pending)
            if not loaded:
                return documents
            documents.update((item.record_id, item) for item in loaded)

    async def _build_default_bundle(
        self,
        query: str,
        *,
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle:
        profile = self._registry.get_profile(profile_id)
        template_ids = profile.prompt_defaults.get(prompt_name, ())
        if not template_ids:
            raise ExpertTemplateContextNotFoundError("当前 Profile 没有可用的默认专家模板。")
        documents = await self._repository.get_active_template_documents_by_template_ids(
            template_ids
        )
        by_template_id = {item.template_id: item for item in documents}
        if any(template_id not in by_template_id for template_id in template_ids):
            raise ExpertTemplateContextNotFoundError("默认专家模板没有 active 数据库版本。")
        documents_by_id = await self._load_parent_documents(documents)
        defaults = tuple(
            _default_candidate(by_template_id[template_id], rank)
            for rank, template_id in enumerate(template_ids, start=1)
        )
        return self._context_builder.build(
            query,
            profile_id=profile_id,
            prompt_name=prompt_name,
            ranked_candidates=defaults,
            documents=documents_by_id,
        )


def reciprocal_rank_fusion_templates(
    vector_candidates: Sequence[ExpertTemplateCandidate],
    lexical_candidates: Sequence[ExpertTemplateCandidate],
    *,
    rrf_k: int = 60,
) -> tuple[RankedExpertTemplateCandidate, ...]:
    candidates_by_chunk_id: dict[UUID, ExpertTemplateCandidate] = {}
    vector_similarity_by_id: dict[UUID, float | None] = {}
    lexical_score_by_id: dict[UUID, float | None] = {}

    for candidate in vector_candidates:
        candidates_by_chunk_id.setdefault(candidate.chunk_id, candidate)
        vector_similarity_by_id.setdefault(candidate.chunk_id, candidate.vector_similarity)
    for candidate in lexical_candidates:
        candidates_by_chunk_id.setdefault(candidate.chunk_id, candidate)
        lexical_score_by_id.setdefault(candidate.chunk_id, candidate.lexical_score)

    ranks = reciprocal_rank_fusion_ids(
        tuple(candidate.chunk_id for candidate in vector_candidates),
        tuple(candidate.chunk_id for candidate in lexical_candidates),
        rrf_k=rrf_k,
    )
    ranked_chunks = tuple(
        RankedExpertTemplateCandidate(
            chunk_id=rank.item_id,
            template_record_id=candidates_by_chunk_id[rank.item_id].template_record_id,
            template_id=candidates_by_chunk_id[rank.item_id].template_id,
            version=candidates_by_chunk_id[rank.item_id].version,
            name=candidates_by_chunk_id[rank.item_id].name,
            layer=candidates_by_chunk_id[rank.item_id].layer,
            profile_id=candidates_by_chunk_id[rank.item_id].profile_id,
            kind=candidates_by_chunk_id[rank.item_id].kind,
            category=candidates_by_chunk_id[rank.item_id].category,
            content_hash=candidates_by_chunk_id[rank.item_id].content_hash,
            extends_record_id=candidates_by_chunk_id[rank.item_id].extends_record_id,
            matched_chunk_content=candidates_by_chunk_id[rank.item_id].content,
            vector_similarity=vector_similarity_by_id.get(rank.item_id),
            lexical_score=lexical_score_by_id.get(rank.item_id),
            vector_rank=rank.vector_rank,
            lexical_rank=rank.lexical_rank,
            fused_score=rank.fused_score,
            reason="semantic",
        )
        for rank in ranks
    )
    ordered = sorted(
        ranked_chunks,
        key=lambda item: (
            -item.fused_score,
            item.template_id,
            item.version,
            candidates_by_chunk_id[item.chunk_id].chunk_index,
            str(item.chunk_id),
        ),
    )
    aggregated: list[RankedExpertTemplateCandidate] = []
    seen_templates: set[UUID] = set()
    for candidate in ordered:
        if candidate.template_record_id in seen_templates:
            continue
        seen_templates.add(candidate.template_record_id)
        aggregated.append(candidate)
    return tuple(aggregated)


def _default_candidate(
    document: ExpertTemplateDocument,
    rank: int,
) -> RankedExpertTemplateCandidate:
    return RankedExpertTemplateCandidate(
        chunk_id=document.record_id,
        template_record_id=document.record_id,
        template_id=document.template_id,
        version=document.version,
        name=document.name,
        layer=document.layer,
        profile_id=document.profile_id,
        kind=document.kind,
        category=document.category,
        content_hash=document.content_hash,
        extends_record_id=document.extends_record_id,
        matched_chunk_content="",
        vector_similarity=None,
        lexical_score=None,
        vector_rank=None,
        lexical_rank=None,
        fused_score=1 / (60 + rank),
        reason="default",
    )


def _validate_query_embedding(query_embedding: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(query_embedding)
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"查询 Embedding 必须是 {EMBEDDING_DIMENSIONS} 维。")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value))
        for value in vector
    ):
        raise ValueError("查询 Embedding 包含无效数值。")
    normalized = tuple(float(value) for value in vector)
    if not any(value != 0.0 for value in normalized):
        raise ValueError("查询 Embedding 不能是零向量。")
    return normalized


def _best_vector_score(candidates: Sequence[ExpertTemplateCandidate]) -> float:
    return max(
        (
            candidate.vector_similarity
            for candidate in candidates
            if candidate.vector_similarity is not None
        ),
        default=float("-inf"),
    )
