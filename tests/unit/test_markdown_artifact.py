from collections.abc import Iterable

import pytest

from databricks_zh_expert.artifacts.markdown import (
    MAX_ARTIFACT_CHARS,
    MarkdownArtifactParser,
)
from databricks_zh_expert.artifacts.types import ArtifactValidationError
from databricks_zh_expert.prompts.registry import PROMPT_SPECS, PromptName, PromptSpec

SPECS = {spec.name: spec for spec in PROMPT_SPECS}
AVAILABLE_PROMPTS = tuple(spec.name for spec in PROMPT_SPECS if spec.available)


def build_document(
    spec: PromptSpec,
    sections: Iterable[str] | None = None,
    *,
    title: str = "测试交付物",
) -> str:
    section_names = tuple(sections) if sections is not None else spec.required_sections
    parts = [f"# {title}"]
    for section in section_names:
        parts.extend(("", f"## {section}", "内容"))
    return "\n".join(parts)


def get_violations(spec: PromptSpec, content: str) -> tuple[str, ...]:
    with pytest.raises(ArtifactValidationError) as caught:
        MarkdownArtifactParser().parse(spec, content)
    return caught.value.violations


@pytest.mark.parametrize("prompt_name", AVAILABLE_PROMPTS)
def test_parser_accepts_every_available_artifact(prompt_name: PromptName) -> None:
    spec = SPECS[prompt_name]
    if prompt_name is PromptName.SQL_GENERATION:
        content = "```sql\n-- 用途：测试\nSELECT 1;\n```"
        expected_title = "Databricks SQL"
    elif prompt_name is PromptName.PYSPARK_GENERATION:
        content = "```python\n# 用途：测试\nprint(1)\n```"
        expected_title = "PySpark"
    else:
        content = build_document(spec)
        expected_title = "测试交付物"

    artifact = MarkdownArtifactParser().parse(spec, content)

    assert artifact.artifact_type is spec.artifact_type
    assert artifact.title == expected_title
    assert artifact.content == content


def test_code_artifact_does_not_require_headings() -> None:
    content = "```sql\nSELECT current_date();\n```"

    artifact = MarkdownArtifactParser().parse(
        SPECS[PromptName.SQL_GENERATION],
        content,
    )

    assert artifact.title == "Databricks SQL"
    assert "#" not in artifact.content


def test_parser_normalizes_line_endings_and_outer_markdown_fence() -> None:
    content = "```markdown\r\n```sql\r\nSELECT 1;\r\n```\r\n```"

    artifact = MarkdownArtifactParser().parse(
        SPECS[PromptName.SQL_GENERATION],
        content,
    )

    assert artifact.content == "```sql\nSELECT 1;\n```"


def test_document_artifact_allows_additional_sections() -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = build_document(spec) + "\n\n## 补充信息\n内容"

    artifact = MarkdownArtifactParser().parse(spec, content)

    assert artifact.title == "测试交付物"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("", ("empty_content",)),
        ("x" * (MAX_ARTIFACT_CHARS + 1), ("content_too_long",)),
    ],
    ids=("empty", "too_long"),
)
def test_parser_rejects_invalid_content_length(
    content: str,
    expected: tuple[str, ...],
) -> None:
    assert get_violations(SPECS[PromptName.DATABRICKS_QA], content) == expected


def test_document_requires_h1_as_the_first_block() -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = f"说明文字\n\n{build_document(spec)}"

    assert "missing_h1" in get_violations(spec, content)


def test_document_rejects_multiple_h1_headings() -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = build_document(spec) + "\n\n# 第二个标题"

    assert get_violations(spec, content) == ("multiple_h1",)


def test_document_rejects_a_missing_section() -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = build_document(spec, spec.required_sections[:-1])

    assert get_violations(spec, content) == ("missing_section",)


def test_document_rejects_sections_in_the_wrong_order() -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = build_document(spec, reversed(spec.required_sections))

    assert get_violations(spec, content) == ("section_order_invalid",)


def test_code_fence_must_be_the_first_block() -> None:
    content = "先解释一段。\n\n```sql\nSELECT 1;\n```"

    assert get_violations(SPECS[PromptName.SQL_GENERATION], content) == ("code_fence_not_first",)


def test_sql_requires_an_sql_fence() -> None:
    content = "```python\nprint(1)\n```"

    assert get_violations(SPECS[PromptName.SQL_GENERATION], content) == (
        "code_fence_not_first",
        "missing_sql_fence",
    )


def test_pyspark_requires_a_python_fence() -> None:
    content = "```sql\nSELECT 1;\n```"

    assert get_violations(SPECS[PromptName.PYSPARK_GENERATION], content) == (
        "code_fence_not_first",
        "missing_python_fence",
    )


@pytest.mark.parametrize(
    "html",
    (
        "<div>不允许</div>",
        "段落中的 <span>HTML</span>",
    ),
)
def test_parser_rejects_raw_html(html: str) -> None:
    spec = SPECS[PromptName.DATABRICKS_QA]
    content = build_document(spec) + f"\n\n{html}"

    assert get_violations(spec, content) == ("raw_html_not_allowed",)
