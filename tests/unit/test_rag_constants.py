from pathlib import Path

from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.rag.constants import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    KNOWLEDGE_FETCH_TIMEOUT_SECONDS,
    KNOWLEDGE_MANIFEST_PATH,
    RAG_LEXICAL_CANDIDATE_K,
    RAG_MAX_CONTEXT_TOKENS,
    RAG_MIN_VECTOR_SCORE,
    RAG_TOP_K,
    RAG_VECTOR_CANDIDATE_K,
)


def test_rag_product_constants_are_fixed() -> None:
    assert EMBEDDING_MODEL == "text-embedding-3-small"
    assert EMBEDDING_DIMENSIONS == 1536
    assert KNOWLEDGE_MANIFEST_PATH == Path("knowledge/databricks/sources.yml")
    assert KNOWLEDGE_FETCH_TIMEOUT_SECONDS == 30
    assert RAG_VECTOR_CANDIDATE_K == 30
    assert RAG_LEXICAL_CANDIDATE_K == 30
    assert RAG_TOP_K == 6
    assert RAG_MAX_CONTEXT_TOKENS == 5000
    assert RAG_MIN_VECTOR_SCORE == 0.3


def test_rag_product_constants_are_not_deployment_settings() -> None:
    assert {
        "embedding_model",
        "embedding_dimensions",
        "knowledge_manifest_path",
        "knowledge_fetch_timeout_seconds",
        "rag_vector_candidate_k",
        "rag_lexical_candidate_k",
        "rag_top_k",
        "rag_max_context_tokens",
        "rag_min_vector_score",
    }.isdisjoint(Settings.model_fields)
