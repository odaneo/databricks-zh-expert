from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.db.models import ChatSession, Message, ModelCall
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import (
    ModelAttempt,
    ModelGateway,
    ModelGatewayFailure,
)
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.observability.model_trace import ModelCallTrace, ModelTraceSink

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_session() -> ChatSession:
    return ChatSession(
        id=uuid4(),
        title="测试会话",
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
    content: str = "这是一个 Markdown 回答。",
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
    ) -> Message:
        message = make_message(session_id, role, content, len(self.messages))
        message.artifact_type = artifact_type
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
            yield attempt
        if self.failure is not None:
            raise self.failure


class FakeModelTraceSink:
    def __init__(self) -> None:
        self.traces: list[ModelCallTrace] = []

    async def write(self, trace: ModelCallTrace) -> None:
        self.traces.append(trace)


def build_service(
    repository: FakeChatRepository,
    model_gateway: FakeModelGateway,
    trace_sink: FakeModelTraceSink | None = None,
) -> tuple[ChatService, FakeModelTraceSink]:
    trace_sink = trace_sink or FakeModelTraceSink()
    service = ChatService(
        cast(ChatRepository, repository),
        cast(ModelGateway, model_gateway),
        cast(ModelTraceSink, trace_sink),
    )
    return service, trace_sink


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
    assert result.assistant_message.content == "这是一个 Markdown 回答。"
    assert result.assistant_message.artifact_type == "answer"
    assert result.model_invocation_id == invocation_id
    assert result.requested_model is ModelAlias.GPT_55
    assert result.used_model is ModelAlias.GPT_54_MINI
    assert result.fallback_used is True
    assert result.attempt_count == 2
    assert result.model_call.id == repository.model_calls[1].id
    assert [call.attempt_number for call in repository.model_calls] == [1, 2]
    assert repository.model_calls[0].success is False
    assert repository.model_calls[1].success is True
    assert repository.model_calls[0].invocation_id == repository.model_calls[1].invocation_id
    assert repository.events[-4:] == [
        "message:user",
        "model_call:1",
        "model_call:2",
        "message:assistant",
    ]
    assert [message.content for message in gateway.received_messages] == [
        message.content for message in repository.messages[-21:-1]
    ]
    assert gateway.received_requested_model is ModelAlias.GPT_55
    assert len(trace_sink.traces) == 2
    assert [trace.attempt_number for trace in trace_sink.traces] == [1, 2]
    assert trace_sink.traces[0].response is None
    assert trace_sink.traces[0].error is not None
    assert trace_sink.traces[1].response is not None
    assert trace_sink.traces[1].error is None


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
