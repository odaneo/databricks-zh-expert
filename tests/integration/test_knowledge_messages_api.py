from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.api.dependencies import (
    get_chat_context_service,
    get_knowledge_repository,
    get_knowledge_retriever,
    get_model_gateway,
)
from databricks_zh_expert.chat.context import ChatContextBundle
from databricks_zh_expert.db.models import Message, ModelCall
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.context import (
    RankedKnowledgeChunk,
    RetrievalBundle,
    SourceCitation,
)
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus
from databricks_zh_expert.workspace.types import WorkspaceDefinition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

VALID_ANSWER = """# Databricks 工作流建议

## 结论
建议使用分层工作流。

## 适用场景
每日数据处理。

## 详细说明
按业务口径逐层处理。

## 注意事项
监控延迟和失败。

## 人工确认事项
确认数据源。
"""
VALID_KNOWLEDGE_ANSWER = """# Lakeflow Jobs 重试建议

## 结论
建议配置任务重试。[S1]

## 适用场景
临时故障恢复。

## 详细说明
根据任务幂等性配置重试。[S1]

## 注意事项
非幂等任务需要额外保护。

## 人工确认事项
确认重试次数。

## 引用来源
- [S1] Configure Lakeflow Jobs
"""


class FakeKnowledgeStatusProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def get_index_status(self) -> KnowledgeIndexStatus:
        self.calls += 1
        return KnowledgeIndexStatus(
            last_run_status="succeeded",
            active_document_count=6,
            chunk_count=6,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            queryable=True,
        )


class FakeKnowledgeRetriever:
    def __init__(self, bundle: RetrievalBundle) -> None:
        self.bundle = bundle
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> RetrievalBundle:
        self.queries.append(query)
        return self.bundle


class FakeChatContextService:
    def __init__(
        self,
        retriever: FakeKnowledgeRetriever,
        status_provider: FakeKnowledgeStatusProvider,
    ) -> None:
        self.retriever = retriever
        self.status_provider = status_provider

    async def build(
        self,
        query: str,
        *,
        prompt_spec,
        expert_profile: str,
        workspace: WorkspaceDefinition | None = None,
    ) -> ChatContextBundle:
        del expert_profile, workspace
        if prompt_spec.name is not PromptName.KNOWLEDGE_QA:
            return ChatContextBundle(expert=None, official=None)
        status = await self.status_provider.get_index_status()
        assert status.queryable is True
        return ChatContextBundle(
            expert=None,
            official=await self.retriever.retrieve(query),
            official_latency_ms=1,
        )


class FakeModelGateway:
    def __init__(self) -> None:
        self.invocation_id = uuid4()
        self.messages: list[ModelMessage] = []

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.messages = messages
        is_knowledge = "## 引用来源" in messages[0].content
        content = VALID_KNOWLEDGE_ANSWER if is_knowledge else VALID_ANSWER
        model_alias = requested_model or ModelAlias.DEEPSEEK_V4_FLASH
        yield ModelAttempt(
            invocation_id=self.invocation_id,
            requested_model=model_alias,
            model_alias=model_alias,
            provider=ModelProvider.DEEPSEEK,
            litellm_model="deepseek/deepseek-v4-flash",
            attempt_number=1,
            request={
                "model": "deepseek/deepseek-v4-flash",
                "messages": [
                    {"role": message.role, "content": message.content} for message in messages
                ],
            },
            response={
                "id": "chatcmpl-knowledge-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
            content=content,
            prompt_tokens=40,
            completion_tokens=30,
            latency_ms=100,
            success=True,
            retryable=False,
            error=None,
        )


def _retrieval_bundle() -> RetrievalBundle:
    chunks: list[RankedKnowledgeChunk] = []
    citations: list[SourceCitation] = []
    for rank in range(1, 7):
        chunk_id = UUID(int=rank)
        source_ref = f"https://docs.databricks.com/aws/en/jobs/source-{rank}#section"
        chunks.append(
            RankedKnowledgeChunk(
                chunk_id=chunk_id,
                chunk_hash=f"{rank:064x}",
                document_id=UUID(int=rank + 100),
                source_key=f"docs-source-{rank}",
                title=f"Databricks Source {rank}",
                canonical_url=f"https://docs.databricks.com/aws/en/jobs/source-{rank}",
                chunk_index=0,
                heading_path=("Lakeflow Jobs", f"Section {rank}"),
                content=f"Official content {rank}.",
                token_count=6,
                source_ref=source_ref,
                vector_similarity=0.9 - (rank / 100),
                lexical_score=None,
                vector_rank=rank,
                lexical_rank=None,
                fused_score=1 / (60 + rank),
            )
        )
        citations.append(
            SourceCitation(
                citation_id=f"S{rank}",
                rank=rank,
                title=f"Databricks Source {rank}",
                url=source_ref,
                heading=f"Lakeflow Jobs > Section {rank}",
                chunk_id=chunk_id,
                chunk_hash=f"{rank:064x}",
            )
        )
    context = "【不可信资料开始】\n[S1] Official content 1.\n【不可信资料结束】"
    return RetrievalBundle(
        query="如何配置失败重试？",
        ranked_candidates=tuple(chunks),
        selected_chunks=tuple(chunks),
        citations=tuple(citations),
        context=context,
        context_token_count=20,
    )


async def test_knowledge_message_response_and_history_share_persisted_citations(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    bundle = _retrieval_bundle()
    retriever = FakeKnowledgeRetriever(bundle)
    status_provider = FakeKnowledgeStatusProvider()
    gateway = FakeModelGateway()
    test_app.dependency_overrides[get_knowledge_retriever] = lambda: retriever
    test_app.dependency_overrides[get_knowledge_repository] = lambda: status_provider
    test_app.dependency_overrides[get_chat_context_service] = lambda: FakeChatContextService(
        retriever,
        status_provider,
    )
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "知识库引用测试"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "如何配置失败重试？",
            "prompt": "knowledge_qa",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user_message"]["source_citations"] is None
    assert len(payload["assistant_message"]["source_citations"]) == 6
    assert payload["assistant_message"]["source_citations"][0] == {
        "citation_id": "S1",
        "rank": 1,
        "title": "Databricks Source 1",
        "url": "https://docs.databricks.com/aws/en/jobs/source-1#section",
        "heading": "Lakeflow Jobs > Section 1",
        "chunk_id": "00000000-0000-0000-0000-000000000001",
        "chunk_hash": f"{1:064x}",
    }
    assert retriever.queries == ["如何配置失败重试？"]
    assert status_provider.calls == 1
    assert [message.role for message in gateway.messages] == ["system", "user", "user"]
    assert gateway.messages[-2].content == bundle.context
    assert gateway.messages[-1].content == "如何配置失败重试？"

    detail_response = await client.get(f"/api/chat/sessions/{session_id}")
    history_messages = detail_response.json()["messages"]
    assert history_messages[0]["source_citations"] is None
    assert (
        history_messages[1]["source_citations"] == payload["assistant_message"]["source_citations"]
    )

    stored_messages = list(
        (
            await test_db_session.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at, Message.id)
            )
        ).all()
    )
    assert stored_messages[0].source_citations is None
    assert stored_messages[1].source_citations == payload["assistant_message"]["source_citations"]
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.expert_profile == "generic"
    assert model_call.expert_template_selections == []


async def test_standard_message_history_keeps_null_citations(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    retriever = FakeKnowledgeRetriever(_retrieval_bundle())
    status_provider = FakeKnowledgeStatusProvider()
    gateway = FakeModelGateway()
    test_app.dependency_overrides[get_knowledge_retriever] = lambda: retriever
    test_app.dependency_overrides[get_knowledge_repository] = lambda: status_provider
    test_app.dependency_overrides[get_chat_context_service] = lambda: FakeChatContextService(
        retriever,
        status_provider,
    )
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "普通消息引用测试"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "设计一个工作流"},
    )
    detail_response = await client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 201
    assert response.json()["assistant_message"]["source_citations"] is None
    assert all(
        message["source_citations"] is None for message in detail_response.json()["messages"]
    )
    assert retriever.queries == []
    assert status_provider.calls == 0
