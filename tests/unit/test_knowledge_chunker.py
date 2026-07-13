import re

import pytest
import tiktoken

from databricks_zh_expert.rag.chunker import ChunkingError, MarkdownChunker
from databricks_zh_expert.rag.types import (
    DiscoveredSource,
    KnowledgeCategory,
    NormalizedDocument,
    SourceKind,
)


def _document(content: str) -> NormalizedDocument:
    source = DiscoveredSource(
        source_key="docs-lakeflow-jobs",
        kind=SourceKind.GENERAL_HTML,
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/jobs/",
        category=KnowledgeCategory.ORCHESTRATION,
        catalog_id="databricks-docs",
        cloud="aws",
        locale="en",
        topic="Data engineering",
        summary="Official Databricks guidance.",
    )
    return NormalizedDocument(
        source=source,
        title="Lakeflow Jobs",
        canonical_url="https://docs.databricks.com/aws/en/jobs/",
        normalized_content=content,
        source_updated_at="2026-07-10T08:30:00Z",
        etag='"jobs-v1"',
        last_modified="Fri, 10 Jul 2026 08:30:00 GMT",
    )


def _paragraph(block_number: int) -> str:
    sentence = "Configure reliable workflow retries and task dependencies. "
    return f"Block-{block_number} " + sentence * 8


def test_regular_chunks_respect_token_limit_and_reuse_nearby_blocks() -> None:
    markdown = "# Lakeflow Jobs\n\n" + "\n\n".join(_paragraph(index) for index in range(24))
    chunker = MarkdownChunker(chunk_size_tokens=600, chunk_overlap_tokens=80)

    chunks = chunker.split(_document(markdown))

    assert len(chunks) >= 2
    assert all(chunk.token_count <= 600 for chunk in chunks)

    shared_blocks = []
    encoding = tiktoken.get_encoding("cl100k_base")
    overlap_token_counts = []
    for previous, current in zip(chunks, chunks[1:], strict=False):
        previous_ids = set(re.findall(r"Block-(\d+)", previous.content))
        current_ids = set(re.findall(r"Block-(\d+)", current.content))
        shared = previous_ids & current_ids
        shared_blocks.append(shared)
        if shared:
            overlap_text = "\n\n".join(_paragraph(int(value)) for value in sorted(shared, key=int))
            overlap_token_counts.append(len(encoding.encode(overlap_text)))
    assert any(shared for shared in shared_blocks)
    assert any(50 <= count <= 80 for count in overlap_token_counts)


def test_short_fence_table_and_list_remain_whole() -> None:
    markdown = """# Lakeflow Jobs

## Configure tasks

Intro text about task configuration and operational ownership.

```sql
SELECT job_id, run_id
FROM system.lakeflow.job_run_timeline
WHERE result_state = 'FAILED';
```

| Setting | Purpose |
| --- | --- |
| max_retries | Retry failed tasks |
| timeout_seconds | Stop stalled tasks |

- Use unique task keys.
- Confirm retry behavior.

Final guidance about monitoring and alerts.
"""
    chunks = MarkdownChunker(chunk_size_tokens=70, chunk_overlap_tokens=10).split(
        _document(markdown)
    )

    code = """```sql
SELECT job_id, run_id
FROM system.lakeflow.job_run_timeline
WHERE result_state = 'FAILED';
```"""
    table = """| Setting | Purpose |
| --- | --- |
| max_retries | Retry failed tasks |
| timeout_seconds | Stop stalled tasks |"""
    task_list = """- Use unique task keys.
- Confirm retry behavior."""

    assert sum(code in chunk.content for chunk in chunks) == 1
    assert sum(table in chunk.content for chunk in chunks) == 1
    assert sum(task_list in chunk.content for chunk in chunks) == 1


def test_oversized_fence_uses_bounded_closed_fence_fallback() -> None:
    code_lines = "\n".join(f'print("task-{index}")' for index in range(120))
    markdown = f"""# Lakeflow Jobs

## Long notebook

```python
{code_lines}
```
"""

    chunks = MarkdownChunker(chunk_size_tokens=80, chunk_overlap_tokens=10).split(
        _document(markdown)
    )
    code_chunks = [chunk for chunk in chunks if "```python" in chunk.content]

    assert 2 <= len(code_chunks) < 30
    assert all(chunk.token_count <= 80 for chunk in code_chunks)
    assert all(chunk.content.count("```python") == 1 for chunk in code_chunks)
    assert all(chunk.content.rstrip().endswith("```") for chunk in code_chunks)


def test_heading_path_source_ref_index_and_hash_are_deterministic() -> None:
    markdown = """# Lakeflow Jobs

Overview of reliable production workflows and operational ownership.

## Configure tasks

Task dependencies, retries, and timeouts should be explicit and reviewable.

### Retry policy

Use bounded retries with clear failure alerts and idempotent task behavior.
"""
    chunker = MarkdownChunker(chunk_size_tokens=120, chunk_overlap_tokens=20)
    document = _document(markdown)

    first = chunker.split(document)
    second = chunker.split(document)

    assert first == second
    assert tuple(chunk.chunk_index for chunk in first) == tuple(range(len(first)))
    assert {chunk.heading_path for chunk in first} == {
        ("Lakeflow Jobs",),
        ("Lakeflow Jobs", "Configure tasks"),
        ("Lakeflow Jobs", "Configure tasks", "Retry policy"),
    }
    retry_chunk = next(chunk for chunk in first if chunk.heading_path[-1] == "Retry policy")
    assert retry_chunk.source_ref.endswith("#retry-policy")
    assert re.fullmatch(r"[0-9a-f]{64}", retry_chunk.content_hash)


def test_empty_sections_do_not_create_chunks() -> None:
    markdown = """# Lakeflow Jobs

## Empty section

### Filled section

This section contains enough useful content to become one deterministic chunk.
"""

    chunks = MarkdownChunker(chunk_size_tokens=120, chunk_overlap_tokens=20).split(
        _document(markdown)
    )

    assert chunks
    assert all(chunk.heading_path != ("Lakeflow Jobs",) for chunk in chunks)
    assert all(chunk.heading_path != ("Lakeflow Jobs", "Empty section") for chunk in chunks)
    assert chunks[0].heading_path == (
        "Lakeflow Jobs",
        "Empty section",
        "Filled section",
    )


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (100, -1), (100, 100), (100, 101)],
)
def test_chunker_rejects_invalid_window_configuration(
    chunk_size: int,
    overlap: int,
) -> None:
    with pytest.raises(ChunkingError):
        MarkdownChunker(
            chunk_size_tokens=chunk_size,
            chunk_overlap_tokens=overlap,
        )


def test_reported_token_count_matches_cl100k_base() -> None:
    chunks = MarkdownChunker(chunk_size_tokens=120, chunk_overlap_tokens=20).split(
        _document("# Lakeflow Jobs\n\nUse a deterministic token encoding for every chunk.\n")
    )
    encoding = tiktoken.get_encoding("cl100k_base")

    assert chunks[0].token_count == len(encoding.encode(chunks[0].content))
