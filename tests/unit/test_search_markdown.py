import re

import pytest

from databricks_zh_expert.search.markdown import (
    ChunkingError,
    MarkdownChunker,
    MarkdownSource,
)


def test_shared_markdown_chunker_is_deterministic() -> None:
    source = MarkdownSource(
        title="测试模板",
        source_ref="expert-template://test@1.0.0",
        content="# 测试模板\n\n## 适用场景\n\n正文。\n",
        heading_anchors=("test", "usage"),
    )
    chunker = MarkdownChunker(chunk_size_tokens=80, chunk_overlap_tokens=10)

    first = chunker.split(source)

    assert first == chunker.split(source)
    assert len(first) == 1
    assert first[0].chunk_index == 0
    assert first[0].heading_path == ("测试模板", "适用场景")
    assert first[0].source_ref == "expert-template://test@1.0.0#usage"
    assert re.fullmatch(r"[0-9a-f]{64}", first[0].content_hash)


def test_shared_markdown_chunker_preserves_closed_code_fences() -> None:
    code_lines = "\n".join(f'print("record-{index}")' for index in range(80))
    source = MarkdownSource(
        title="代码模板",
        source_ref="expert-template://code.test@1.0.0",
        content=f"# 代码模板\n\n## 代码\n\n```python\n{code_lines}\n```\n",
    )

    chunks = MarkdownChunker(chunk_size_tokens=70, chunk_overlap_tokens=10).split(source)

    assert len(chunks) >= 2
    assert all(chunk.token_count <= 70 for chunk in chunks)
    assert all(chunk.content.count("```python") == 1 for chunk in chunks)
    assert all(chunk.content.rstrip().endswith("```") for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (100, -1), (100, 100)],
)
def test_shared_markdown_chunker_rejects_invalid_windows(
    chunk_size: int,
    overlap: int,
) -> None:
    with pytest.raises(ChunkingError):
        MarkdownChunker(
            chunk_size_tokens=chunk_size,
            chunk_overlap_tokens=overlap,
        )
