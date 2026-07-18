import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.artifacts.markdown import MarkdownArtifactParser
from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.chat.context import ChatContextBundle
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.errors import (
    AppError,
    EmbeddingRequestFailedAppError,
    KnowledgeContextNotFoundAppError,
    KnowledgeIndexNotReadyAppError,
)
from databricks_zh_expert.db.models import ChatSession, Message, ModelCall
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateRetrievalBundle,
    ExpertTemplateSelection,
    RankedExpertTemplateCandidate,
)
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import (
    ModelAttempt,
    ModelGateway,
    ModelGatewayFailure,
)
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.observability.model_trace import ModelCallTrace, ModelTraceSink
from databricks_zh_expert.prompts.registry import PromptName, PromptRegistry
from databricks_zh_expert.rag.context import (
    KnowledgeContextBuilder,
    KnowledgeContextNotFoundError,
    RankedKnowledgeChunk,
    RetrievalBundle,
)
from databricks_zh_expert.rag.embeddings import EmbeddingRequestError
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.registry import WorkspaceRegistry
from databricks_zh_expert.workspace.types import WorkspaceDefinition

NOW = datetime(2026, 1, 1, tzinfo=UTC)
VALID_ANSWER = """# Databricks 分析建议

## 结论
建议使用分层工作流。

## 适用场景
每日销售分析。

## 详细说明
使用 Bronze、Silver、Gold 三层。

## 注意事项
先确认源数据质量。

## 人工确认事项
确认调度时间。"""
VALID_SQL = """```sql
-- 汇总销售数据
SELECT 1;
```"""
VALID_WORKFLOW = """# AWS 零售销售工作流

## 需求理解
整合批处理、CDC 与实时事件。

## 数据源假设
使用 S3、RDS PostgreSQL 和 Kinesis。

## Bronze 层设计
保留原始数据与摄取元数据。

## Silver 层设计
完成清洗、去重和统一口径。

## Gold 层设计
生成销售主题汇总。

## Notebook 拆分
按摄取、清洗和聚合拆分。

## Job 依赖关系
Bronze 完成后执行 Silver，再执行 Gold。

## 调度建议
批处理每日调度，流处理持续运行。

## 监控点
监控延迟、失败和数据质量。

## 风险点
关注 CDC 重放和事件乱序。

## 后续确认事项
确认 SLA 与保留周期。"""
VALID_KNOWLEDGE_ANSWER = """# Lakeflow Jobs 重试建议

## 结论
建议显式配置任务重试策略。

## 适用场景
存在临时网络或服务故障的工作流。

## 详细说明
结合任务幂等性设置重试次数和间隔。[S1]

## 注意事项
非幂等写入需要额外保护。

## 人工确认事项
确认失败类型和恢复目标。

## 引用来源
- [S1] Configure Lakeflow Jobs
"""


def make_session() -> ChatSession:
    return ChatSession(
        id=uuid4(),
        title="测试会话",
        expert_profile="generic",
        created_at=NOW,
        updated_at=NOW,
    )


def make_message(
    session_id: UUID,
    role: str,
    content: str,
    index: int,
) -> Message:
    return Message(
        id=uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        artifact_type=None,
        created_at=NOW + timedelta(seconds=index),
    )


MODEL_DETAILS = {
    ModelAlias.GPT_55: (ModelProvider.OPENAI, "openai/gpt-5.5"),
    ModelAlias.GPT_54_MINI: (ModelProvider.OPENAI, "openai/gpt-5.4-mini"),
    ModelAlias.DEEPSEEK_V4_FLASH: (
        ModelProvider.DEEPSEEK,
        "deepseek/deepseek-v4-flash",
    ),
}


def make_attempt(
    *,
    invocation_id: UUID,
    requested_model: ModelAlias = ModelAlias.GPT_55,
    model_alias: ModelAlias,
    attempt_number: int,
    success: bool,
    retryable: bool = False,
    content: str = VALID_ANSWER,
    error_code: str = "model_provider_unavailable",
    error_message: str = "模型服务暂时不可用。",
) -> ModelAttempt:
    provider, litellm_model = MODEL_DETAILS[model_alias]
    response = (
        {
            "object": "chat.completion",
            "model": litellm_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
        if success
        else None
    )
    error = (
        None
        if success
        else {
            "message": error_message,
            "type": "FakeProviderError",
            "param": None,
            "code": error_code,
        }
    )
    return ModelAttempt(
        invocation_id=invocation_id,
        requested_model=requested_model,
        model_alias=model_alias,
        provider=provider,
        litellm_model=litellm_model,
        attempt_number=attempt_number,
        request={
            "model": litellm_model,
            "messages": [{"role": "user", "content": "设计一个销售工作流"}],
        },
        response=response,
        content=content if success else None,
        prompt_tokens=12 if success else None,
        completion_tokens=8 if success else None,
        latency_ms=attempt_number * 100,
        success=success,
        retryable=retryable,
        error=error,
    )


class FakeChatRepository:
    def __init__(
        self,
        session: ChatSession | None,
        messages: list[Message] | None = None,
        *,
        fail_model_call_number: int | None = None,
    ) -> None:
        self.session = session
        self.messages = list(messages or [])
        self.model_calls: list[ModelCall] = []
        self.events: list[str] = []
        self.fail_model_call_number = fail_model_call_number
        self.model_call_requests = 0

    async def get_session(self, session_id: UUID) -> ChatSession | None:
        if self.session is not None and self.session.id == session_id:
            return self.session
        return None

    async def create_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        artifact_type: str | None = None,
        source_citations: list[dict[str, object]] | None = None,
    ) -> Message:
        message = make_message(session_id, role, content, len(self.messages))
        message.artifact_type = artifact_type
        message.source_citations = source_citations
        self.messages.append(message)
        self.events.append(f"message:{role}")
        return message

    async def list_recent_messages(
        self,
        session_id: UUID,
        limit: int = 20,
    ) -> list[Message]:
        return [message for message in self.messages if message.session_id == session_id][-limit:]

    async def create_model_call(
        self,
        *,
        session_id: UUID,
        invocation_id: UUID,
        provider: str,
        model: str,
        model_alias: str,
        attempt_number: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
        success: bool,
        retryable: bool,
        error_code: str | None,
        error_message: str | None,
        prompt_name: str,
        prompt_version: str,
        artifact_type: str,
        artifact_valid: bool | None,
        artifact_error_code: str | None,
        expert_profile: str,
        expert_template_selections: list[dict[str, object]],
        workspace_id: str | None = None,
        workspace_version: str | None = None,
        workspace_mode: str | None = None,
        workspace_source_hash: str | None = None,
        workspace_context: list[dict[str, object]] | None = None,
        project_fact_status: str | None = None,
    ) -> ModelCall:
        self.model_call_requests += 1
        if self.model_call_requests == self.fail_model_call_number:
            raise RuntimeError("数据库写入失败")
        model_call = ModelCall(
            id=uuid4(),
            session_id=session_id,
            invocation_id=invocation_id,
            provider=provider,
            model=model,
            model_alias=model_alias,
            attempt_number=attempt_number,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            retryable=retryable,
            error_code=error_code,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            artifact_type=artifact_type,
            artifact_valid=artifact_valid,
            artifact_error_code=artifact_error_code,
            expert_profile=expert_profile,
            expert_template_selections=expert_template_selections,
            workspace_id=workspace_id,
            workspace_version=workspace_version,
            workspace_mode=workspace_mode,
            workspace_source_hash=workspace_source_hash,
            workspace_context=workspace_context,
            project_fact_status=project_fact_status,
            error_message=error_message,
            created_at=NOW + timedelta(milliseconds=attempt_number),
        )
        self.model_calls.append(model_call)
        self.events.append(f"model_call:{attempt_number}")
        return model_call


class FakeModelGateway:
    def __init__(
        self,
        attempts: list[ModelAttempt],
        *,
        failure: ModelGatewayFailure | None = None,
    ) -> None:
        self.attempts = attempts
        self.failure = failure
        self.received_messages: list[ModelMessage] = []
        self.received_requested_model: ModelAlias | None = None
        self.resumed = False
        self.called = False
        self.yielded_attempts = 0

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.called = True
        self.received_messages = messages
        self.received_requested_model = requested_model
        for index, attempt in enumerate(self.attempts):
            if index > 0:
                self.resumed = True
            self.yielded_attempts += 1
            yield attempt
        if self.failure is not None:
            raise self.failure


class FakeModelTraceSink:
    def __init__(self) -> None:
        self.traces: list[ModelCallTrace] = []

    async def write(self, trace: ModelCallTrace) -> None:
        self.traces.append(trace)


class FakeChatContextService:
    def __init__(
        self,
        bundle: ChatContextBundle,
        *,
        error: AppError | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.bundle = bundle
        self.error = error
        self.events = events
        self.requests: list[tuple[str, PromptName, str]] = []
        self.workspaces: list[WorkspaceDefinition | None] = []

    async def build(
        self,
        query: str,
        *,
        prompt_spec,
        expert_profile: str,
        workspace: WorkspaceDefinition | None = None,
    ) -> ChatContextBundle:
        self.requests.append((query, prompt_spec.name, expert_profile))
        self.workspaces.append(workspace)
        if self.events is not None:
            self.events.append("context")
        if self.error is not None:
            raise self.error
        return self.bundle


class FakeKnowledgeChatContextService:
    def __init__(
        self,
        retriever: "FakeKnowledgeRetriever",
        status_provider: "FakeKnowledgeStatusProvider",
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
        if not status.queryable:
            raise KnowledgeIndexNotReadyAppError()
        try:
            bundle = await self.retriever.retrieve(query)
        except KnowledgeContextNotFoundError:
            raise KnowledgeContextNotFoundAppError() from None
        except EmbeddingRequestError:
            raise EmbeddingRequestFailedAppError() from None
        return ChatContextBundle(
            expert=None,
            official=bundle,
            official_latency_ms=1,
        )


class FakeKnowledgeStatusProvider:
    def __init__(
        self,
        status: KnowledgeIndexStatus,
        *,
        events: list[str] | None = None,
    ) -> None:
        self.status = status
        self.events = events
        self.calls = 0

    async def get_index_status(self) -> KnowledgeIndexStatus:
        self.calls += 1
        if self.events is not None:
            self.events.append("index_status")
        return self.status


class FakeKnowledgeRetriever:
    def __init__(
        self,
        bundle: RetrievalBundle | None = None,
        *,
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.bundle = bundle
        self.error = error
        self.events = events
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> RetrievalBundle:
        self.queries.append(query)
        if self.events is not None:
            self.events.append("retrieve")
        if self.error is not None:
            raise self.error
        if self.bundle is None:
            raise AssertionError("FakeKnowledgeRetriever 缺少 RetrievalBundle。")
        return self.bundle


def make_index_status(*, queryable: bool) -> KnowledgeIndexStatus:
    return KnowledgeIndexStatus(
        last_run_status="succeeded" if queryable else None,
        active_document_count=1 if queryable else 0,
        chunk_count=1 if queryable else 0,
        embedding_model="text-embedding-3-small" if queryable else None,
        embedding_dimensions=1536 if queryable else None,
        queryable=queryable,
    )


def make_retrieval_bundle() -> RetrievalBundle:
    chunk = RankedKnowledgeChunk(
        chunk_id=UUID("00000000-0000-0000-0000-000000000101"),
        chunk_hash="1" * 64,
        document_id=UUID("00000000-0000-0000-0000-000000000201"),
        source_key="docs-lakeflow-jobs",
        title="Configure Lakeflow Jobs",
        canonical_url="https://docs.databricks.com/aws/en/jobs/",
        chunk_index=0,
        heading_path=("Lakeflow Jobs", "Configure retries"),
        content="Configure retries for transient task failures.",
        token_count=8,
        source_ref="https://docs.databricks.com/aws/en/jobs/configure-job#retries",
        vector_similarity=0.92,
        lexical_score=0.7,
        vector_rank=1,
        lexical_rank=1,
        fused_score=(1 / 61) + (1 / 61),
    )
    return KnowledgeContextBuilder().build("如何配置失败重试？", (chunk,))


def make_expert_retrieval_bundle() -> ExpertTemplateRetrievalBundle:
    record_id = UUID("00000000-0000-0000-0000-000000000301")
    candidate = RankedExpertTemplateCandidate(
        chunk_id=UUID("00000000-0000-0000-0000-000000000302"),
        template_record_id=record_id,
        template_id="retail.workflow_dag",
        version="1.0.0",
        name="零售工作流依赖图",
        layer="retail_sales_demo",
        profile_id="retail_sales_demo",
        kind=ExpertTemplateKind.BLUEPRINT,
        category=ExpertTemplateCategory.WORKFLOW,
        content_hash="3" * 64,
        extends_record_id=UUID("00000000-0000-0000-0000-000000000303"),
        matched_chunk_content="RDS DMS、S3 和 Kinesis 工作流。",
        vector_similarity=0.91,
        lexical_score=0.8,
        vector_rank=1,
        lexical_rank=1,
        fused_score=(1 / 61) + (1 / 61),
        reason="semantic",
    )
    selection = ExpertTemplateSelection(
        record_id=record_id,
        template_id="retail.workflow_dag",
        version="1.0.0",
        name="零售工作流依赖图",
        content_hash="3" * 64,
        layer="retail_sales_demo",
        profile_id="retail_sales_demo",
        rank=1,
        reason="semantic",
        extends="workflow.lakeflow_jobs@1.0.0",
    )
    return ExpertTemplateRetrievalBundle(
        query="设计零售工作流",
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        ranked_candidates=(candidate,),
        selected_templates=(selection,),
        context="以下内容是内部专家模板。\n【内部专家模板开始】\n零售工作流",
        context_token_count=24,
    )


def build_service(
    repository: FakeChatRepository,
    model_gateway: FakeModelGateway,
    trace_sink: FakeModelTraceSink | None = None,
    *,
    context_service: FakeChatContextService | None = None,
    knowledge_retriever: FakeKnowledgeRetriever | None = None,
    knowledge_status_provider: FakeKnowledgeStatusProvider | None = None,
) -> tuple[ChatService, FakeModelTraceSink]:
    trace_sink = trace_sink or FakeModelTraceSink()
    if context_service is None:
        if knowledge_retriever is not None and knowledge_status_provider is not None:
            context_service = cast(
                FakeChatContextService,
                FakeKnowledgeChatContextService(
                    knowledge_retriever,
                    knowledge_status_provider,
                ),
            )
        else:
            context_service = FakeChatContextService(ChatContextBundle(expert=None, official=None))
    service = ChatService(
        cast(ChatRepository, repository),
        cast(ModelGateway, model_gateway),
        cast(ModelTraceSink, trace_sink),
        PromptRegistry.create_default(),
        MarkdownArtifactParser(),
        context_service=context_service,
        workspace_registry=WorkspaceRegistry.create_default(),
    )
    return service, trace_sink


@pytest.mark.asyncio
async def test_workspace_proposal_orders_context_and_audits_every_attempt() -> None:
    session = make_session()
    session.workspace_id = "retail_sales_demo"
    historical_user = make_message(session.id, "user", "历史需求", 0)
    historical_artifact = make_message(session.id, "assistant", VALID_SQL, 1)
    historical_artifact.artifact_type = "sql"
    repository = FakeChatRepository(session, [historical_user, historical_artifact])
    invocation_id = uuid4()
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
                content=VALID_SQL,
            ),
        ]
    )
    registry = WorkspaceRegistry.create_default()
    workspace = registry.get("retail_sales_demo")
    workspace_bundle = WorkspaceContextBuilder().build_for_prompt(
        "根据 public.customers 生成客户 CDC DDL",
        workspace=workspace,
        prompt_name=PromptName.DDL_GENERATION.value,
    )
    assert workspace_bundle is not None
    context_service = FakeChatContextService(
        ChatContextBundle(
            expert=make_expert_retrieval_bundle(),
            official=make_retrieval_bundle(),
            workspace=workspace_bundle,
        )
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        context_service=context_service,
    )

    result = await service.send_message(
        session.id,
        "根据 public.customers 生成客户 CDC DDL",
        requested_prompt=PromptName.DDL_GENERATION,
    )

    assert context_service.workspaces == [workspace]
    assert [message.content for message in gateway.received_messages[1:4]] == [
        make_retrieval_bundle().context,
        make_expert_retrieval_bundle().context,
        workspace_bundle.context,
    ]
    assert gateway.received_messages[4].content == "历史需求"
    assert "未确认提案" in gateway.received_messages[5].content
    assert VALID_SQL in gateway.received_messages[5].content
    assert gateway.received_messages[6].content == "根据 public.customers 生成客户 CDC DDL"
    assert result.project_fact_status == "proposal"
    assert [call.project_fact_status for call in repository.model_calls] == [
        "proposal",
        "proposal",
    ]
    assert [call.workspace_id for call in repository.model_calls] == [
        "retail_sales_demo",
        "retail_sales_demo",
    ]
    assert repository.model_calls[0].workspace_context == (
        repository.model_calls[1].workspace_context
    )
    assert repository.model_calls[0].workspace_context
    assert all(
        not str(selection["source_path"]).startswith(("C:\\", "/"))
        for selection in repository.model_calls[0].workspace_context or []
    )
    assert trace_sink.traces[0].workspace is trace_sink.traces[1].workspace
    assert trace_sink.traces[0].project_fact_status == "proposal"


@pytest.mark.asyncio
async def test_dual_context_orders_messages_and_persists_same_audit_for_fallback() -> None:
    session = make_session()
    session.expert_profile = "retail_sales_demo"
    historical_messages = [
        make_message(session.id, "user", "历史问题", 0),
        make_message(session.id, "assistant", "历史回答", 1),
    ]
    repository = FakeChatRepository(session, historical_messages)
    invocation_id = uuid4()
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
                content=VALID_WORKFLOW,
            ),
        ]
    )
    expert_bundle = make_expert_retrieval_bundle()
    official_bundle = make_retrieval_bundle()
    context_service = FakeChatContextService(
        ChatContextBundle(
            expert=expert_bundle,
            official=official_bundle,
            expert_latency_ms=11,
            official_latency_ms=13,
        ),
        events=repository.events,
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        context_service=context_service,
    )

    result = await service.send_message(
        session.id,
        "设计零售工作流",
        requested_prompt=PromptName.WORKFLOW_DESIGN,
    )

    assert context_service.requests == [
        ("设计零售工作流", PromptName.WORKFLOW_DESIGN, "retail_sales_demo")
    ]
    assert repository.events[:2] == ["message:user", "context"]
    assert [message.role for message in gateway.received_messages] == [
        "system",
        "user",
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in gateway.received_messages[1:]] == [
        official_bundle.context,
        expert_bundle.context,
        "历史问题",
        "历史回答",
        "设计零售工作流",
    ]
    expected_selections = [
        {
            "template_id": "retail.workflow_dag",
            "version": "1.0.0",
            "content_hash": "3" * 64,
            "layer": "retail_sales_demo",
            "profile": "retail_sales_demo",
            "rank": 1,
            "reason": "semantic",
        }
    ]
    assert [call.expert_profile for call in repository.model_calls] == [
        "retail_sales_demo",
        "retail_sales_demo",
    ]
    assert [call.expert_template_selections for call in repository.model_calls] == [
        expected_selections,
        expected_selections,
    ]
    assert result.assistant_message.source_citations == _citation_payloads_for_test(official_bundle)
    assert len(trace_sink.traces) == 2
    assert trace_sink.traces[0].expert_profile == "retail_sales_demo"
    assert trace_sink.traces[0].expert_templates is trace_sink.traces[1].expert_templates


def _citation_payloads_for_test(bundle: RetrievalBundle) -> list[dict[str, object]]:
    return [
        {
            "citation_id": citation.citation_id,
            "rank": citation.rank,
            "title": citation.title,
            "url": citation.url,
            "heading": citation.heading,
            "chunk_id": str(citation.chunk_id),
            "chunk_hash": citation.chunk_hash,
        }
        for citation in bundle.citations
    ]


@pytest.mark.asyncio
async def test_send_message_persists_each_fallback_attempt_before_reply() -> None:
    session = make_session()
    historical_messages = [
        make_message(session.id, "user" if index % 2 == 0 else "assistant", f"历史 {index}", index)
        for index in range(25)
    ]
    invocation_id = uuid4()
    repository = FakeChatRepository(session, historical_messages)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
            ),
        ]
    )
    service, trace_sink = build_service(repository, gateway)

    result = await service.send_message(
        session.id,
        "设计一个销售工作流",
        ModelAlias.GPT_55,
    )

    assert result.user_message.content == "设计一个销售工作流"
    assert result.assistant_message.content == VALID_ANSWER
    assert result.assistant_message.artifact_type == "answer"
    assert result.prompt_name is PromptName.DATABRICKS_QA
    assert result.prompt_version == "1.0.1"
    assert result.artifact.artifact_type is ArtifactType.ANSWER
    assert result.artifact.title == "Databricks 分析建议"
    assert result.model_invocation_id == invocation_id
    assert result.requested_model is ModelAlias.GPT_55
    assert result.used_model is ModelAlias.GPT_54_MINI
    assert result.fallback_used is True
    assert result.attempt_count == 2
    assert result.model_call.id == repository.model_calls[1].id
    assert [call.attempt_number for call in repository.model_calls] == [1, 2]
    assert repository.model_calls[0].success is False
    assert repository.model_calls[1].success is True
    assert repository.model_calls[0].prompt_name == "databricks_qa"
    assert repository.model_calls[0].prompt_version == "1.0.1"
    assert repository.model_calls[0].artifact_type == "answer"
    assert repository.model_calls[0].artifact_valid is None
    assert repository.model_calls[0].artifact_error_code is None
    assert repository.model_calls[1].artifact_valid is True
    assert repository.model_calls[1].artifact_error_code is None
    assert repository.model_calls[0].invocation_id == repository.model_calls[1].invocation_id
    assert repository.events[-4:] == [
        "message:user",
        "model_call:1",
        "model_call:2",
        "message:assistant",
    ]
    assert gateway.received_messages[0].role == "system"
    assert "始终使用中文" in gateway.received_messages[0].content
    assert [message.content for message in gateway.received_messages[1:]] == [
        message.content for message in repository.messages[-21:-1]
    ]
    assert gateway.received_requested_model is ModelAlias.GPT_55
    assert len(trace_sink.traces) == 2
    assert [trace.attempt_number for trace in trace_sink.traces] == [1, 2]
    assert trace_sink.traces[0].response is None
    assert trace_sink.traces[0].error is not None
    assert trace_sink.traces[0].artifact_validation is None
    assert trace_sink.traces[1].response is not None
    assert trace_sink.traces[1].error is None
    assert trace_sink.traces[1].artifact_validation is not None
    assert trace_sink.traces[1].artifact_validation.valid is True
    assert trace_sink.traces[1].artifact_validation.violations == ()


@pytest.mark.asyncio
async def test_explicit_sql_prompt_persists_sql_artifact_audit() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
                content=VALID_SQL,
            )
        ]
    )
    service, trace_sink = build_service(repository, gateway)

    result = await service.send_message(
        session_id=session.id,
        content="生成销售汇总 SQL",
        requested_model=ModelAlias.GPT_55,
        requested_prompt=PromptName.SQL_GENERATION,
    )

    assert gateway.received_messages[0].role == "system"
    assert "语言标识为 `sql`" in gateway.received_messages[0].content
    assert result.prompt_name is PromptName.SQL_GENERATION
    assert result.prompt_version == "1.1.0"
    assert result.artifact.artifact_type is ArtifactType.SQL
    assert result.artifact.content == VALID_SQL
    assert result.assistant_message.artifact_type == "sql"
    assert repository.model_calls[0].prompt_name == "sql_generation"
    assert repository.model_calls[0].prompt_version == "1.1.0"
    assert repository.model_calls[0].artifact_type == "sql"
    assert repository.model_calls[0].artifact_valid is True
    assert repository.model_calls[0].artifact_error_code is None
    assert trace_sink.traces[0].prompt_name is PromptName.SQL_GENERATION
    assert trace_sink.traces[0].artifact_type is ArtifactType.SQL


@pytest.mark.asyncio
async def test_historical_system_messages_are_replaced_by_current_prompt() -> None:
    session = make_session()
    historical_messages = [
        make_message(session.id, "system", "旧系统提示", 0),
        make_message(session.id, "user", "历史问题", 1),
        make_message(session.id, "assistant", "历史回答", 2),
    ]
    repository = FakeChatRepository(session, historical_messages)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
            )
        ]
    )
    service, _ = build_service(repository, gateway)

    await service.send_message(session.id, "当前问题")

    assert [message.role for message in gateway.received_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "旧系统提示" not in {message.content for message in gateway.received_messages}


@pytest.mark.asyncio
async def test_standard_prompt_does_not_access_knowledge_dependencies() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
            )
        ]
    )
    status_provider = FakeKnowledgeStatusProvider(make_index_status(queryable=True))
    retriever = FakeKnowledgeRetriever(make_retrieval_bundle())
    service, _ = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=status_provider,
    )

    result = await service.send_message(session.id, "普通顾问问题")

    assert status_provider.calls == 0
    assert retriever.queries == []
    assert result.assistant_message.source_citations is None


@pytest.mark.asyncio
async def test_knowledge_prompt_retrieves_once_after_user_and_orders_messages() -> None:
    session = make_session()
    historical_messages = [
        make_message(session.id, "user", "历史问题", 0),
        make_message(session.id, "assistant", "历史回答", 1),
    ]
    repository = FakeChatRepository(session, historical_messages)
    bundle = make_retrieval_bundle()
    status_provider = FakeKnowledgeStatusProvider(
        make_index_status(queryable=True),
        events=repository.events,
    )
    retriever = FakeKnowledgeRetriever(bundle, events=repository.events)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
                content=VALID_KNOWLEDGE_ANSWER,
            )
        ]
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=status_provider,
    )

    result = await service.send_message(
        session_id=session.id,
        content="如何配置失败重试？",
        requested_prompt=PromptName.KNOWLEDGE_QA,
    )

    assert repository.events == [
        "message:user",
        "index_status",
        "retrieve",
        "model_call:1",
        "message:assistant",
    ]
    assert retriever.queries == ["如何配置失败重试？"]
    assert [message.role for message in gateway.received_messages] == [
        "system",
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in gateway.received_messages[1:]] == [
        bundle.context,
        "历史问题",
        "历史回答",
        "如何配置失败重试？",
    ]
    assert bundle.selected_chunks[0].content not in gateway.received_messages[0].content
    assert result.prompt_name is PromptName.KNOWLEDGE_QA
    assert result.prompt_version == "1.2.0"
    assert result.assistant_message.source_citations == [
        {
            "citation_id": "S1",
            "rank": 1,
            "title": "Configure Lakeflow Jobs",
            "url": "https://docs.databricks.com/aws/en/jobs/configure-job#retries",
            "heading": "Lakeflow Jobs > Configure retries",
            "chunk_id": "00000000-0000-0000-0000-000000000101",
            "chunk_hash": "1" * 64,
        }
    ]
    assert len(trace_sink.traces) == 1
    assert trace_sink.traces[0].retrieval is not None


@pytest.mark.asyncio
async def test_knowledge_prompt_stops_before_retrieval_when_index_is_not_ready() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    status_provider = FakeKnowledgeStatusProvider(make_index_status(queryable=False))
    retriever = FakeKnowledgeRetriever(make_retrieval_bundle())
    gateway = FakeModelGateway([])
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=status_provider,
    )

    with pytest.raises(AppError) as error:
        await service.send_message(
            session_id=session.id,
            content="如何配置失败重试？",
            requested_prompt=PromptName.KNOWLEDGE_QA,
        )

    assert error.value.code == "knowledge_index_not_ready"
    assert error.value.status_code == 503
    assert [message.role for message in repository.messages] == ["user"]
    assert repository.model_calls == []
    assert trace_sink.traces == []
    assert gateway.called is False
    assert status_provider.calls == 1
    assert retriever.queries == []


@pytest.mark.asyncio
async def test_knowledge_prompt_maps_missing_context_without_calling_model() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    retriever = FakeKnowledgeRetriever(error=KnowledgeContextNotFoundError("没有相关上下文。"))
    gateway = FakeModelGateway([])
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=FakeKnowledgeStatusProvider(make_index_status(queryable=True)),
    )

    with pytest.raises(AppError) as error:
        await service.send_message(
            session.id,
            "无关问题",
            requested_prompt=PromptName.KNOWLEDGE_QA,
        )

    assert error.value.code == "knowledge_context_not_found"
    assert error.value.status_code == 404
    assert [message.role for message in repository.messages] == ["user"]
    assert repository.model_calls == []
    assert trace_sink.traces == []
    assert gateway.called is False


@pytest.mark.asyncio
async def test_embedding_failure_does_not_start_chat_fallback() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    retriever = FakeKnowledgeRetriever(error=EmbeddingRequestError("Embedding 失败。"))
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
            ),
        ]
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=FakeKnowledgeStatusProvider(make_index_status(queryable=True)),
    )

    with pytest.raises(AppError) as error:
        await service.send_message(
            session.id,
            "如何配置失败重试？",
            requested_prompt=PromptName.KNOWLEDGE_QA,
        )

    assert error.value.code == "embedding_request_failed"
    assert error.value.status_code == 502
    assert gateway.called is False
    assert repository.model_calls == []
    assert trace_sink.traces == []


@pytest.mark.asyncio
async def test_chat_fallback_reuses_one_retrieval_bundle() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    bundle = make_retrieval_bundle()
    retriever = FakeKnowledgeRetriever(bundle)
    invocation_id = uuid4()
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
                content=VALID_KNOWLEDGE_ANSWER,
            ),
        ]
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=retriever,
        knowledge_status_provider=FakeKnowledgeStatusProvider(make_index_status(queryable=True)),
    )

    await service.send_message(
        session.id,
        "如何配置失败重试？",
        requested_prompt=PromptName.KNOWLEDGE_QA,
    )

    assert retriever.queries == ["如何配置失败重试？"]
    assert len(trace_sink.traces) == 2
    assert trace_sink.traces[0].retrieval is trace_sink.traces[1].retrieval


@pytest.mark.asyncio
async def test_rag_artifact_failure_does_not_persist_assistant_or_citations() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
                content="# 缺少固定章节",
            )
        ]
    )
    service, trace_sink = build_service(
        repository,
        gateway,
        knowledge_retriever=FakeKnowledgeRetriever(make_retrieval_bundle()),
        knowledge_status_provider=FakeKnowledgeStatusProvider(make_index_status(queryable=True)),
    )

    with pytest.raises(AppError) as error:
        await service.send_message(
            session.id,
            "如何配置失败重试？",
            requested_prompt=PromptName.KNOWLEDGE_QA,
        )

    assert error.value.code == "artifact_invalid"
    assert [message.role for message in repository.messages] == ["user"]
    assert repository.model_calls[0].artifact_valid is False
    assert trace_sink.traces[0].retrieval is not None


@pytest.mark.asyncio
async def test_invalid_artifact_is_audited_without_assistant_message_or_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = make_session()
    invalid_content = "# 不完整且不应写入日志的回答"
    invocation_id = uuid4()
    repository = FakeChatRepository(session)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=True,
                content=invalid_content,
            )
        ]
    )
    service, trace_sink = build_service(repository, gateway)

    with caplog.at_level(logging.WARNING), pytest.raises(AppError) as error:
        await service.send_message(session.id, "生成分析建议")

    assert error.value.code == "artifact_invalid"
    assert error.value.status_code == 502
    assert [message.role for message in repository.messages] == ["user"]
    assert gateway.yielded_attempts == 1
    assert len(repository.model_calls) == 1
    assert repository.model_calls[0].artifact_valid is False
    assert repository.model_calls[0].artifact_error_code == "artifact_invalid"
    assert len(trace_sink.traces) == 1
    assert trace_sink.traces[0].artifact_validation is not None
    assert trace_sink.traces[0].artifact_validation.valid is False
    assert "missing_section" in trace_sink.traces[0].artifact_validation.violations
    assert "databricks_qa" in caplog.text
    assert str(invocation_id) in caplog.text
    assert "missing_section" in caplog.text
    assert invalid_content not in caplog.text


@pytest.mark.asyncio
async def test_database_failure_does_not_resume_gateway_fallback() -> None:
    session = make_session()
    invocation_id = uuid4()
    repository = FakeChatRepository(session, fail_model_call_number=1)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            ),
            make_attempt(
                invocation_id=invocation_id,
                model_alias=ModelAlias.GPT_54_MINI,
                attempt_number=2,
                success=True,
            ),
        ]
    )
    service, trace_sink = build_service(repository, gateway)

    with pytest.raises(RuntimeError, match="数据库写入失败"):
        await service.send_message(session.id, "测试", ModelAlias.GPT_55)

    assert gateway.resumed is False
    assert [message.role for message in repository.messages] == ["user"]
    assert repository.model_calls == []
    assert trace_sink.traces == []


@pytest.mark.asyncio
async def test_non_retryable_failure_maps_gateway_failure_to_app_error() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    attempt = make_attempt(
        invocation_id=uuid4(),
        model_alias=ModelAlias.GPT_55,
        attempt_number=1,
        success=False,
        error_code="model_authentication_failed",
        error_message="模型认证或权限校验失败。",
    )
    gateway = FakeModelGateway(
        [attempt],
        failure=ModelGatewayFailure(
            "model_authentication_failed",
            "模型认证或权限校验失败。",
            503,
        ),
    )
    service, trace_sink = build_service(repository, gateway)

    with pytest.raises(AppError) as error:
        await service.send_message(session.id, "测试认证", ModelAlias.GPT_55)

    assert error.value.code == "model_authentication_failed"
    assert error.value.status_code == 503
    assert [message.role for message in repository.messages] == ["user"]
    assert len(repository.model_calls) == 1
    assert len(trace_sink.traces) == 1
    assert trace_sink.traces[0].error == attempt.error


@pytest.mark.asyncio
async def test_all_retryable_failures_are_persisted_before_exhaustion_error() -> None:
    session = make_session()
    invocation_id = uuid4()
    repository = FakeChatRepository(session)
    attempts = [
        make_attempt(
            invocation_id=invocation_id,
            model_alias=ModelAlias.GPT_55,
            attempt_number=1,
            success=False,
            retryable=True,
        ),
        make_attempt(
            invocation_id=invocation_id,
            model_alias=ModelAlias.GPT_54_MINI,
            attempt_number=2,
            success=False,
            retryable=True,
        ),
    ]
    gateway = FakeModelGateway(
        attempts,
        failure=ModelGatewayFailure(
            "model_fallback_exhausted",
            "模型调用失败，请稍后重试。",
            502,
        ),
    )
    service, trace_sink = build_service(repository, gateway)

    with pytest.raises(AppError) as error:
        await service.send_message(session.id, "测试耗尽", ModelAlias.GPT_55)

    assert error.value.code == "model_fallback_exhausted"
    assert error.value.status_code == 502
    assert [message.role for message in repository.messages] == ["user"]
    assert [call.attempt_number for call in repository.model_calls] == [1, 2]
    assert len(trace_sink.traces) == 2


@pytest.mark.asyncio
async def test_gateway_ending_without_success_is_an_internal_contract_error() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    gateway = FakeModelGateway(
        [
            make_attempt(
                invocation_id=uuid4(),
                model_alias=ModelAlias.GPT_55,
                attempt_number=1,
                success=False,
                retryable=True,
            )
        ]
    )
    service, _ = build_service(repository, gateway)

    with pytest.raises(RuntimeError, match="模型网关未返回成功尝试"):
        await service.send_message(session.id, "测试内部契约")


@pytest.mark.asyncio
async def test_send_message_rejects_missing_session_before_persisting() -> None:
    missing_session_id = uuid4()
    repository = FakeChatRepository(None)
    gateway = FakeModelGateway([])
    service, trace_sink = build_service(repository, gateway)

    with pytest.raises(AppError) as error:
        await service.send_message(missing_session_id, "不会保存")

    assert error.value.code == "session_not_found"
    assert repository.messages == []
    assert repository.model_calls == []
    assert trace_sink.traces == []
    assert gateway.called is False
