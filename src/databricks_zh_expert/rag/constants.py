from pathlib import Path
from typing import Final

EMBEDDING_MODEL: Final = "text-embedding-3-small"
EMBEDDING_DIMENSIONS: Final = 1536
KNOWLEDGE_MANIFEST_PATH: Final = Path("knowledge/databricks/sources.yml")
KNOWLEDGE_FETCH_TIMEOUT_SECONDS: Final = 30
RAG_VECTOR_CANDIDATE_K: Final = 30
RAG_LEXICAL_CANDIDATE_K: Final = 30
RAG_TOP_K: Final = 6
RAG_MAX_CONTEXT_TOKENS: Final = 5000
RAG_MIN_VECTOR_SCORE: Final = 0.3
