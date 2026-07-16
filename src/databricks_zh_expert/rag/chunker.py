import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import tiktoken
from markdown_it import MarkdownIt

from databricks_zh_expert.rag.types import NormalizedDocument

_TOP_LEVEL_BLOCK_TYPES = frozenset(
    {
        "blockquote_open",
        "bullet_list_open",
        "code_block",
        "fence",
        "heading_open",
        "html_block",
        "hr",
        "ordered_list_open",
        "paragraph_open",
        "table_open",
    }
)


class ChunkingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    token_count: int
    source_ref: str


@dataclass(frozen=True, slots=True)
class _Heading:
    start_line: int
    body_start_line: int
    level: int
    title: str
    path: tuple[tuple[int, str], ...]
    anchor: str | None


@dataclass(frozen=True, slots=True)
class _Section:
    heading_levels: tuple[tuple[int, str], ...]
    body: str
    anchor: str | None

    @property
    def heading_path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self.heading_levels)


@dataclass(frozen=True, slots=True)
class _Block:
    text: str
    kind: str


class MarkdownChunker:
    def __init__(
        self,
        *,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
    ) -> None:
        if chunk_size_tokens <= 0:
            raise ChunkingError("Chunk token 上限必须大于 0。")
        if chunk_overlap_tokens < 0:
            raise ChunkingError("Chunk token 重叠不能小于 0。")
        if chunk_overlap_tokens >= chunk_size_tokens:
            raise ChunkingError("Chunk token 重叠必须小于 token 上限。")

        self._chunk_size_tokens = chunk_size_tokens
        self._chunk_overlap_tokens = chunk_overlap_tokens
        self._encoding = tiktoken.get_encoding("cl100k_base")
        self._markdown = MarkdownIt("commonmark").enable("table")

    def split(self, document: NormalizedDocument) -> tuple[KnowledgeChunk, ...]:
        sections = self._sections(document)
        chunks: list[KnowledgeChunk] = []
        for section in sections:
            prefix = self._heading_prefix(section.heading_levels)
            blocks = self._extract_blocks(section.body)
            if not blocks:
                continue
            expanded = self._expand_blocks(prefix, blocks)
            for content in self._pack_blocks(prefix, expanded):
                chunks.append(
                    KnowledgeChunk(
                        chunk_index=len(chunks),
                        heading_path=section.heading_path,
                        content=content,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        token_count=self._token_count(content),
                        source_ref=self._source_ref(document.canonical_url, section.anchor),
                    )
                )
        return tuple(chunks)

    def _sections(self, document: NormalizedDocument) -> tuple[_Section, ...]:
        content = document.normalized_content.replace("\r\n", "\n").replace("\r", "\n")
        lines = content.split("\n")
        tokens = self._markdown.parse(content)
        hierarchy: dict[int, str] = {}
        slug_counts: dict[str, int] = {}
        headings: list[_Heading] = []

        for index, token in enumerate(tokens):
            if token.type != "heading_open" or token.tag not in {"h1", "h2", "h3"}:
                continue
            if token.map is None or index + 1 >= len(tokens):
                continue
            title = tokens[index + 1].content.strip()
            if not title:
                continue
            level = int(token.tag[1])
            if level == 1:
                hierarchy = {1: title}
            else:
                if 1 not in hierarchy:
                    hierarchy[1] = document.title
                hierarchy = {
                    existing_level: existing_title
                    for existing_level, existing_title in hierarchy.items()
                    if existing_level < level
                }
                hierarchy[level] = title

            anchor = (
                document.heading_anchors[len(headings)]
                if len(headings) < len(document.heading_anchors)
                else None
            )
            if anchor is None:
                base_anchor = self._slug(title)
                if base_anchor:
                    occurrence = slug_counts.get(base_anchor, 0)
                    slug_counts[base_anchor] = occurrence + 1
                    anchor = base_anchor if occurrence == 0 else f"{base_anchor}-{occurrence}"
            headings.append(
                _Heading(
                    start_line=token.map[0],
                    body_start_line=token.map[1],
                    level=level,
                    title=title,
                    path=tuple(sorted(hierarchy.items())),
                    anchor=anchor,
                )
            )

        sections: list[_Section] = []
        first_heading_line = headings[0].start_line if headings else len(lines)
        preamble = "\n".join(lines[:first_heading_line]).strip()
        if preamble:
            sections.append(
                _Section(
                    heading_levels=((1, document.title),),
                    body=preamble,
                    anchor=None,
                )
            )

        for index, heading in enumerate(headings):
            end_line = headings[index + 1].start_line if index + 1 < len(headings) else len(lines)
            body = "\n".join(lines[heading.body_start_line : end_line]).strip()
            if body:
                sections.append(
                    _Section(
                        heading_levels=heading.path,
                        body=body,
                        anchor=heading.anchor,
                    )
                )
        return tuple(sections)

    def _extract_blocks(self, body: str) -> tuple[_Block, ...]:
        lines = body.split("\n")
        ranges: list[tuple[int, int, str]] = []
        seen: set[tuple[int, int]] = set()
        for token in self._markdown.parse(body):
            if token.level != 0 or token.map is None:
                continue
            if token.type not in _TOP_LEVEL_BLOCK_TYPES:
                continue
            start_line, end_line = token.map
            key = (start_line, end_line)
            if key in seen:
                continue
            seen.add(key)
            ranges.append((start_line, end_line, token.type))

        blocks = []
        for start_line, end_line, kind in sorted(ranges):
            text = "\n".join(lines[start_line:end_line]).strip()
            if text:
                blocks.append(_Block(text=text, kind=kind))
        if not blocks and body.strip():
            blocks.append(_Block(text=body.strip(), kind="text"))
        return tuple(blocks)

    def _expand_blocks(
        self,
        prefix: str,
        blocks: tuple[_Block, ...],
    ) -> tuple[_Block, ...]:
        if self._token_count(prefix) >= self._chunk_size_tokens:
            raise ChunkingError("标题路径已经达到 Chunk token 上限。")

        expanded: list[_Block] = []
        for block in blocks:
            if self._token_count(self._render(prefix, [block])) <= self._chunk_size_tokens:
                expanded.append(block)
                continue
            if block.kind == "fence":
                expanded.extend(self._split_fence(prefix, block))
            else:
                expanded.extend(self._split_text_block(prefix, block))
        return tuple(expanded)

    def _split_fence(self, prefix: str, block: _Block) -> tuple[_Block, ...]:
        lines = block.text.split("\n")
        opening_match = re.match(r"^\s*(`{3,}|~{3,}).*$", lines[0]) if lines else None
        if opening_match is None or len(lines) < 3:
            return self._split_text_block(prefix, block)
        marker = opening_match.group(1)
        closing_pattern = rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$"
        if re.match(closing_pattern, lines[-1]) is None:
            return self._split_text_block(prefix, block)

        opening = lines[0].rstrip()
        closing = lines[-1].strip()
        body = "\n".join(lines[1:-1])

        def wrap(fragment: str) -> str:
            return f"{opening}\n{fragment}\n{closing}"

        return self._split_token_window(prefix, body, block.kind, wrap)

    def _split_text_block(self, prefix: str, block: _Block) -> tuple[_Block, ...]:
        return self._split_token_window(prefix, block.text, block.kind, lambda value: value)

    def _split_token_window(
        self,
        prefix: str,
        text: str,
        kind: str,
        wrap: Callable[[str], str],
    ) -> tuple[_Block, ...]:
        tokens = self._encoding.encode(text)
        if not tokens:
            return ()

        prefix_budget = self._token_count(prefix) + 4
        window_size = self._chunk_size_tokens - prefix_budget
        if window_size <= 0:
            raise ChunkingError("标题路径没有为 Chunk 正文留下 token 空间。")

        fragments: list[_Block] = []
        cursor = 0
        while cursor < len(tokens):
            end = min(cursor + window_size, len(tokens))
            fragment = wrap(self._encoding.decode(tokens[cursor:end]))
            while (
                end > cursor
                and self._token_count(self._render(prefix, [_Block(fragment, kind)]))
                > self._chunk_size_tokens
            ):
                end -= 1
                fragment = wrap(self._encoding.decode(tokens[cursor:end]))
            if end <= cursor:
                raise ChunkingError("无法在 token 上限内切分知识正文。")
            fragments.append(_Block(text=fragment.strip(), kind=kind))
            if end == len(tokens):
                break
            overlap = min(self._chunk_overlap_tokens, end - cursor - 1)
            cursor = max(cursor + 1, end - overlap)
        return tuple(fragments)

    def _pack_blocks(self, prefix: str, blocks: tuple[_Block, ...]) -> tuple[str, ...]:
        packed: list[str] = []
        current: list[_Block] = []

        for block in blocks:
            candidate = [*current, block]
            if self._token_count(self._render(prefix, candidate)) <= self._chunk_size_tokens:
                current = candidate
                continue

            if not current:
                raise ChunkingError("知识结构块超过 Chunk token 上限。")
            packed.append(self._render(prefix, current))
            current = self._overlap_suffix(current)
            while current and (
                self._token_count(self._render(prefix, [*current, block])) > self._chunk_size_tokens
            ):
                current.pop(0)
            current.append(block)

        if current:
            packed.append(self._render(prefix, current))
        return tuple(packed)

    def _overlap_suffix(self, blocks: list[_Block]) -> list[_Block]:
        selected: list[_Block] = []
        for block in reversed(blocks):
            candidate = [block, *selected]
            if self._token_count(self._render_body(candidate)) > self._chunk_overlap_tokens:
                break
            selected = candidate
        return selected

    @staticmethod
    def _heading_prefix(heading_levels: tuple[tuple[int, str], ...]) -> str:
        return "\n".join(f"{'#' * level} {title}" for level, title in heading_levels)

    @staticmethod
    def _render(prefix: str, blocks: list[_Block]) -> str:
        body = MarkdownChunker._render_body(blocks)
        return f"{prefix}\n\n{body}".strip() + "\n"

    @staticmethod
    def _render_body(blocks: list[_Block]) -> str:
        return "\n\n".join(block.text.strip() for block in blocks if block.text.strip())

    def _token_count(self, content: str) -> int:
        return len(self._encoding.encode(content))

    @staticmethod
    def _slug(title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title).casefold()
        without_marks = "".join(
            character for character in normalized if not unicodedata.combining(character)
        )
        slug = re.sub(r"[^\w\s-]", "", without_marks).replace("_", "-")
        slug = re.sub(r"[-\s]+", "-", slug).strip("-")
        return quote(slug, safe="-")

    @staticmethod
    def _source_ref(canonical_url: str, anchor: str | None) -> str:
        return canonical_url if anchor is None else f"{canonical_url}#{anchor}"
