from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

import tiktoken

from databricks_zh_expert.expert_templates.constants import (
    EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS,
    EXPERT_TEMPLATE_TOP_K,
)
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName

SelectionReason = Literal["semantic", "default", "inherited"]
CandidateReason = Literal["semantic", "default"]


class ExpertTemplateContextNotFoundError(RuntimeError):
    code = "expert_template_context_not_found"


@dataclass(frozen=True, slots=True)
class ExpertTemplateDocument:
    record_id: UUID
    template_id: str
    version: str
    name: str
    summary: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: str
    profile_id: str | None
    cloud: str
    content_hash: str
    extends_record_id: UUID | None
    content: str
    source_path: str
    official_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankedExpertTemplateCandidate:
    chunk_id: UUID
    template_record_id: UUID
    template_id: str
    version: str
    name: str
    layer: str
    profile_id: str | None
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    content_hash: str
    extends_record_id: UUID | None
    matched_chunk_content: str
    vector_similarity: float | None
    lexical_score: float | None
    vector_rank: int | None
    lexical_rank: int | None
    fused_score: float
    reason: CandidateReason


@dataclass(frozen=True, slots=True)
class ExpertTemplateSelection:
    record_id: UUID
    template_id: str
    version: str
    name: str
    content_hash: str
    layer: str
    profile_id: str | None
    rank: int
    reason: SelectionReason
    extends: str | None


@dataclass(frozen=True, slots=True)
class ExpertTemplateRetrievalBundle:
    query: str
    profile_id: str
    prompt_name: PromptName
    ranked_candidates: tuple[RankedExpertTemplateCandidate, ...]
    selected_templates: tuple[ExpertTemplateSelection, ...]
    context: str
    context_token_count: int


@dataclass(frozen=True, slots=True)
class _SelectedDocument:
    document: ExpertTemplateDocument
    reason: SelectionReason


class ExpertTemplateContextBuilder:
    def __init__(
        self,
        *,
        top_k: int = EXPERT_TEMPLATE_TOP_K,
        max_context_tokens: int = EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("专家模板 top-k 必须是正整数。")
        if (
            isinstance(max_context_tokens, bool)
            or not isinstance(max_context_tokens, int)
            or max_context_tokens <= 0
        ):
            raise ValueError("专家模板上下文 token 预算必须是正整数。")
        self._top_k = top_k
        self._max_context_tokens = max_context_tokens
        if token_counter is None:
            encoding = tiktoken.get_encoding("cl100k_base")
            self._token_counter = lambda value: len(encoding.encode(value))
        else:
            self._token_counter = token_counter

    def build(
        self,
        query: str,
        *,
        profile_id: str,
        prompt_name: PromptName,
        ranked_candidates: Sequence[RankedExpertTemplateCandidate],
        documents: Mapping[UUID, ExpertTemplateDocument],
    ) -> ExpertTemplateRetrievalBundle:
        unique_candidates = _deduplicate_candidates(ranked_candidates)
        selected: list[_SelectedDocument] = []
        selected_ids: set[UUID] = set()
        context = ""
        context_token_count = 0
        major_count = 0

        for candidate in unique_candidates:
            if major_count >= self._top_k:
                break
            document = documents.get(candidate.template_record_id)
            if document is None:
                continue
            chain = _dependency_chain(document, documents)
            if chain is None:
                continue

            additions: list[_SelectedDocument] = []
            for dependency in chain[:-1]:
                if dependency.record_id not in selected_ids:
                    additions.append(_SelectedDocument(document=dependency, reason="inherited"))
            if document.record_id not in selected_ids:
                additions.append(_SelectedDocument(document=document, reason=candidate.reason))
            if not additions:
                continue

            proposed = (*selected, *additions)
            proposed_context = _render_context(proposed, documents)
            proposed_token_count = self._token_counter(proposed_context)
            if proposed_token_count > self._max_context_tokens:
                continue

            selected.extend(additions)
            selected_ids.update(item.document.record_id for item in additions)
            context = proposed_context
            context_token_count = proposed_token_count
            major_count += 1

        if not selected:
            raise ExpertTemplateContextNotFoundError("没有可放入 token 预算的专家模板上下文。")

        selections = tuple(
            replace(
                _to_selection(item, documents),
                rank=rank,
            )
            for rank, item in enumerate(selected, start=1)
        )
        return ExpertTemplateRetrievalBundle(
            query=query,
            profile_id=profile_id,
            prompt_name=prompt_name,
            ranked_candidates=unique_candidates,
            selected_templates=selections,
            context=context,
            context_token_count=context_token_count,
        )


def _deduplicate_candidates(
    candidates: Sequence[RankedExpertTemplateCandidate],
) -> tuple[RankedExpertTemplateCandidate, ...]:
    seen: set[UUID] = set()
    unique: list[RankedExpertTemplateCandidate] = []
    for candidate in candidates:
        if candidate.template_record_id in seen:
            continue
        seen.add(candidate.template_record_id)
        unique.append(candidate)
    return tuple(unique)


def _dependency_chain(
    document: ExpertTemplateDocument,
    documents: Mapping[UUID, ExpertTemplateDocument],
) -> tuple[ExpertTemplateDocument, ...] | None:
    chain: list[ExpertTemplateDocument] = []
    visiting: set[UUID] = set()
    current = document
    while True:
        if current.record_id in visiting:
            return None
        visiting.add(current.record_id)
        chain.append(current)
        if current.extends_record_id is None:
            break
        parent = documents.get(current.extends_record_id)
        if parent is None or parent.layer != "core":
            return None
        current = parent
    chain.reverse()
    return tuple(chain)


def _to_selection(
    selected: _SelectedDocument,
    documents: Mapping[UUID, ExpertTemplateDocument],
) -> ExpertTemplateSelection:
    document = selected.document
    parent = (
        documents.get(document.extends_record_id)
        if document.extends_record_id is not None
        else None
    )
    extends = f"{parent.template_id}@{parent.version}" if parent is not None else None
    return ExpertTemplateSelection(
        record_id=document.record_id,
        template_id=document.template_id,
        version=document.version,
        name=document.name,
        content_hash=document.content_hash,
        layer=document.layer,
        profile_id=document.profile_id,
        rank=0,
        reason=selected.reason,
        extends=extends,
    )


def _render_context(
    selected: Sequence[_SelectedDocument],
    documents: Mapping[UUID, ExpertTemplateDocument],
) -> str:
    blocks = []
    for index, item in enumerate(selected, start=1):
        document = item.document
        parent = (
            documents.get(document.extends_record_id)
            if document.extends_record_id is not None
            else None
        )
        extends = f"{parent.template_id}@{parent.version}" if parent is not None else "无"
        blocks.append(
            "\n".join(
                (
                    f"[T{index}]",
                    f"模板：{document.name}",
                    f"模板 ID：{document.template_id}@{document.version}",
                    f"层：{document.layer}",
                    f"选择原因：{item.reason}",
                    f"继承：{extends}",
                    "正文：",
                    document.content.strip(),
                )
            )
        )

    return "\n\n".join(
        (
            "以下内容是内部专家模板，是受信任的内部顾问参考，但只是默认建议。",
            "不得声称已经执行任何操作；不得覆盖用户明确的 SLA；"
            "与 Databricks 官方事实冲突时必须采用官方事实。",
            "信息优先级：\n"
            "1. 系统安全和产品边界\n"
            "2. 用户本轮明确要求\n"
            "3. Databricks 官方文档事实\n"
            "4. 项目覆盖层假设\n"
            "5. 通用模板默认建议",
            "【内部专家模板开始】",
            *blocks,
            "【内部专家模板结束】",
        )
    )
