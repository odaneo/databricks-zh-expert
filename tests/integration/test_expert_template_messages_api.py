from collections.abc import AsyncIterator, Sequence
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.api.dependencies import (
    get_chat_context_service,
    get_model_gateway,
)
from databricks_zh_expert.chat.context import ChatContextService
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.retrieval import ExpertTemplateRetriever
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.rag.context import (
    RankedKnowledgeChunk,
    RetrievalBundle,
    SourceCitation,
)
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

VALID_WORKFLOW = """# AWS 零售销售工作流

## 需求理解
整合 S3 日批、RDS DMS CDC 与 Kinesis 事件流。

## 数据源假设
云平台为 AWS，关系源为 RDS PostgreSQL。

## Bronze 层设计
保留原始数据、摄取时间和来源元数据。

## Silver 层设计
完成去重、模式统一与业务主键校验。

## Gold 层设计
生成日销售和实时运营指标。

## Notebook 拆分
按批摄取、CDC、事件流、清洗和聚合拆分。

## Job 依赖关系
各 Bronze 任务完成后汇入 Silver，再生成 Gold。

## 调度建议
日批定时调度，Kinesis 流持续运行。

## 监控点
监控延迟、吞吐、失败重试与数据质量。

## 风险点
关注 CDC 重放、事件乱序和 SLA 偏差。

## 后续确认事项
确认数据量、恢复目标和保留周期。"""


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.embedding = (0.01,) * 1536

    async def embed_query(self, text: str) -> EmbeddingResult:
        self.queries.append(text)
        return EmbeddingResult(index=0, embedding=self.embedding)


class FakeKnowledgeStatusProvider:
    async def get_index_status(self) -> KnowledgeIndexStatus:
        return KnowledgeIndexStatus(
            last_run_status="succeeded",
            active_document_count=1,
            chunk_count=1,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            queryable=True,
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


class FakeModelGateway:
    def __init__(self) -> None:
        self.messages: list[ModelMessage] = []

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.messages = messages
        model_alias = requested_model or ModelAlias.DEEPSEEK_V4_FLASH
        yield ModelAttempt(
            invocation_id=uuid4(),
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
                "id": "chatcmpl-expert-template-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": VALID_WORKFLOW},
                        "finish_reason": "stop",
                    }
                ],
            },
            content=VALID_WORKFLOW,
            prompt_tokens=200,
            completion_tokens=100,
            latency_ms=120,
            success=True,
            retryable=False,
            error=None,
        )


def make_official_bundle() -> RetrievalBundle:
    chunk_id = UUID("00000000-0000-0000-0000-000000000901")
    chunk = RankedKnowledgeChunk(
        chunk_id=chunk_id,
        chunk_hash="9" * 64,
        document_id=UUID("00000000-0000-0000-0000-000000000902"),
        source_key="docs-lakeflow-jobs",
        title="Lakeflow Jobs",
        canonical_url="https://docs.databricks.com/aws/en/jobs/",
        chunk_index=0,
        heading_path=("Lakeflow Jobs",),
        content="Lakeflow Jobs orchestrates tasks.",
        token_count=8,
        source_ref="https://docs.databricks.com/aws/en/jobs/",
        vector_similarity=0.9,
        lexical_score=0.7,
        vector_rank=1,
        lexical_rank=1,
        fused_score=(1 / 61) + (1 / 61),
    )
    citation = SourceCitation(
        citation_id="S1",
        rank=1,
        title="Lakeflow Jobs",
        url="https://docs.databricks.com/aws/en/jobs/",
        heading="Lakeflow Jobs",
        chunk_id=chunk_id,
        chunk_hash="9" * 64,
    )
    return RetrievalBundle(
        query="设计零售工作流",
        ranked_candidates=(chunk,),
        selected_chunks=(chunk,),
        citations=(citation,),
        context="【不可信资料开始】\n[S1] Lakeflow Jobs 官方资料。\n【不可信资料结束】",
        context_token_count=20,
    )


async def test_retail_workflow_uses_real_expert_repository_and_keeps_api_private(
    ready_client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
    ready_expert_template_index: ExpertTemplateRepository,
    expert_template_registry: ExpertTemplateRegistry,
) -> None:
    embedding = FakeEmbeddingClient()
    official = FakeKnowledgeRetriever(make_official_bundle())
    context_service = ChatContextService(
        embedding_client=embedding,
        knowledge_status_provider=FakeKnowledgeStatusProvider(),
        expert_status_provider=ready_expert_template_index,
        knowledge_retriever=official,
        expert_retriever=ExpertTemplateRetriever(
            repository=ready_expert_template_index,
            registry=expert_template_registry,
        ),
        expert_source_hash=expert_template_registry.source_hash,
    )
    gateway = FakeModelGateway()
    test_app.dependency_overrides[get_chat_context_service] = lambda: context_service
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway

    create_response = await ready_client.post(
        "/api/chat/sessions",
        json={
            "title": "零售工作流集成测试",
            "expert_profile": "retail_sales_demo",
        },
    )
    session_id = UUID(create_response.json()["id"])
    response = await ready_client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "设计包含 S3、RDS DMS CDC 和 Kinesis 的零售工作流",
            "prompt": "workflow_design",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert "expert_templates" not in payload
    assert "expert_templates" not in payload["assistant_message"]
    assert payload["assistant_message"]["source_citations"][0]["url"].startswith(
        "https://docs.databricks.com/"
    )
    assert embedding.queries == ["设计包含 S3、RDS DMS CDC 和 Kinesis 的零售工作流"]
    assert official.query_embeddings == [embedding.embedding]
    assert [message.role for message in gateway.messages[-3:]] == ["user", "user", "user"]
    assert gateway.messages[-3].content.startswith("以下内容是内部专家模板")
    assert gateway.messages[-2].content.startswith("【不可信资料开始】")

    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.expert_profile == "retail_sales_demo"
    assert model_call.expert_template_selections
    assert any(
        selection["layer"] == "retail_sales_demo"
        for selection in model_call.expert_template_selections
    )
