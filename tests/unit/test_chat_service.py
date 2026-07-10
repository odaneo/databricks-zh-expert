from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.db.models import ChatSession, Message, ModelCall
from databricks_zh_expert.llm.client import ModelClient, ModelMessage, ModelResult
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


class FakeChatRepository:
    def __init__(self, session: ChatSession | None, messages: list[Message] | None = None) -> None:
        self.session = session
        self.messages = list(messages or [])
        self.model_calls: list[ModelCall] = []
        self.events: list[str] = []

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
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
        success: bool,
        error_message: str | None,
    ) -> ModelCall:
        model_call = ModelCall(
            id=uuid4(),
            session_id=session_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
            created_at=NOW,
        )
        self.model_calls.append(model_call)
        self.events.append("model_call")
        return model_call


class FakeModelClient:
    provider = "deepseek"
    model = "deepseek/deepseek-v4-flash"

    def __init__(
        self,
        repository: FakeChatRepository,
        *,
        error: Exception | None = None,
    ) -> None:
        self.repository = repository
        self.error = error
        self.received_messages: list[ModelMessage] = []

    async def complete(self, messages: list[ModelMessage]) -> ModelResult:
        self.repository.events.append("model")
        self.received_messages = messages
        if self.error is not None:
            raise self.error
        return ModelResult(
            content="这是一个 Markdown 回答。",
            provider=self.provider,
            model=self.model,
            prompt_tokens=12,
            completion_tokens=8,
            api_response={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1767225600,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "这是一个 Markdown 回答。",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                },
            },
        )


class FakeModelTraceSink:
    def __init__(self) -> None:
        self.traces: list[ModelCallTrace] = []

    async def write(self, trace: ModelCallTrace) -> None:
        self.traces.append(trace)


def build_service(
    repository: FakeChatRepository,
    model_client: FakeModelClient,
    trace_sink: FakeModelTraceSink | None = None,
) -> tuple[ChatService, FakeModelTraceSink]:
    trace_sink = trace_sink or FakeModelTraceSink()
    service = ChatService(
        cast(ChatRepository, repository),
        cast(ModelClient, model_client),
        cast(ModelTraceSink, trace_sink),
    )
    return service, trace_sink


@pytest.mark.asyncio
async def test_send_message_persists_reply_and_model_call() -> None:
    session = make_session()
    historical_messages = [
        make_message(session.id, "user" if index % 2 == 0 else "assistant", f"历史 {index}", index)
        for index in range(25)
    ]
    repository = FakeChatRepository(session, historical_messages)
    model_client = FakeModelClient(repository)
    service, trace_sink = build_service(repository, model_client)

    result = await service.send_message(session.id, "设计一个销售工作流")

    assert result.user_message.content == "设计一个销售工作流"
    assert result.assistant_message.content == "这是一个 Markdown 回答。"
    assert [message.content for message in model_client.received_messages] == [
        message.content for message in repository.messages[-21:-1]
    ]
    assert repository.events[-4:] == [
        "message:user",
        "model",
        "message:assistant",
        "model_call",
    ]
    assert result.model_call.success is True
    assert result.model_call.latency_ms >= 0
    trace = trace_sink.traces[0]
    assert trace.model_call_id == result.model_call.id
    assert trace.session_id == session.id
    assert trace.request == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [
            {"role": message.role, "content": message.content}
            for message in model_client.received_messages
        ],
    }
    assert trace.response == {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1767225600,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "这是一个 Markdown 回答。",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }
    assert trace.error is None
    assert trace.success is True


@pytest.mark.asyncio
async def test_send_message_trace_uses_exact_messages_sent_to_model() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    model_client = FakeModelClient(repository)
    service, trace_sink = build_service(repository, model_client)

    await service.send_message(session.id, "设计一个销售工作流")

    assert trace_sink.traces[0].request["messages"] == [
        {"role": message.role, "content": message.content}
        for message in model_client.received_messages
    ]


@pytest.mark.asyncio
async def test_send_message_records_safe_failure_without_assistant_message() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    model_client = FakeModelClient(
        repository,
        error=RuntimeError("请求失败，密钥是 sk-sensitive-value"),
    )
    service, trace_sink = build_service(repository, model_client)

    with pytest.raises(AppError) as error:
        await service.send_message(session.id, "测试失败")

    assert error.value.code == "model_request_failed"
    assert [message.role for message in repository.messages] == ["user"]
    assert repository.model_calls[0].success is False
    assert repository.model_calls[0].error_message is not None
    assert "sk-sensitive-value" not in repository.model_calls[0].error_message
    trace = trace_sink.traces[0]
    assert trace.model_call_id == repository.model_calls[0].id
    assert trace.response is None
    assert trace.success is False
    assert trace.error == {
        "message": "模型调用失败，请稍后重试。",
        "type": "RuntimeError",
        "param": None,
        "code": "model_request_failed",
    }
    assert "sk-sensitive-value" not in str(trace.error)


@pytest.mark.asyncio
async def test_send_message_preserves_model_not_configured_error() -> None:
    session = make_session()
    repository = FakeChatRepository(session)
    expected_error = AppError(
        code="model_not_configured",
        message="当前模型尚未配置 API 密钥。",
        status_code=503,
    )
    service, trace_sink = build_service(
        repository,
        FakeModelClient(repository, error=expected_error),
    )

    with pytest.raises(AppError) as error:
        await service.send_message(session.id, "测试配置")

    assert error.value is expected_error
    assert repository.model_calls[0].success is False
    assert trace_sink.traces[0].error == {
        "message": "当前模型尚未配置 API 密钥。",
        "type": "AppError",
        "param": None,
        "code": "model_not_configured",
    }


@pytest.mark.asyncio
async def test_send_message_rejects_missing_session_before_persisting() -> None:
    missing_session_id = uuid4()
    repository = FakeChatRepository(None)
    model_client = FakeModelClient(repository)
    service, trace_sink = build_service(repository, model_client)

    with pytest.raises(AppError) as error:
        await service.send_message(missing_session_id, "不会保存")

    assert error.value.code == "session_not_found"
    assert repository.messages == []
    assert repository.model_calls == []
    assert trace_sink.traces == []
