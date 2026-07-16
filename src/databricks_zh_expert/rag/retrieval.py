import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
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

_LEXICAL_TOKEN_PATTERN = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+|[A-Za-z][A-Za-z0-9_.-]*")
_LEXICAL_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "databricks",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "please",
        "the",
        "to",
        "use",
        "what",
        "with",
    }
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


@dataclass(slots=True)
class _FusionState:
    candidate: KnowledgeCandidate
    vector_similarity: float | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    lexical_rank: int | None = None


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
        vector_candidates = await self._repository.find_vector_candidates(
            query_embedding.embedding,
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


def extract_lexical_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query)
    terms: list[str] = []
    seen: set[str] = set()
    for match in _LEXICAL_TOKEN_PATTERN.finditer(normalized):
        term = match.group(0).rstrip(".-")
        normalized_term = term.casefold()
        if not term or normalized_term in _LEXICAL_STOP_WORDS or normalized_term in seen:
            continue
        if not term.startswith("/") and len(term) < 2:
            continue
        seen.add(normalized_term)
        terms.append(term)
    return " OR ".join(terms)


def reciprocal_rank_fusion(
    vector_candidates: Sequence[KnowledgeCandidate],
    lexical_candidates: Sequence[KnowledgeCandidate],
    *,
    rrf_k: int = 60,
) -> tuple[RankedKnowledgeChunk, ...]:
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
        raise ValueError("RRF k 必须是正整数。")

    states: dict[UUID, _FusionState] = {}
    seen_vector: set[UUID] = set()
    for candidate in vector_candidates:
        if candidate.chunk_id in seen_vector:
            continue
        seen_vector.add(candidate.chunk_id)
        rank = len(seen_vector)
        state = states.setdefault(candidate.chunk_id, _FusionState(candidate=candidate))
        state.vector_rank = rank
        state.vector_similarity = candidate.vector_similarity

    seen_lexical: set[UUID] = set()
    for candidate in lexical_candidates:
        if candidate.chunk_id in seen_lexical:
            continue
        seen_lexical.add(candidate.chunk_id)
        rank = len(seen_lexical)
        state = states.setdefault(candidate.chunk_id, _FusionState(candidate=candidate))
        state.lexical_rank = rank
        state.lexical_score = candidate.lexical_score

    ranked = tuple(_ranked_chunk(state, rrf_k=rrf_k) for state in states.values())
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


def _ranked_chunk(state: _FusionState, *, rrf_k: int) -> RankedKnowledgeChunk:
    candidate = state.candidate
    fused_score = 0.0
    if state.vector_rank is not None:
        fused_score += 1 / (rrf_k + state.vector_rank)
    if state.lexical_rank is not None:
        fused_score += 1 / (rrf_k + state.lexical_rank)
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
        vector_similarity=state.vector_similarity,
        lexical_score=state.lexical_score,
        vector_rank=state.vector_rank,
        lexical_rank=state.lexical_rank,
        fused_score=fused_score,
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
