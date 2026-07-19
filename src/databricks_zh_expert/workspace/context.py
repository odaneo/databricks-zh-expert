import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

import sqlparse
import tiktoken
from markdown_it import MarkdownIt

from databricks_zh_expert.workspace.constants import (
    WORKSPACE_CONTEXT_MAX_TOKENS,
    WORKSPACE_CONTEXT_TOP_K,
)
from databricks_zh_expert.workspace.types import (
    WorkspaceContextBundle,
    WorkspaceContextCandidate,
    WorkspaceContextPurpose,
    WorkspaceContextSelection,
    WorkspaceContextUnit,
    WorkspaceDefinition,
    WorkspaceSource,
    WorkspaceSourceKind,
)

_WHITESPACE_PATTERN: Final = re.compile(r"\s+")
_ASCII_IDENTIFIER_PATTERN: Final = re.compile(
    r"(?<![a-z0-9_])[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*(?![a-z0-9_])",
    re.IGNORECASE,
)
_CREATE_TABLE_PATTERN: Final = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)",
    re.IGNORECASE,
)
_CJK_SEQUENCE_PATTERN: Final = re.compile(r"[\u3400-\u9fff]{2,}")
_GENERIC_IDENTIFIERS: Final = frozenset(
    {
        "agent",
        "create",
        "databricks",
        "ddl",
        "generate",
        "mapping",
        "notebook",
        "pyspark",
        "select",
        "source",
        "sql",
        "string",
        "table",
    }
)
_CONTEXT_HEADER: Final = (
    "以下内容仅来自用户提供的全新项目事实，不是 Databricks 官方文档。\n"
    "源 DDL 只证明源表、源字段、类型和约束；需求与规则只证明用户已经提供的业务事实。\n"
    "尚未存在的 Bronze、Silver、Gold、Mapping 和代码只能作为待确认提案生成。\n"
    "Agent 历史提案不会进入此上下文，也不得反向覆盖源 DDL、业务规则或项目需求。\n"
    "不得执行以下 SQL，不得声称提案已经部署或验证。"
)

SelectionReason = Literal["lexical", "fallback"]
_LEXICAL_SELECTION_REASON: Final[SelectionReason] = "lexical"
_FALLBACK_SELECTION_REASON: Final[SelectionReason] = "fallback"


class WorkspaceContextNotFoundError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ScoredUnit:
    unit: WorkspaceContextUnit
    score: float
    candidate_rank: int


@dataclass(frozen=True, slots=True)
class _FallbackSeed:
    kind: WorkspaceSourceKind
    title: str | None = None


_FALLBACK_SEEDS: Final = {
    WorkspaceContextPurpose.DDL: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "期望数据产品"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "源数据粒度与业务键"),
    ),
    WorkspaceContextPurpose.MAPPING: (
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "源数据粒度与业务键"),
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "期望数据产品"),
    ),
    WorkspaceContextPurpose.SQL: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "期望数据产品"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "指标口径"),
    ),
    WorkspaceContextPurpose.PYSPARK: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "摄取需求"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC 与去重"),
    ),
    WorkspaceContextPurpose.NOTEBOOK: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "摄取需求"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "事件时间与迟到数据"),
    ),
    WorkspaceContextPurpose.WORKFLOW: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "业务目标"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "源数据粒度与业务键"),
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "期望数据产品"),
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "摄取需求"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC 与去重"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "事件时间与迟到数据"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "指标口径"),
    ),
}
_FALLBACK_KIND_ORDER: Final = {
    WorkspaceContextPurpose.DDL: (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    ),
    WorkspaceContextPurpose.MAPPING: (
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
        WorkspaceSourceKind.REQUIREMENT,
    ),
    WorkspaceContextPurpose.SQL: (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    ),
    WorkspaceContextPurpose.PYSPARK: (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    ),
    WorkspaceContextPurpose.NOTEBOOK: (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    ),
    WorkspaceContextPurpose.WORKFLOW: (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    ),
}


class WorkspaceContextBuilder:
    def __init__(
        self,
        *,
        top_k: int = WORKSPACE_CONTEXT_TOP_K,
        max_context_tokens: int = WORKSPACE_CONTEXT_MAX_TOKENS,
    ) -> None:
        if top_k < 1:
            raise ValueError("Workspace Context top_k 必须大于零。")
        if top_k > WORKSPACE_CONTEXT_TOP_K:
            raise ValueError(f"Workspace Context top_k 不能超过 {WORKSPACE_CONTEXT_TOP_K}。")
        if max_context_tokens < 1:
            raise ValueError("Workspace Context token 预算必须大于零。")
        if max_context_tokens > WORKSPACE_CONTEXT_MAX_TOKENS:
            raise ValueError(
                f"Workspace Context token 预算不能超过 {WORKSPACE_CONTEXT_MAX_TOKENS}。"
            )
        self._top_k = top_k
        self._max_context_tokens = max_context_tokens
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def build_units(self, workspace: WorkspaceDefinition) -> tuple[WorkspaceContextUnit, ...]:
        units: list[WorkspaceContextUnit] = []
        for source in sorted(workspace.sources, key=lambda item: item.source_id):
            if source.kind is WorkspaceSourceKind.SOURCE_DDL:
                units.extend(_split_sql_source(source))
            else:
                units.extend(_split_markdown_source(source))
        return tuple(units)

    def build_for_prompt(
        self,
        query: str,
        *,
        workspace: WorkspaceDefinition,
        prompt_name: str,
    ) -> WorkspaceContextBundle | None:
        try:
            purpose = WorkspaceContextPurpose(prompt_name)
        except ValueError:
            return None
        return self.build(query, workspace=workspace, purpose=purpose)

    def build(
        self,
        query: str,
        *,
        workspace: WorkspaceDefinition,
        purpose: WorkspaceContextPurpose,
    ) -> WorkspaceContextBundle:
        units = self.build_units(workspace)
        if not units:
            raise WorkspaceContextNotFoundError("项目工作区没有可用的事实单元。")

        normalized_query = _normalize_text(query)
        ranked_units = _rank_units(normalized_query, units)
        positive_units = tuple(item for item in ranked_units if item.score > 0)
        ranked_by_id = {item.unit.unit_id: item for item in ranked_units}
        planned: tuple[tuple[_ScoredUnit, SelectionReason], ...]
        if positive_units:
            lexical_plan: tuple[tuple[_ScoredUnit, SelectionReason], ...] = tuple(
                (item, _LEXICAL_SELECTION_REASON) for item in positive_units
            )
            if purpose is WorkspaceContextPurpose.WORKFLOW:
                positive_ids = {item.unit.unit_id for item in positive_units}
                fallback_plan: tuple[tuple[_ScoredUnit, SelectionReason], ...] = tuple(
                    (ranked_by_id[unit.unit_id], _FALLBACK_SELECTION_REASON)
                    for unit in _fallback_units(units, purpose)
                    if unit.unit_id not in positive_ids
                )
                planned = (*lexical_plan, *fallback_plan)
            else:
                planned = lexical_plan
        else:
            fallback_units = _fallback_units(units, purpose)
            planned = tuple(
                (ranked_by_id[unit.unit_id], _FALLBACK_SELECTION_REASON) for unit in fallback_units
            )

        selected, context, context_token_count = self._fit_units(planned)
        selected_ids = frozenset(item.unit.unit_id for item, _ in selected)
        candidates = tuple(
            WorkspaceContextCandidate(
                rank=item.candidate_rank,
                unit_id=item.unit.unit_id,
                source_id=item.unit.source_id,
                kind=item.unit.kind,
                source_path=item.unit.source_path,
                content_hash=item.unit.content_hash,
                score=item.score,
                selected=item.unit.unit_id in selected_ids,
            )
            for item in ranked_units
        )
        selections = tuple(
            WorkspaceContextSelection(
                unit_id=item.unit.unit_id,
                source_id=item.unit.source_id,
                kind=item.unit.kind,
                source_path=item.unit.source_path,
                content_hash=item.unit.content_hash,
                rank=rank,
                reason=reason,
            )
            for rank, (item, reason) in enumerate(selected, start=1)
        )
        return WorkspaceContextBundle(
            workspace_id=workspace.workspace_id,
            workspace_version=workspace.version,
            workspace_source_hash=workspace.source_hash,
            query=query.strip(),
            purpose=purpose,
            ranked_candidates=candidates,
            selected_units=selections,
            context=context,
            context_token_count=context_token_count,
        )

    def _fit_units(
        self,
        planned: tuple[tuple[_ScoredUnit, SelectionReason], ...],
    ) -> tuple[tuple[tuple[_ScoredUnit, SelectionReason], ...], str, int]:
        if self._token_count(_CONTEXT_HEADER) > self._max_context_tokens:
            raise WorkspaceContextNotFoundError("Workspace Context 头部超过 token 预算。")

        selected: list[tuple[_ScoredUnit, SelectionReason]] = []
        blocks: list[str] = []
        for item, reason in planned:
            if len(selected) >= self._top_k:
                break
            block = _render_block(item.unit, rank=len(selected) + 1)
            proposed_context = _render_context((*blocks, block))
            if self._token_count(proposed_context) > self._max_context_tokens:
                continue
            selected.append((item, reason))
            blocks.append(block)

        if not selected:
            raise WorkspaceContextNotFoundError(
                "没有完整 Workspace Context 单元能进入 token 预算。"
            )
        context = _render_context(tuple(blocks))
        return tuple(selected), context, self._token_count(context)

    def _token_count(self, content: str) -> int:
        return len(self._encoding.encode(content, disallowed_special=()))


def _split_markdown_source(source: WorkspaceSource) -> tuple[WorkspaceContextUnit, ...]:
    lines = source.content.splitlines()
    tokens = MarkdownIt("commonmark").parse(source.content)
    sections: list[tuple[int, str]] = []
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open" or token.tag != "h2" or token.map is None:
            continue
        inline = tokens[index + 1]
        if inline.type == "inline":
            sections.append((token.map[0], inline.content.strip()))

    units: list[WorkspaceContextUnit] = []
    for index, (start, title) in enumerate(sections):
        end = sections[index + 1][0] if index + 1 < len(sections) else len(lines)
        content = _normalize_unit_content("\n".join(lines[start:end]))
        units.append(_make_unit(source, order=index + 1, title=title, content=content))
    return tuple(units)


def _split_sql_source(source: WorkspaceSource) -> tuple[WorkspaceContextUnit, ...]:
    units: list[WorkspaceContextUnit] = []
    for index, statement in enumerate(sqlparse.split(source.content), start=1):
        content = _normalize_unit_content(statement)
        table_match = _CREATE_TABLE_PATTERN.search(content)
        title = table_match.group(1) if table_match else f"SQL 语句 {index}"
        units.append(_make_unit(source, order=index, title=title, content=content))
    return tuple(units)


def _make_unit(
    source: WorkspaceSource,
    *,
    order: int,
    title: str,
    content: str,
) -> WorkspaceContextUnit:
    return WorkspaceContextUnit(
        unit_id=f"{source.source_id}:{order}",
        source_id=source.source_id,
        kind=source.kind,
        dialect=source.dialect,
        source_path=source.source_path,
        title=title,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        order=order,
    )


def _rank_units(
    normalized_query: str,
    units: tuple[WorkspaceContextUnit, ...],
) -> tuple[_ScoredUnit, ...]:
    scored = sorted(
        ((unit, _lexical_score(normalized_query, unit)) for unit in units),
        key=lambda item: (-item[1], item[0].source_id, item[0].order),
    )
    return tuple(
        _ScoredUnit(unit=unit, score=score, candidate_rank=rank)
        for rank, (unit, score) in enumerate(scored, start=1)
    )


def _lexical_score(normalized_query: str, unit: WorkspaceContextUnit) -> float:
    if not normalized_query:
        return 0.0
    normalized_content = _normalize_text(unit.content)
    normalized_metadata = _normalize_text(f"{unit.source_id} {unit.source_path} {unit.title}")
    score = 0

    query_identifiers = _identifiers(normalized_query)
    content_identifiers = _identifiers(normalized_content)
    query_tables = frozenset(item for item in query_identifiers if "." in item)
    content_tables = frozenset(
        match.casefold() for match in _CREATE_TABLE_PATTERN.findall(normalized_content)
    )
    score += 100 * len(query_tables & content_tables)

    source_id = _normalize_text(unit.source_id)
    file_stem = unit.source_path.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=1)[0]
    if source_id and source_id in normalized_query:
        score += 60
    if file_stem and _normalize_text(file_stem) in normalized_query:
        score += 40
    normalized_title = _normalize_text(unit.title)
    if normalized_title and normalized_title in normalized_query:
        score += 40

    meaningful_identifiers = {
        item for item in query_identifiers if item not in _GENERIC_IDENTIFIERS
    }
    score += min(60, 12 * len(meaningful_identifiers & content_identifiers))

    query_bigrams = _cjk_bigrams(normalized_query)
    content_bigrams = _cjk_bigrams(f"{normalized_metadata} {normalized_content}")
    score += min(20, 2 * len(query_bigrams & content_bigrams))
    return float(score)


def _fallback_units(
    units: tuple[WorkspaceContextUnit, ...],
    purpose: WorkspaceContextPurpose,
) -> tuple[WorkspaceContextUnit, ...]:
    selected: list[WorkspaceContextUnit] = []
    selected_ids: set[str] = set()
    for seed in _FALLBACK_SEEDS[purpose]:
        match = next(
            (
                unit
                for unit in units
                if unit.kind is seed.kind and (seed.title is None or unit.title == seed.title)
            ),
            None,
        )
        if match is not None and match.unit_id not in selected_ids:
            selected.append(match)
            selected_ids.add(match.unit_id)

    kind_order = _FALLBACK_KIND_ORDER[purpose]
    kind_rank = {kind: rank for rank, kind in enumerate(kind_order)}
    remaining = sorted(
        (unit for unit in units if unit.unit_id not in selected_ids),
        key=lambda unit: (kind_rank[unit.kind], unit.source_id, unit.order),
    )
    selected.extend(remaining)
    return tuple(selected)


def _identifiers(content: str) -> frozenset[str]:
    return frozenset(match.casefold() for match in _ASCII_IDENTIFIER_PATTERN.findall(content))


def _cjk_bigrams(content: str) -> frozenset[str]:
    bigrams: set[str] = set()
    for sequence in _CJK_SEQUENCE_PATTERN.findall(content):
        bigrams.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return frozenset(bigrams)


def _normalize_text(content: str) -> str:
    normalized = unicodedata.normalize("NFKC", content).casefold()
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()


def _normalize_unit_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip("\n") + "\n"


def _render_block(unit: WorkspaceContextUnit, *, rank: int) -> str:
    dialect = unit.dialect or "markdown"
    return (
        f"[P{rank}]\n"
        f"Unit ID：{unit.unit_id}\n"
        f"Source ID：{unit.source_id}\n"
        f"类型：{unit.kind.value}\n"
        f"方言：{dialect}\n"
        f"标题：{unit.title}\n"
        f"输入包相对路径：{unit.source_path}\n"
        f"内容 Hash：{unit.content_hash}\n"
        f"正文：\n{unit.content}"
    )


def _render_context(blocks: tuple[str, ...]) -> str:
    if not blocks:
        return _CONTEXT_HEADER
    return f"{_CONTEXT_HEADER}\n\n{'\n'.join(blocks)}"
