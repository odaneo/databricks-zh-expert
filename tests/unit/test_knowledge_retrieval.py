from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

import pytest

from databricks_zh_expert.rag.constants import (
    RAG_LEXICAL_CANDIDATE_K,
    RAG_VECTOR_CANDIDATE_K,
)
from databricks_zh_expert.rag.context import KnowledgeContextNotFoundError
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.repository import KnowledgeCandidate
from databricks_zh_expert.rag.retrieval import (
    KnowledgeRetriever,
    extract_lexical_query,
    reciprocal_rank_fusion,
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _candidate(
    value: int,
    *,
    source_key: str | None = None,
    document_id: UUID | None = None,
    chunk_index: int = 0,
    vector_similarity: float | None = None,
    lexical_score: float | None = None,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        chunk_id=_uuid(value),
        chunk_hash=f"{value:064x}",
        document_id=document_id or _uuid(value + 100),
        source_key=source_key or f"docs-{value}",
        title=f"Document {value}",
        canonical_url=f"https://docs.databricks.com/aws/en/document-{value}",
        chunk_index=chunk_index,
        heading_path=("Guide", f"Section {value}"),
        content=f"Knowledge content {value}.",
        token_count=8,
        source_ref=f"https://docs.databricks.com/aws/en/document-{value}#section",
        vector_similarity=vector_similarity,
        lexical_score=lexical_score,
    )


def test_rrf_combines_vector_only_lexical_only_and_shared_candidates() -> None:
    vector_only = _candidate(1, vector_similarity=0.9)
    lexical_only = _candidate(2, lexical_score=0.8)
    shared_vector = _candidate(3, vector_similarity=0.7)
    shared_lexical = replace(shared_vector, vector_similarity=None, lexical_score=0.6)

    ranked = reciprocal_rank_fusion(
        (vector_only, shared_vector),
        (lexical_only, shared_lexical),
        rrf_k=60,
    )

    assert tuple(candidate.chunk_id for candidate in ranked) == (
        shared_vector.chunk_id,
        vector_only.chunk_id,
        lexical_only.chunk_id,
    )
    assert ranked[0].vector_rank == 2
    assert ranked[0].lexical_rank == 2
    assert ranked[0].fused_score == pytest.approx((1 / 62) + (1 / 62))
    assert ranked[1].vector_rank == 1
    assert ranked[1].lexical_rank is None
    assert ranked[2].vector_rank is None
    assert ranked[2].lexical_rank == 1


def test_rrf_uses_stable_secondary_key_for_equal_scores() -> None:
    lexical_first = _candidate(
        20,
        source_key="docs-z",
        lexical_score=0.7,
    )
    vector_first = _candidate(
        10,
        source_key="docs-a",
        vector_similarity=0.7,
    )

    ranked = reciprocal_rank_fusion((vector_first,), (lexical_first,), rrf_k=60)

    assert tuple(candidate.source_key for candidate in ranked) == ("docs-a", "docs-z")


def test_rrf_deduplicates_repeated_chunk_within_each_channel() -> None:
    candidate = _candidate(1, vector_similarity=0.9)
    second = _candidate(2, vector_similarity=0.8)

    ranked = reciprocal_rank_fusion((candidate, candidate, second), (), rrf_k=60)

    assert len(ranked) == 2
    assert ranked[0].fused_score == pytest.approx(1 / 61)
    assert ranked[1].vector_rank == 2
    assert ranked[1].fused_score == pytest.approx(1 / 62)


def test_extract_lexical_query_keeps_precise_english_terms_and_paths() -> None:
    lexical_query = extract_lexical_query(
        "如何用 OPTIMIZE 配合 run_if，并调用 /api/2.1/jobs/runs/submit？"
    )

    assert lexical_query == "OPTIMIZE OR run_if OR /api/2.1/jobs/runs/submit"


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.query_calls: list[str] = []

    async def embed_query(self, text: str) -> EmbeddingResult:
        self.query_calls.append(text)
        return EmbeddingResult(index=0, embedding=(1.0,) * 1536)

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[EmbeddingResult, ...]:
        del texts
        raise AssertionError("在线检索不得调用 embed_documents。")


class _FakeKnowledgeRepository:
    def __init__(
        self,
        *,
        vector_candidates: tuple[KnowledgeCandidate, ...],
        lexical_candidates: tuple[KnowledgeCandidate, ...],
    ) -> None:
        self.vector_candidates = vector_candidates
        self.lexical_candidates = lexical_candidates
        self.vector_calls: list[tuple[tuple[float, ...], int]] = []
        self.lexical_calls: list[tuple[str, int]] = []

    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]:
        self.vector_calls.append((tuple(query_embedding), limit))
        return self.vector_candidates

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[KnowledgeCandidate, ...]:
        self.lexical_calls.append((query, limit))
        return self.lexical_candidates


@pytest.mark.asyncio
async def test_retriever_embeds_query_once_and_uses_fixed_candidate_limits() -> None:
    vector_candidate = _candidate(1, vector_similarity=0.9)
    lexical_candidate = replace(
        vector_candidate,
        vector_similarity=None,
        lexical_score=0.7,
    )
    embedding_client = _FakeEmbeddingClient()
    repository = _FakeKnowledgeRepository(
        vector_candidates=(vector_candidate,),
        lexical_candidates=(lexical_candidate,),
    )
    retriever = KnowledgeRetriever(
        repository=repository,
        embedding_client=embedding_client,
    )

    bundle = await retriever.retrieve("如何执行 OPTIMIZE？")

    assert embedding_client.query_calls == ["如何执行 OPTIMIZE？"]
    assert len(repository.vector_calls) == 1
    assert repository.vector_calls[0][1] == RAG_VECTOR_CANDIDATE_K
    assert repository.lexical_calls == [("OPTIMIZE", RAG_LEXICAL_CANDIDATE_K)]
    assert tuple(chunk.chunk_id for chunk in bundle.selected_chunks) == (vector_candidate.chunk_id,)
    assert bundle.citations[0].citation_id == "S1"


@pytest.mark.asyncio
async def test_retriever_rejects_low_vector_score_without_lexical_match() -> None:
    embedding_client = _FakeEmbeddingClient()
    repository = _FakeKnowledgeRepository(
        vector_candidates=(_candidate(1, vector_similarity=0.29),),
        lexical_candidates=(),
    )
    retriever = KnowledgeRetriever(
        repository=repository,
        embedding_client=embedding_client,
    )

    with pytest.raises(KnowledgeContextNotFoundError) as error:
        await retriever.retrieve("完全无关的问题")

    assert error.value.code == "knowledge_context_not_found"
    assert embedding_client.query_calls == ["完全无关的问题"]


@pytest.mark.asyncio
async def test_retriever_accepts_lexical_match_when_vector_score_is_low() -> None:
    low_vector = _candidate(1, vector_similarity=0.1)
    lexical = _candidate(2, lexical_score=0.8)
    repository = _FakeKnowledgeRepository(
        vector_candidates=(low_vector,),
        lexical_candidates=(lexical,),
    )
    retriever = KnowledgeRetriever(
        repository=repository,
        embedding_client=_FakeEmbeddingClient(),
    )

    bundle = await retriever.retrieve("请解释 run_if")

    assert tuple(chunk.chunk_id for chunk in bundle.selected_chunks) == (
        low_vector.chunk_id,
        lexical.chunk_id,
    )
