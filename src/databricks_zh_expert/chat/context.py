from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from databricks_zh_expert.core.errors import (
    EmbeddingNotConfiguredAppError,
    EmbeddingRequestFailedAppError,
    ExpertTemplateContextNotFoundAppError,
    ExpertTemplateIndexNotReadyAppError,
    KnowledgeContextNotFoundAppError,
    KnowledgeIndexNotReadyAppError,
)
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextNotFoundError,
    ExpertTemplateRetrievalBundle,
)
from databricks_zh_expert.expert_templates.types import ExpertTemplateIndexStatus
from databricks_zh_expert.prompts.registry import PromptName, PromptSpec
from databricks_zh_expert.rag.context import (
    KnowledgeContextNotFoundError,
    RetrievalBundle,
)
from databricks_zh_expert.rag.embeddings import (
    EmbeddingInputError,
    EmbeddingNotConfiguredError,
    EmbeddingRequestError,
    EmbeddingResult,
)
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.types import (
    WorkspaceContextBundle,
    WorkspaceDefinition,
)


class QueryEmbeddingClient(Protocol):
    async def embed_query(self, text: str) -> EmbeddingResult: ...


class KnowledgeStatusProvider(Protocol):
    async def get_index_status(self) -> KnowledgeIndexStatus: ...


class ExpertTemplateStatusProvider(Protocol):
    async def get_index_status(
        self,
        current_source_hash: str,
    ) -> ExpertTemplateIndexStatus: ...


class KnowledgeContextRetriever(Protocol):
    async def retrieve_with_embedding(
        self,
        query: str,
        query_embedding: Sequence[float],
    ) -> RetrievalBundle: ...


class ExpertTemplateContextRetriever(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        query_embedding: Sequence[float],
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle: ...


@dataclass(frozen=True, slots=True)
class ChatContextBundle:
    expert: ExpertTemplateRetrievalBundle | None
    official: RetrievalBundle | None
    workspace: WorkspaceContextBundle | None = None
    expert_latency_ms: int = 0
    official_latency_ms: int = 0


class ChatContextService:
    def __init__(
        self,
        *,
        embedding_client: QueryEmbeddingClient | None,
        knowledge_status_provider: KnowledgeStatusProvider | None,
        expert_status_provider: ExpertTemplateStatusProvider | None,
        knowledge_retriever: KnowledgeContextRetriever | None,
        expert_retriever: ExpertTemplateContextRetriever | None,
        expert_source_hash: str,
        workspace_context_builder: WorkspaceContextBuilder | None = None,
    ) -> None:
        self._embedding_client = embedding_client
        self._knowledge_status_provider = knowledge_status_provider
        self._expert_status_provider = expert_status_provider
        self._knowledge_retriever = knowledge_retriever
        self._expert_retriever = expert_retriever
        self._expert_source_hash = expert_source_hash
        self._workspace_context_builder = workspace_context_builder or WorkspaceContextBuilder()

    async def build(
        self,
        query: str,
        *,
        prompt_spec: PromptSpec,
        expert_profile: str,
        workspace: WorkspaceDefinition | None = None,
    ) -> ChatContextBundle:
        workspace_context = (
            self._workspace_context_builder.build_for_prompt(
                query,
                workspace=workspace,
                prompt_name=prompt_spec.name.value,
            )
            if prompt_spec.use_workspace_context and workspace is not None
            else None
        )
        if not prompt_spec.use_official_knowledge and not prompt_spec.use_expert_templates:
            return ChatContextBundle(
                expert=None,
                official=None,
                workspace=workspace_context,
            )

        await self._ensure_required_indexes(prompt_spec)
        query_embedding = await self._embed_query(query)

        expert: ExpertTemplateRetrievalBundle | None = None
        expert_latency_ms = 0
        if prompt_spec.use_expert_templates:
            if self._expert_retriever is None:
                raise ExpertTemplateIndexNotReadyAppError()
            started_at = perf_counter()
            try:
                expert = await self._expert_retriever.retrieve(
                    query,
                    query_embedding=query_embedding,
                    profile_id=expert_profile,
                    prompt_name=prompt_spec.name,
                )
            except ExpertTemplateContextNotFoundError:
                raise ExpertTemplateContextNotFoundAppError() from None
            expert_latency_ms = round((perf_counter() - started_at) * 1000)

        official: RetrievalBundle | None = None
        official_latency_ms = 0
        if prompt_spec.use_official_knowledge:
            if self._knowledge_retriever is None:
                raise KnowledgeIndexNotReadyAppError()
            started_at = perf_counter()
            try:
                official = await self._knowledge_retriever.retrieve_with_embedding(
                    query,
                    query_embedding,
                )
            except KnowledgeContextNotFoundError:
                raise KnowledgeContextNotFoundAppError() from None
            official_latency_ms = round((perf_counter() - started_at) * 1000)

        return ChatContextBundle(
            expert=expert,
            official=official,
            workspace=workspace_context,
            expert_latency_ms=expert_latency_ms,
            official_latency_ms=official_latency_ms,
        )

    async def _ensure_required_indexes(self, prompt_spec: PromptSpec) -> None:
        if prompt_spec.use_official_knowledge:
            if self._knowledge_status_provider is None:
                raise KnowledgeIndexNotReadyAppError()
            status = await self._knowledge_status_provider.get_index_status()
            if not status.queryable:
                raise KnowledgeIndexNotReadyAppError()

        if prompt_spec.use_expert_templates:
            if self._expert_status_provider is None or not self._expert_source_hash:
                raise ExpertTemplateIndexNotReadyAppError()
            status = await self._expert_status_provider.get_index_status(self._expert_source_hash)
            if not status.queryable:
                raise ExpertTemplateIndexNotReadyAppError()

    async def _embed_query(self, query: str) -> tuple[float, ...]:
        if self._embedding_client is None:
            raise EmbeddingNotConfiguredAppError()
        try:
            result = await self._embedding_client.embed_query(query)
        except EmbeddingNotConfiguredError:
            raise EmbeddingNotConfiguredAppError() from None
        except (EmbeddingInputError, EmbeddingRequestError):
            raise EmbeddingRequestFailedAppError() from None
        return result.embedding
