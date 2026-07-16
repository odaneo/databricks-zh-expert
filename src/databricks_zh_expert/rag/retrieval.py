from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.rag.constants import (
    RAG_LEXICAL_CANDIDATE_K,
    RAG_MIN_VECTOR_SCORE,
    RAG_VECTOR_CANDIDATE_K,
)
from databricks_zh_expert.rag.context import (
    KnowledgeContextBuilder,
    KnowledgeContextNotFoundError,
    RankedKnowledgeChunk,
    RetrievalBundle,
)
from databricks_zh_expert.rag.embeddings import EmbeddingClient
from databricks_zh_expert.rag.repository import KnowledgeCandidate
from databricks_zh_expert.search.hybrid import (
    FusionRank,
    extract_lexical_query,
    reciprocal_rank_fusion_ids,
)


class KnowledgeCandidateRepository(Protocol):
    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]: ...

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]: ...


class KnowledgeRetriever:
    def __init__(
        self,
        *,
        repository: KnowledgeCandidateRepository,
        embedding_client: EmbeddingClient,
        context_builder: KnowledgeContextBuilder | None = None,
        min_vector_score: float = RAG_MIN_VECTOR_SCORE,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._context_builder = context_builder or KnowledgeContextBuilder()
        self._min_vector_score = min_vector_score

    async def retrieve(self, query: str) -> RetrievalBundle:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("知识检索问题不能为空。")

        query_embedding = await self._embedding_client.embed_query(query)
        return await self.retrieve_with_embedding(query, query_embedding.embedding)

    async def retrieve_with_embedding(
        self,
        query: str,
        query_embedding: Sequence[float],
    ) -> RetrievalBundle:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("知识检索问题不能为空。")

        vector_candidates = await self._repository.find_vector_candidates(
            query_embedding,
            limit=RAG_VECTOR_CANDIDATE_K,
        )
        lexical_query = extract_lexical_query(query)
        lexical_candidates = (
            await self._repository.find_lexical_candidates(
                lexical_query,
                limit=RAG_LEXICAL_CANDIDATE_K,
            )
            if lexical_query
            else ()
        )

        if (
            not lexical_candidates
            and _best_vector_score(vector_candidates) < self._min_vector_score
        ):
            raise KnowledgeContextNotFoundError("没有找到达到相关性阈值的知识上下文。")

        ranked_candidates = reciprocal_rank_fusion(
            vector_candidates,
            lexical_candidates,
        )
        if not ranked_candidates:
            raise KnowledgeContextNotFoundError("没有找到可用的知识上下文。")
        return self._context_builder.build(query, ranked_candidates)


def reciprocal_rank_fusion(
    vector_candidates: Sequence[KnowledgeCandidate],
    lexical_candidates: Sequence[KnowledgeCandidate],
    *,
    rrf_k: int = 60,
) -> tuple[RankedKnowledgeChunk, ...]:
    candidates_by_id: dict[UUID, KnowledgeCandidate] = {}
    vector_similarity_by_id: dict[UUID, float | None] = {}
    lexical_score_by_id: dict[UUID, float | None] = {}

    seen_vector: set[UUID] = set()
    for candidate in vector_candidates:
        if candidate.chunk_id in seen_vector:
            continue
        seen_vector.add(candidate.chunk_id)
        candidates_by_id.setdefault(candidate.chunk_id, candidate)
        vector_similarity_by_id[candidate.chunk_id] = candidate.vector_similarity

    seen_lexical: set[UUID] = set()
    for candidate in lexical_candidates:
        if candidate.chunk_id in seen_lexical:
            continue
        seen_lexical.add(candidate.chunk_id)
        candidates_by_id.setdefault(candidate.chunk_id, candidate)
        lexical_score_by_id[candidate.chunk_id] = candidate.lexical_score

    fusion_ranks = reciprocal_rank_fusion_ids(
        tuple(candidate.chunk_id for candidate in vector_candidates),
        tuple(candidate.chunk_id for candidate in lexical_candidates),
        rrf_k=rrf_k,
    )
    ranked = tuple(
        _ranked_chunk(
            candidates_by_id[rank.item_id],
            rank=rank,
            vector_similarity=vector_similarity_by_id.get(rank.item_id),
            lexical_score=lexical_score_by_id.get(rank.item_id),
        )
        for rank in fusion_ranks
    )
    return tuple(
        sorted(
            ranked,
            key=lambda candidate: (
                -candidate.fused_score,
                candidate.source_key,
                candidate.chunk_index,
                str(candidate.chunk_id),
            ),
        )
    )


def _ranked_chunk(
    candidate: KnowledgeCandidate,
    *,
    rank: FusionRank,
    vector_similarity: float | None,
    lexical_score: float | None,
) -> RankedKnowledgeChunk:
    return RankedKnowledgeChunk(
        chunk_id=candidate.chunk_id,
        chunk_hash=candidate.chunk_hash,
        document_id=candidate.document_id,
        source_key=candidate.source_key,
        title=candidate.title,
        canonical_url=candidate.canonical_url,
        chunk_index=candidate.chunk_index,
        heading_path=candidate.heading_path,
        content=candidate.content,
        token_count=candidate.token_count,
        source_ref=candidate.source_ref,
        vector_similarity=vector_similarity,
        lexical_score=lexical_score,
        vector_rank=rank.vector_rank,
        lexical_rank=rank.lexical_rank,
        fused_score=rank.fused_score,
        link_only=candidate.link_only,
    )


def _best_vector_score(candidates: Sequence[KnowledgeCandidate]) -> float:
    return max(
        (
            candidate.vector_similarity
            for candidate in candidates
            if candidate.vector_similarity is not None
        ),
        default=float("-inf"),
    )
