import hashlib
import math
import re
import unicodedata
from collections import Counter
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
_TITLE_TERM_SPLIT_PATTERN: Final = re.compile(r"[/、与，：:\s]+")
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
_GENERIC_TITLE_TERMS: Final = frozenset(
    {
        "业务",
        "事实",
        "当前",
        "规则",
        "数据",
        "来源",
        "状态",
        "范围",
        "要求",
        "设计",
        "项目",
    }
)
_CONTEXT_HEADER: Final = (
    "以下内容仅来自用户提供的项目事实，不是 Databricks 官方文档。\n"
    "源 DDL 只证明源表、源字段、类型和约束；需求与规则只证明用户已经提供的业务事实。\n"
    "尚未存在的 Bronze、Silver、Gold、Mapping 和代码只能作为待确认提案生成。\n"
    "Agent 历史提案不会进入此上下文，也不得反向覆盖源 DDL、业务规则或项目需求。\n"
    "不得执行以下 SQL，不得声称提案已经部署或验证。"
)
_LEXICAL_SELECTION_LIMITS: Final = {
    purpose: (
        4
        if purpose
        in {
            WorkspaceContextPurpose.MAPPING,
            WorkspaceContextPurpose.PYSPARK,
        }
        else 3
    )
    for purpose in WorkspaceContextPurpose
}

SelectionReason = Literal["lexical", "fallback"]
_LEXICAL_SELECTION_REASON: Final[SelectionReason] = "lexical"
_FALLBACK_SELECTION_REASON: Final[SelectionReason] = "fallback"
_SEED_RELEVANCE_RATIO: Final = 0.6


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
        _FallbackSeed(WorkspaceSourceKind.DATA_PRODUCT, "共同事实边界"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC、去重与删除"),
        _FallbackSeed(WorkspaceSourceKind.ARCHITECTURE, "Bronze、Silver、Gold 分层原则"),
        _FallbackSeed(WorkspaceSourceKind.DATA_QUALITY, "源结构与摄取合同"),
    ),
    WorkspaceContextPurpose.MAPPING: (
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_SYSTEM, "数据范围"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "源数据粒度与业务键"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "金额、折扣、数量与运费"),
        _FallbackSeed(WorkspaceSourceKind.DATA_PRODUCT, "共同事实边界"),
        _FallbackSeed(WorkspaceSourceKind.GOVERNANCE, "数据分类与敏感字段"),
    ),
    WorkspaceContextPurpose.SQL: (
        _FallbackSeed(WorkspaceSourceKind.DATA_PRODUCT, "跨产品公共维度与指标"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "金额、折扣、数量与运费"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.DATA_QUALITY, "金额计算与数值精度"),
        _FallbackSeed(WorkspaceSourceKind.GLOSSARY, "净销售额"),
    ),
    WorkspaceContextPurpose.PYSPARK: (
        _FallbackSeed(WorkspaceSourceKind.ARCHITECTURE, "Auto Loader 摄取要求"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC、去重与删除"),
        _FallbackSeed(WorkspaceSourceKind.DATA_QUALITY, "CDC、重复与顺序异常"),
        _FallbackSeed(WorkspaceSourceKind.GOVERNANCE, "重跑、补数与故障恢复"),
    ),
    WorkspaceContextPurpose.NOTEBOOK: (
        _FallbackSeed(WorkspaceSourceKind.ARCHITECTURE, "Auto Loader 摄取要求"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
        _FallbackSeed(WorkspaceSourceKind.RULE, "日期、事件时间与迟到数据"),
        _FallbackSeed(WorkspaceSourceKind.DATA_QUALITY, "质量结果与审计"),
        _FallbackSeed(WorkspaceSourceKind.GOVERNANCE, "监控、告警与升级路径"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC、去重与删除"),
    ),
    WorkspaceContextPurpose.WORKFLOW: (
        _FallbackSeed(WorkspaceSourceKind.REQUIREMENT, "业务目标"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_SYSTEM, "更新与抽取方式"),
        _FallbackSeed(WorkspaceSourceKind.ARCHITECTURE, "当前架构决定"),
        _FallbackSeed(WorkspaceSourceKind.DATA_PRODUCT, "产品组合总览"),
        _FallbackSeed(WorkspaceSourceKind.DATA_QUALITY, "发布门禁"),
        _FallbackSeed(WorkspaceSourceKind.GOVERNANCE, "调度、SLA 与 Owner"),
        _FallbackSeed(WorkspaceSourceKind.RULE, "CDC、去重与删除"),
        _FallbackSeed(WorkspaceSourceKind.SOURCE_DDL),
    ),
}
_FALLBACK_KIND_ORDER: Final = {
    purpose: tuple(
        dict.fromkeys(
            (
                *(seed.kind for seed in seeds),
                *tuple(WorkspaceSourceKind),
            )
        )
    )
    for purpose, seeds in _FALLBACK_SEEDS.items()
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
            planned = _build_positive_plan(
                positive_units,
                ranked_by_id=ranked_by_id,
                units=units,
                purpose=purpose,
            )
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
    parent_title: str | None = None
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open" or token.tag not in {"h2", "h3"} or token.map is None:
            continue
        inline = tokens[index + 1]
        if inline.type != "inline":
            continue
        title = inline.content.strip()
        if token.tag == "h2":
            parent_title = title
            unit_title = title
        elif parent_title is not None:
            unit_title = f"{parent_title} / {title}"
        else:
            continue
        sections.append((token.map[0], unit_title))

    units: list[WorkspaceContextUnit] = []
    for index, (start, title) in enumerate(sections):
        end = sections[index + 1][0] if index + 1 < len(sections) else len(lines)
        content = _normalize_unit_content("\n".join(lines[start:end]))
        if not any(line.strip() for line in content.splitlines()[1:]):
            continue
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
    document_terms = {
        unit.unit_id: (
            _identifiers(_normalize_text(f"{unit.title} {unit.content}")),
            _cjk_bigrams(_normalize_text(f"{unit.title} {unit.content}")),
        )
        for unit in units
    }
    identifier_document_frequency = Counter(
        token for identifiers, _ in document_terms.values() for token in identifiers
    )
    bigram_document_frequency = Counter(
        token for _, bigrams in document_terms.values() for token in bigrams
    )
    weighted_lengths = {
        unit_id: len(identifiers) * 3 + len(bigrams)
        for unit_id, (identifiers, bigrams) in document_terms.items()
    }
    average_length = (
        sum(weighted_lengths.values()) / len(weighted_lengths) if weighted_lengths else 1.0
    )
    query_identifiers = _identifiers(normalized_query)
    query_bigrams = _cjk_bigrams(normalized_query)
    scored = sorted(
        (
            (
                unit,
                _lexical_score(
                    normalized_query,
                    unit,
                    query_identifiers=query_identifiers,
                    query_bigrams=query_bigrams,
                    document_identifiers=document_terms[unit.unit_id][0],
                    document_bigrams=document_terms[unit.unit_id][1],
                    identifier_document_frequency=identifier_document_frequency,
                    bigram_document_frequency=bigram_document_frequency,
                    document_count=len(units),
                    weighted_length=weighted_lengths[unit.unit_id],
                    average_length=average_length,
                ),
            )
            for unit in units
        ),
        key=lambda item: (-item[1], item[0].source_id, item[0].order),
    )
    return tuple(
        _ScoredUnit(unit=unit, score=score, candidate_rank=rank)
        for rank, (unit, score) in enumerate(scored, start=1)
    )


def _lexical_score(
    normalized_query: str,
    unit: WorkspaceContextUnit,
    *,
    query_identifiers: frozenset[str],
    query_bigrams: frozenset[str],
    document_identifiers: frozenset[str],
    document_bigrams: frozenset[str],
    identifier_document_frequency: Counter[str],
    bigram_document_frequency: Counter[str],
    document_count: int,
    weighted_length: int,
    average_length: float,
) -> float:
    if not normalized_query:
        return 0.0
    normalized_content = _normalize_text(unit.content)
    score = 0.0

    query_tables = frozenset(
        table_name
        for item in query_identifiers
        if "." in item
        for table_name in (item.rsplit(".", maxsplit=1)[0], item.split(".")[-2])
    )
    content_tables = frozenset(
        match.casefold() for match in _CREATE_TABLE_PATTERN.findall(normalized_content)
    )
    score += 100 * len(query_tables & content_tables)
    score += 100 * len(query_identifiers & content_tables)

    source_id = _normalize_text(unit.source_id)
    file_stem = unit.source_path.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=1)[0]
    if source_id and source_id in normalized_query:
        score += 60
    if file_stem and _normalize_text(file_stem) in normalized_query:
        score += 40
    normalized_title = _normalize_text(unit.title)
    if normalized_title and normalized_title in normalized_query:
        score += 80
    title_parts = frozenset(
        _normalize_text(part) for part in unit.title.split("/") if _normalize_text(part)
    )
    score += 45 * sum(part in normalized_query for part in title_parts)
    title_terms = frozenset(
        normalized
        for term in _TITLE_TERM_SPLIT_PATTERN.split(unit.title)
        if len(term) >= 2 and term not in _GENERIC_TITLE_TERMS
        for normalized in (_normalize_text(term),)
        if normalized
    )
    score += 20 * sum(term in normalized_query for term in title_terms)

    meaningful_identifiers = {
        item for item in query_identifiers if item not in _GENERIC_IDENTIFIERS
    }
    lexical_score = sum(
        _inverse_document_frequency(document_count, identifier_document_frequency[token]) * 8
        for token in meaningful_identifiers & document_identifiers
    )
    lexical_score += sum(
        _inverse_document_frequency(document_count, bigram_document_frequency[token])
        for token in query_bigrams & document_bigrams
    )
    length_normalization = 1.0 / (0.35 + 0.65 * weighted_length / max(average_length, 1.0))
    score += lexical_score * min(2.5, length_normalization)
    return round(score, 6)


def _inverse_document_frequency(document_count: int, document_frequency: int) -> float:
    return math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))


def _build_positive_plan(
    positive_units: tuple[_ScoredUnit, ...],
    *,
    ranked_by_id: dict[str, _ScoredUnit],
    units: tuple[WorkspaceContextUnit, ...],
    purpose: WorkspaceContextPurpose,
) -> tuple[tuple[_ScoredUnit, SelectionReason], ...]:
    planned: list[tuple[_ScoredUnit, SelectionReason]] = []
    selected_ids: set[str] = set()
    selected_source_ids: set[str] = set()

    for item in positive_units:
        if (
            item.unit.kind is not WorkspaceSourceKind.SOURCE_DDL
            and item.unit.source_id in selected_source_ids
        ):
            continue
        planned.append((item, _LEXICAL_SELECTION_REASON))
        selected_ids.add(item.unit.unit_id)
        selected_source_ids.add(item.unit.source_id)
        if len(planned) >= _LEXICAL_SELECTION_LIMITS[purpose]:
            break

    required_kind_counts: Counter[WorkspaceSourceKind] = Counter()
    selected_kind_counts = Counter(item.unit.kind for item, _ in planned)
    fallback_by_id = {unit.unit_id: unit for unit in _fallback_units(units, purpose)}
    for seed in _FALLBACK_SEEDS[purpose]:
        required_kind_counts[seed.kind] += 1
        if selected_kind_counts[seed.kind] >= required_kind_counts[seed.kind]:
            continue
        best_kind_match = next(
            (
                item
                for item in positive_units
                if item.unit.kind is seed.kind and item.unit.unit_id not in selected_ids
            ),
            None,
        )
        seed_match = next(
            (
                item
                for item in positive_units
                if _matches_fallback_seed(item.unit, seed) and item.unit.unit_id not in selected_ids
            ),
            None,
        )
        match = best_kind_match
        if seed_match is not None and (
            required_kind_counts[seed.kind] > 1
            or best_kind_match is None
            or seed_match.score >= best_kind_match.score * _SEED_RELEVANCE_RATIO
        ):
            match = seed_match
        reason = _LEXICAL_SELECTION_REASON
        if match is None:
            fallback = next(
                (
                    unit
                    for unit in fallback_by_id.values()
                    if unit.kind is seed.kind
                    and (seed.title is None or unit.title == seed.title)
                    and unit.unit_id not in selected_ids
                ),
                None,
            )
            if fallback is not None:
                match = ranked_by_id[fallback.unit_id]
                reason = _FALLBACK_SELECTION_REASON
        if match is None:
            continue
        planned.append((match, reason))
        selected_ids.add(match.unit.unit_id)
        selected_kind_counts[match.unit.kind] += 1

    planned.extend(
        (item, _LEXICAL_SELECTION_REASON)
        for item in positive_units
        if item.unit.unit_id not in selected_ids
    )
    selected_ids.update(item.unit.unit_id for item in positive_units)
    planned.extend(
        (ranked_by_id[unit.unit_id], _FALLBACK_SELECTION_REASON)
        for unit in fallback_by_id.values()
        if unit.unit_id not in selected_ids
    )
    return tuple(planned)


def _matches_fallback_seed(unit: WorkspaceContextUnit, seed: _FallbackSeed) -> bool:
    if unit.kind is not seed.kind:
        return False
    if seed.title is None:
        return True
    return unit.title == seed.title or unit.title.startswith(f"{seed.title} /")


def _fallback_units(
    units: tuple[WorkspaceContextUnit, ...],
    purpose: WorkspaceContextPurpose,
) -> tuple[WorkspaceContextUnit, ...]:
    selected: list[WorkspaceContextUnit] = []
    selected_ids: set[str] = set()
    for seed in _FALLBACK_SEEDS[purpose]:
        match = next(
            (unit for unit in units if _matches_fallback_seed(unit, seed)),
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
