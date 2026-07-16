from databricks_zh_expert.rag.types import NormalizedDocument
from databricks_zh_expert.search.markdown import (
    ChunkingError,
    MarkdownChunk,
    MarkdownSource,
)
from databricks_zh_expert.search.markdown import (
    MarkdownChunker as SharedMarkdownChunker,
)

KnowledgeChunk = MarkdownChunk

__all__ = ["ChunkingError", "KnowledgeChunk", "MarkdownChunker"]


class MarkdownChunker:
    def __init__(
        self,
        *,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
    ) -> None:
        self._shared = SharedMarkdownChunker(
            chunk_size_tokens=chunk_size_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
        )

    def split(self, document: NormalizedDocument) -> tuple[KnowledgeChunk, ...]:
        return self._shared.split(
            MarkdownSource(
                title=document.title,
                source_ref=document.canonical_url,
                content=document.normalized_content,
                heading_anchors=document.heading_anchors,
            )
        )
