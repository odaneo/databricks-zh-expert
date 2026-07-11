from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.api.dependencies import get_model_gateway
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FakeModelGateway:
    def __init__(self) -> None:
        self.invocation_id = uuid4()
        self.called = False

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.called = True
        assert messages[-1].content == "设计一个销售工作流"
        assert requested_model is None
        yield ModelAttempt(
            invocation_id=self.invocation_id,
            requested_model=ModelAlias.DEEPSEEK_V4_FLASH,
            model_alias=ModelAlias.DEEPSEEK_V4_FLASH,
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
                "id": "chatcmpl-integration-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "## 工作流方案\n\n使用 Bronze、Silver、Gold 三层。",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
            content="## 工作流方案\n\n使用 Bronze、Silver、Gold 三层。",
            prompt_tokens=20,
            completion_tokens=15,
            latency_ms=125,
            success=True,
            retryable=False,
            error=None,
        )


async def test_send_message_persists_messages_and_model_call(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "销售工作流"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "设计一个销售工作流"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["session_id"] == str(session_id)
    assert payload["user_message"]["content"] == "设计一个销售工作流"
    assert payload["assistant_message"]["content"].startswith("## 工作流方案")

    detail_response = await client.get(f"/api/chat/sessions/{session_id}")
    assert [message["role"] for message in detail_response.json()["messages"]] == [
        "user",
        "assistant",
    ]

    model_calls = await test_db_session.scalars(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    saved_model_call = model_calls.one()
    assert str(saved_model_call.id) == payload["model_call_id"]
    assert saved_model_call.invocation_id == fake_gateway.invocation_id
    assert saved_model_call.model_alias == ModelAlias.DEEPSEEK_V4_FLASH
    assert saved_model_call.attempt_number == 1
    assert saved_model_call.success is True
    assert saved_model_call.retryable is False
    assert saved_model_call.error_code is None


async def test_send_message_rejects_missing_session(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "测试"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
    assert fake_gateway.called is False


async def test_send_message_rejects_empty_content(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": ""},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert fake_gateway.called is False
