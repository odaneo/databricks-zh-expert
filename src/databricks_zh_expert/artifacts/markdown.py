from collections.abc import Iterator, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token

from databricks_zh_expert.artifacts.types import (
    ArtifactValidationError,
    MarkdownArtifact,
)
from databricks_zh_expert.prompts.registry import PromptSpec

MAX_ARTIFACT_CHARS = 100_000


def normalize_markdown(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = normalized.splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().lower() in {"```markdown", "```md"}
        and lines[-1].strip() == "```"
    ):
        normalized = "\n".join(lines[1:-1]).strip()
    return normalized


def _walk_tokens(tokens: Sequence[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token
        if token.children:
            yield from _walk_tokens(token.children)


def _heading_texts(tokens: Sequence[Token], tag: str) -> list[str]:
    headings: list[str] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != tag:
            continue
        if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
            headings.append(tokens[index + 1].content.strip())
    return headings


def _fence_language(token: Token) -> str | None:
    if token.type != "fence":
        return None
    info = token.info.strip()
    if not info:
        return ""
    return info.split(maxsplit=1)[0].lower()


class MarkdownArtifactParser:
    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark")

    def parse(self, spec: PromptSpec, content: str) -> MarkdownArtifact:
        normalized = normalize_markdown(content)
        if not normalized:
            raise ArtifactValidationError(("empty_content",))
        if len(normalized) > MAX_ARTIFACT_CHARS:
            raise ArtifactValidationError(("content_too_long",))

        tokens = self._markdown.parse(normalized)
        violations: list[str] = []
        if any(token.type in {"html_block", "html_inline"} for token in _walk_tokens(tokens)):
            violations.append("raw_html_not_allowed")

        if spec.code_fence_language is not None:
            title = self._validate_code_artifact(spec, tokens, violations)
        else:
            title = self._validate_document_artifact(spec, tokens, violations)

        if violations:
            raise ArtifactValidationError(tuple(dict.fromkeys(violations)))
        return MarkdownArtifact(
            artifact_type=spec.artifact_type,
            title=title,
            content=normalized,
        )

    @staticmethod
    def _validate_code_artifact(
        spec: PromptSpec,
        tokens: Sequence[Token],
        violations: list[str],
    ) -> str:
        required_language = spec.code_fence_language
        if required_language is None:
            raise RuntimeError("代码型 Artifact 缺少代码语言配置。")

        first_language = _fence_language(tokens[0]) if tokens else None
        if first_language != required_language:
            violations.append("code_fence_not_first")

        has_required_fence = any(_fence_language(token) == required_language for token in tokens)
        if not has_required_fence:
            violations.append(
                "missing_sql_fence" if required_language == "sql" else "missing_python_fence"
            )
        return spec.display_name

    @staticmethod
    def _validate_document_artifact(
        spec: PromptSpec,
        tokens: Sequence[Token],
        violations: list[str],
    ) -> str:
        h1_headings = _heading_texts(tokens, "h1")
        first_is_h1 = bool(tokens and tokens[0].type == "heading_open" and tokens[0].tag == "h1")
        title = h1_headings[0] if h1_headings else ""
        if not first_is_h1 or not title:
            violations.append("missing_h1")
        if len(h1_headings) > 1:
            violations.append("multiple_h1")
        if title == "标题":
            violations.append("placeholder_title")

        h2_headings = _heading_texts(tokens, "h2")
        missing_sections = [
            section for section in spec.required_sections if section not in h2_headings
        ]
        if missing_sections:
            violations.append("missing_section")
        else:
            positions = [h2_headings.index(section) for section in spec.required_sections]
            if positions != sorted(positions):
                violations.append("section_order_invalid")
        return title
