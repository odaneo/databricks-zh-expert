from uuid import UUID

from databricks_zh_expert.rag.context import (
    KnowledgeContextBuilder,
    RankedKnowledgeChunk,
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _ranked_chunk(
    value: int,
    *,
    document_id: UUID | None = None,
    source_key: str | None = None,
    chunk_index: int = 0,
    heading_path: tuple[str, ...] = ("Lakeflow Jobs", "Task dependencies"),
    source_ref: str | None = None,
    content: str | None = None,
    fused_score: float | None = None,
    link_only: bool = False,
) -> RankedKnowledgeChunk:
    resolved_document_id = document_id or _uuid(value + 100)
    resolved_source_key = source_key or f"docs-{value}"
    return RankedKnowledgeChunk(
        chunk_id=_uuid(value),
        chunk_hash=f"{value:064x}",
        document_id=resolved_document_id,
        source_key=resolved_source_key,
        title=f"Document {value}",
        canonical_url=f"https://docs.databricks.com/aws/en/document-{value}",
        chunk_index=chunk_index,
        heading_path=heading_path,
        content=content or f"Knowledge content {value}.",
        token_count=8,
        source_ref=source_ref or f"https://docs.databricks.com/aws/en/document-{value}#section",
        vector_similarity=0.9,
        lexical_score=None,
        vector_rank=value,
        lexical_rank=None,
        fused_score=fused_score if fused_score is not None else 1 / (60 + value),
        link_only=link_only,
    )


def test_context_deduplicates_chunks_and_merges_adjacent_same_section() -> None:
    document_id = _uuid(200)
    source_ref = "https://docs.databricks.com/aws/en/jobs#task-dependencies"
    first = _ranked_chunk(
        1,
        document_id=document_id,
        source_key="docs-jobs",
        chunk_index=0,
        source_ref=source_ref,
        content="First adjacent chunk.",
    )
    second = _ranked_chunk(
        2,
        document_id=document_id,
        source_key="docs-jobs",
        chunk_index=1,
        source_ref=source_ref,
        content="Second adjacent chunk.",
    )
    builder = KnowledgeContextBuilder()

    bundle = builder.build("jobs dependencies", (first, first, second))

    assert tuple(chunk.chunk_id for chunk in bundle.selected_chunks) == (
        first.chunk_id,
        second.chunk_id,
    )
    assert len(bundle.citations) == 1
    assert bundle.citations[0].chunk_id == first.chunk_id
    assert "First adjacent chunk." in bundle.context
    assert "Second adjacent chunk." in bundle.context
    assert bundle.context.count("[S1]") == 1


def test_context_applies_top_k_before_rendering() -> None:
    chunks = tuple(_ranked_chunk(value) for value in range(1, 5))
    builder = KnowledgeContextBuilder(top_k=2)

    bundle = builder.build("top k", chunks)

    assert tuple(chunk.chunk_id for chunk in bundle.selected_chunks) == (
        chunks[0].chunk_id,
        chunks[1].chunk_id,
    )
    assert tuple(citation.citation_id for citation in bundle.citations) == ("S1", "S2")


def test_context_skips_chunk_that_would_exceed_token_budget() -> None:
    first = _ranked_chunk(1, content="small first content")
    oversized = _ranked_chunk(2, content=" ".join(["oversized"] * 200))
    third = _ranked_chunk(3, content="small third content")
    builder = KnowledgeContextBuilder(
        top_k=3,
        max_context_tokens=80,
        token_counter=lambda value: len(value.split()),
    )

    bundle = builder.build("budget", (first, oversized, third))

    assert tuple(chunk.chunk_id for chunk in bundle.selected_chunks) == (
        first.chunk_id,
        third.chunk_id,
    )
    assert bundle.context_token_count <= 80
    assert "oversized" not in bundle.context


def test_context_has_stable_citations_metadata_and_untrusted_boundaries() -> None:
    first = _ranked_chunk(1)
    second = _ranked_chunk(2)
    builder = KnowledgeContextBuilder()

    bundle = builder.build("metadata", (first, second))

    assert tuple(citation.citation_id for citation in bundle.citations) == ("S1", "S2")
    assert tuple(citation.rank for citation in bundle.citations) == (1, 2)
    assert bundle.citations[0].title == first.title
    assert bundle.citations[0].url == first.source_ref
    assert bundle.citations[0].heading == "Lakeflow Jobs > Task dependencies"
    assert bundle.citations[0].chunk_hash == first.chunk_hash
    assert "【不可信资料开始】" in bundle.context
    assert "【不可信资料结束】" in bundle.context
    assert f"标题：{first.title}" in bundle.context
    assert f"URL：{first.source_ref}" in bundle.context
    assert "Heading：Lakeflow Jobs > Task dependencies" in bundle.context


def test_context_marks_catalog_link_as_unfetched_metadata() -> None:
    pricing_url = "https://www.databricks.com/product/pricing"
    pricing = _ranked_chunk(
        10,
        source_key="docs-external-pricing",
        heading_path=(),
        source_ref=pricing_url,
        content=(
            "资料类型：官方目录链接（未抓取目标正文）\n\n"
            "标题：Pricing\n\n"
            "目录摘要：Databricks pricing information.\n\n"
            f"官方链接：{pricing_url}"
        ),
        link_only=True,
    )

    bundle = KnowledgeContextBuilder().build("Databricks 最新价格在哪里查看？", (pricing,))

    assert "资料类型：官方目录链接（未抓取目标正文）" in bundle.context
    assert f"URL：{pricing_url}" in bundle.context
    assert bundle.citations[0].url == pricing_url
