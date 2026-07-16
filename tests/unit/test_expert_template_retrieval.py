from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

import pytest

from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextNotFoundError,
    ExpertTemplateDocument,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateCandidate
from databricks_zh_expert.expert_templates.retrieval import ExpertTemplateRetriever
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _document(
    value: int,
    template_id: str,
    *,
    layer: str = "core",
    profile_id: str | None = None,
    extends_record_id: UUID | None = None,
) -> ExpertTemplateDocument:
    return ExpertTemplateDocument(
        record_id=_uuid(value),
        template_id=template_id,
        version="1.0.0",
        name=f"模板 {template_id}",
        summary=f"{template_id} 摘要",
        kind=ExpertTemplateKind.BLUEPRINT,
        category=ExpertTemplateCategory.WORKFLOW,
        layer=layer,
        profile_id=profile_id,
        cloud="aws" if profile_id else "neutral",
        content_hash=f"{value:064x}",
        extends_record_id=extends_record_id,
        content=f"# 模板 {template_id}\n\n{template_id} 的完整正文。\n",
        source_path=f"core/{template_id}.md",
        official_refs=(),
    )


def _candidate(
    value: int,
    document: ExpertTemplateDocument,
    *,
    chunk_index: int = 0,
    vector_similarity: float | None = None,
    lexical_score: float | None = None,
) -> ExpertTemplateCandidate:
    return ExpertTemplateCandidate(
        chunk_id=_uuid(1000 + value),
        template_record_id=document.record_id,
        template_id=document.template_id,
        version=document.version,
        name=document.name,
        layer=document.layer,
        profile_id=document.profile_id,
        cloud=document.cloud,
        kind=document.kind,
        category=document.category,
        chunk_index=chunk_index,
        content=f"命中 Chunk {value}",
        content_hash=document.content_hash,
        extends_record_id=document.extends_record_id,
        vector_similarity=vector_similarity,
        lexical_score=lexical_score,
    )


class FakeExpertTemplateRepository:
    def __init__(
        self,
        *,
        vector_candidates: tuple[ExpertTemplateCandidate, ...] = (),
        lexical_candidates: tuple[ExpertTemplateCandidate, ...] = (),
        documents: Sequence[ExpertTemplateDocument] = (),
    ) -> None:
        self.vector_candidates = vector_candidates
        self.lexical_candidates = lexical_candidates
        self.documents_by_record_id = {item.record_id: item for item in documents}
        self.documents_by_template_id = {item.template_id: item for item in documents}
        self.vector_calls: list[tuple[tuple[float, ...], str, PromptName, int]] = []
        self.lexical_calls: list[tuple[str, str, PromptName, int]] = []
        self.record_loads: list[tuple[UUID, ...]] = []
        self.template_loads: list[tuple[str, ...]] = []

    async def find_vector_candidates(
        self,
        query_embedding: Sequence[float],
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]:
        self.vector_calls.append((tuple(query_embedding), profile_id, prompt_name, limit))
        return self.vector_candidates

    async def find_lexical_candidates(
        self,
        query: str,
        *,
        profile_id: str,
        prompt_name: PromptName,
        limit: int,
    ) -> tuple[ExpertTemplateCandidate, ...]:
        self.lexical_calls.append((query, profile_id, prompt_name, limit))
        return self.lexical_candidates

    async def get_active_template_documents(
        self,
        record_ids: Sequence[UUID],
    ) -> tuple[ExpertTemplateDocument, ...]:
        values = tuple(record_ids)
        self.record_loads.append(values)
        return tuple(
            self.documents_by_record_id[value]
            for value in values
            if value in self.documents_by_record_id
        )

    async def get_active_template_documents_by_template_ids(
        self,
        template_ids: Sequence[str],
    ) -> tuple[ExpertTemplateDocument, ...]:
        values = tuple(template_ids)
        self.template_loads.append(values)
        return tuple(
            self.documents_by_template_id[value]
            for value in values
            if value in self.documents_by_template_id
        )


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


@pytest.mark.asyncio
async def test_retriever_aggregates_chunks_by_best_fused_template_candidate(
    registry: ExpertTemplateRegistry,
) -> None:
    document = _document(1, "workflow.lakeflow_jobs")
    vector_first = _candidate(1, document, chunk_index=0, vector_similarity=0.9)
    vector_second = _candidate(2, document, chunk_index=1, vector_similarity=0.8)
    lexical_second = replace(
        vector_second,
        vector_similarity=None,
        lexical_score=0.7,
    )
    repository = FakeExpertTemplateRepository(
        vector_candidates=(vector_first, vector_second),
        lexical_candidates=(lexical_second,),
        documents=(document,),
    )
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    bundle = await retriever.retrieve(
        "如何设计 Lakeflow 工作流？",
        query_embedding=(0.01,) * 1536,
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert len(bundle.ranked_candidates) == 1
    assert bundle.ranked_candidates[0].chunk_id == vector_second.chunk_id
    assert bundle.ranked_candidates[0].vector_rank == 2
    assert bundle.ranked_candidates[0].lexical_rank == 1
    assert tuple(item.template_id for item in bundle.selected_templates) == (document.template_id,)
    assert repository.vector_calls[0][1:] == (
        "generic",
        PromptName.WORKFLOW_DESIGN,
        20,
    )


@pytest.mark.asyncio
async def test_retail_overlay_loads_active_core_parent(
    registry: ExpertTemplateRegistry,
) -> None:
    parent = _document(1, "workflow.lakeflow_jobs")
    overlay = _document(
        2,
        "retail.workflow_dag",
        layer="retail_sales_demo",
        profile_id="retail_sales_demo",
        extends_record_id=parent.record_id,
    )
    vector = _candidate(1, overlay, vector_similarity=0.95)
    lexical = replace(vector, vector_similarity=None, lexical_score=0.8)
    repository = FakeExpertTemplateRepository(
        vector_candidates=(vector,),
        lexical_candidates=(lexical,),
        documents=(parent, overlay),
    )
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    bundle = await retriever.retrieve(
        "设计 AWS 零售销售工作流",
        query_embedding=(0.01,) * 1536,
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert [item.template_id for item in bundle.selected_templates][:2] == [
        "workflow.lakeflow_jobs",
        "retail.workflow_dag",
    ]
    assert bundle.selected_templates[0].reason == "inherited"
    assert bundle.selected_templates[1].reason == "semantic"
    assert parent.record_id in repository.record_loads[0]


@pytest.mark.asyncio
async def test_low_semantic_score_without_lexical_match_uses_profile_defaults(
    registry: ExpertTemplateRegistry,
) -> None:
    first = _document(1, "workflow.lakeflow_jobs")
    second = _document(2, "pipeline.lakeflow_sdp")
    low = _candidate(3, _document(3, "unrelated"), vector_similarity=0.29)
    repository = FakeExpertTemplateRepository(
        vector_candidates=(low,),
        documents=(first, second),
    )
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    bundle = await retriever.retrieve(
        "完全无关的工作流问题",
        query_embedding=(0.01,) * 1536,
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert tuple(item.template_id for item in bundle.selected_templates) == (
        "workflow.lakeflow_jobs",
        "pipeline.lakeflow_sdp",
    )
    assert all(item.reason == "default" for item in bundle.selected_templates)
    assert repository.template_loads == [("workflow.lakeflow_jobs", "pipeline.lakeflow_sdp")]


@pytest.mark.asyncio
async def test_missing_default_template_raises_stable_context_error(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository()
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    with pytest.raises(ExpertTemplateContextNotFoundError) as caught:
        await retriever.retrieve(
            "完全无关的问题",
            query_embedding=(0.01,) * 1536,
            profile_id="generic",
            prompt_name=PromptName.WORKFLOW_DESIGN,
        )

    assert caught.value.code == "expert_template_context_not_found"


@pytest.mark.asyncio
async def test_retriever_rejects_invalid_query_embedding_before_repository_call(
    registry: ExpertTemplateRegistry,
) -> None:
    repository = FakeExpertTemplateRepository()
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    with pytest.raises(ValueError, match="1536"):
        await retriever.retrieve(
            "设计工作流",
            query_embedding=(0.1,) * 8,
            profile_id="generic",
            prompt_name=PromptName.WORKFLOW_DESIGN,
        )

    assert repository.vector_calls == []


@pytest.mark.asyncio
async def test_lexical_match_can_rescue_low_vector_score(
    registry: ExpertTemplateRegistry,
) -> None:
    document = _document(1, "workflow.lakeflow_jobs")
    low = _candidate(1, document, vector_similarity=0.1)
    lexical = replace(low, vector_similarity=None, lexical_score=0.8)
    repository = FakeExpertTemplateRepository(
        vector_candidates=(low,),
        lexical_candidates=(lexical,),
        documents=(document,),
    )
    retriever = ExpertTemplateRetriever(repository=repository, registry=registry)

    bundle = await retriever.retrieve(
        "请解释 run_if",
        query_embedding=(0.01,) * 1536,
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert bundle.selected_templates[0].template_id == document.template_id
    assert repository.lexical_calls[0][0] == "run_if"
