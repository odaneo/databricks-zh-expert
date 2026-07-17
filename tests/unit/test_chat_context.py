from collections.abc import Sequence

import pytest

from databricks_zh_expert.chat.context import ChatContextService
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextNotFoundError,
    ExpertTemplateRetrievalBundle,
)
from databricks_zh_expert.expert_templates.types import ExpertTemplateIndexStatus
from databricks_zh_expert.prompts.registry import PromptName, PromptRegistry
from databricks_zh_expert.rag.context import RetrievalBundle
from databricks_zh_expert.rag.embeddings import (
    EmbeddingRequestError,
    EmbeddingResult,
)
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus


class FakeEmbeddingClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.queries: list[str] = []
        self.embedding = (0.01,) * 1536

    async def embed_query(self, text: str) -> EmbeddingResult:
        self.queries.append(text)
        if self.error is not None:
            raise self.error
        return EmbeddingResult(index=0, embedding=self.embedding)


class FakeKnowledgeStatusProvider:
    def __init__(self, *, queryable: bool = True) -> None:
        self.queryable = queryable
        self.calls = 0

    async def get_index_status(self) -> KnowledgeIndexStatus:
        self.calls += 1
        return KnowledgeIndexStatus(
            last_run_status="succeeded" if self.queryable else None,
            active_document_count=1 if self.queryable else 0,
            chunk_count=1 if self.queryable else 0,
            embedding_model="text-embedding-3-small" if self.queryable else None,
            embedding_dimensions=1536 if self.queryable else None,
            queryable=self.queryable,
        )


class FakeExpertStatusProvider:
    def __init__(self, *, queryable: bool = True) -> None:
        self.queryable = queryable
        self.source_hashes: list[str] = []

    async def get_index_status(self, current_source_hash: str) -> ExpertTemplateIndexStatus:
        self.source_hashes.append(current_source_hash)
        return ExpertTemplateIndexStatus(
            latest_run_status="succeeded" if self.queryable else None,
            source_hash_matches=self.queryable,
            active_template_count=1 if self.queryable else 0,
            chunk_count=1 if self.queryable else 0,
            embedding_model="text-embedding-3-small" if self.queryable else None,
            embedding_dimensions=1536 if self.queryable else None,
            queryable=self.queryable,
        )


class FakeKnowledgeRetriever:
    def __init__(self, bundle: RetrievalBundle) -> None:
        self.bundle = bundle
        self.query_embeddings: list[tuple[float, ...]] = []

    async def retrieve_with_embedding(
        self,
        query: str,
        query_embedding: Sequence[float],
    ) -> RetrievalBundle:
        del query
        self.query_embeddings.append(tuple(query_embedding))
        return self.bundle


class FakeExpertRetriever:
    def __init__(
        self,
        bundle: ExpertTemplateRetrievalBundle | None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.bundle = bundle
        self.error = error
        self.query_embeddings: list[tuple[float, ...]] = []
        self.profile_ids: list[str] = []
        self.prompt_names: list[PromptName] = []

    async def retrieve(
        self,
        query: str,
        *,
        query_embedding: Sequence[float],
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle:
        del query
        self.query_embeddings.append(tuple(query_embedding))
        self.profile_ids.append(profile_id)
        self.prompt_names.append(prompt_name)
        if self.error is not None:
            raise self.error
        if self.bundle is None:
            raise AssertionError("FakeExpertRetriever 缺少结果。")
        return self.bundle


def make_knowledge_bundle() -> RetrievalBundle:
    return RetrievalBundle(
        query="设计零售工作流",
        ranked_candidates=(),
        selected_chunks=(),
        citations=(),
        context="官方上下文",
        context_token_count=10,
    )


def make_expert_bundle() -> ExpertTemplateRetrievalBundle:
    return ExpertTemplateRetrievalBundle(
        query="设计零售工作流",
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        ranked_candidates=(),
        selected_templates=(),
        context="以下内容是内部专家模板。",
        context_token_count=12,
    )


def make_service(
    *,
    embedding_client: FakeEmbeddingClient | None = None,
    knowledge_status: FakeKnowledgeStatusProvider | None = None,
    expert_status: FakeExpertStatusProvider | None = None,
    knowledge_retriever: FakeKnowledgeRetriever | None = None,
    expert_retriever: FakeExpertRetriever | None = None,
) -> ChatContextService:
    return ChatContextService(
        embedding_client=embedding_client,
        knowledge_status_provider=knowledge_status,
        expert_status_provider=expert_status,
        knowledge_retriever=knowledge_retriever,
        expert_retriever=expert_retriever,
        expert_source_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_generation_prompt_reuses_one_embedding_for_two_retrievers() -> None:
    embedding = FakeEmbeddingClient()
    knowledge = FakeKnowledgeRetriever(make_knowledge_bundle())
    expert = FakeExpertRetriever(make_expert_bundle())
    service = make_service(
        embedding_client=embedding,
        knowledge_status=FakeKnowledgeStatusProvider(),
        expert_status=FakeExpertStatusProvider(),
        knowledge_retriever=knowledge,
        expert_retriever=expert,
    )
    prompt_spec = PromptRegistry.create_default().get(PromptName.WORKFLOW_DESIGN)

    bundle = await service.build(
        "设计零售工作流",
        prompt_spec=prompt_spec,
        expert_profile="retail_sales_demo",
    )

    assert embedding.queries == ["设计零售工作流"]
    assert knowledge.query_embeddings == [embedding.embedding]
    assert expert.query_embeddings == [embedding.embedding]
    assert bundle.expert is not None
    assert bundle.official is not None


@pytest.mark.asyncio
async def test_document_summary_skips_indexes_embedding_and_retrievers() -> None:
    embedding = FakeEmbeddingClient()
    knowledge_status = FakeKnowledgeStatusProvider()
    expert_status = FakeExpertStatusProvider()
    knowledge = FakeKnowledgeRetriever(make_knowledge_bundle())
    expert = FakeExpertRetriever(make_expert_bundle())
    service = make_service(
        embedding_client=embedding,
        knowledge_status=knowledge_status,
        expert_status=expert_status,
        knowledge_retriever=knowledge,
        expert_retriever=expert,
    )
    prompt_spec = PromptRegistry.create_default().get(PromptName.DOCUMENT_SUMMARY)

    bundle = await service.build(
        "总结当前内容",
        prompt_spec=prompt_spec,
        expert_profile="generic",
    )

    assert bundle.expert is None
    assert bundle.official is None
    assert embedding.queries == []
    assert knowledge_status.calls == 0
    assert expert_status.source_hashes == []
    assert knowledge.query_embeddings == []
    assert expert.query_embeddings == []


@pytest.mark.asyncio
async def test_expert_index_not_ready_stops_before_embedding() -> None:
    embedding = FakeEmbeddingClient()
    service = make_service(
        embedding_client=embedding,
        expert_status=FakeExpertStatusProvider(queryable=False),
        expert_retriever=FakeExpertRetriever(make_expert_bundle()),
    )
    prompt_spec = PromptRegistry.create_default().get(PromptName.DATABRICKS_QA)

    with pytest.raises(AppError) as error:
        await service.build(
            "设计工作流",
            prompt_spec=prompt_spec,
            expert_profile="generic",
        )

    assert error.value.code == "expert_template_index_not_ready"
    assert error.value.status_code == 503
    assert embedding.queries == []


@pytest.mark.asyncio
async def test_expert_context_not_found_maps_stable_error() -> None:
    service = make_service(
        embedding_client=FakeEmbeddingClient(),
        expert_status=FakeExpertStatusProvider(),
        expert_retriever=FakeExpertRetriever(
            None,
            error=ExpertTemplateContextNotFoundError("没有上下文。"),
        ),
    )
    prompt_spec = PromptRegistry.create_default().get(PromptName.DATABRICKS_QA)

    with pytest.raises(AppError) as error:
        await service.build(
            "设计工作流",
            prompt_spec=prompt_spec,
            expert_profile="generic",
        )

    assert error.value.code == "expert_template_context_not_found"
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_embedding_failure_uses_existing_stable_error() -> None:
    service = make_service(
        embedding_client=FakeEmbeddingClient(error=EmbeddingRequestError("失败")),
        expert_status=FakeExpertStatusProvider(),
        expert_retriever=FakeExpertRetriever(make_expert_bundle()),
    )
    prompt_spec = PromptRegistry.create_default().get(PromptName.DATABRICKS_QA)

    with pytest.raises(AppError) as error:
        await service.build(
            "设计工作流",
            prompt_spec=prompt_spec,
            expert_profile="generic",
        )

    assert error.value.code == "embedding_request_failed"
    assert error.value.status_code == 502
