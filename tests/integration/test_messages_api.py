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
        self.requested_models: list[ModelAlias | None] = []

    @property
    def called(self) -> bool:
        return bool(self.requested_models)

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.requested_models.append(requested_model)
        assert messages[-1].content == "设计一个销售工作流"

        if requested_model is ModelAlias.GPT_55:
            yield ModelAttempt(
                invocation_id=self.invocation_id,
                requested_model=ModelAlias.GPT_55,
                model_alias=ModelAlias.GPT_55,
                provider=ModelProvider.OPENAI,
                litellm_model="openai/gpt-5.5",
                attempt_number=1,
                request={
                    "model": "openai/gpt-5.5",
                    "messages": [
                        {"role": message.role, "content": message.content} for message in messages
                    ],
                },
                response=None,
                content=None,
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=80,
                success=False,
                retryable=True,
                error={
                    "message": "请求过于频繁。",
                    "type": "rate_limit_error",
                    "param": None,
                    "code": "rate_limit",
                },
            )
            used_model = ModelAlias.GPT_54_MINI
            provider = ModelProvider.OPENAI
            litellm_model = "openai/gpt-5.4-mini"
            attempt_number = 2
        else:
            used_model = ModelAlias.DEEPSEEK_V4_FLASH
            provider = ModelProvider.DEEPSEEK
            litellm_model = "deepseek/deepseek-v4-flash"
            attempt_number = 1

        yield ModelAttempt(
            invocation_id=self.invocation_id,
            requested_model=requested_model or ModelAlias.DEEPSEEK_V4_FLASH,
            model_alias=used_model,
            provider=provider,
            litellm_model=litellm_model,
            attempt_number=attempt_number,
            request={
                "model": litellm_model,
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


async def test_send_message_supports_requested_model_and_persists_fallback_attempts(
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
        json={"content": "设计一个销售工作流", "model": "gpt5.5"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["session_id"] == str(session_id)
    assert payload["user_message"]["content"] == "设计一个销售工作流"
    assert payload["assistant_message"]["content"].startswith("## 工作流方案")
    assert payload["model_invocation_id"] == str(fake_gateway.invocation_id)
    assert payload["requested_model"] == "gpt5.5"
    assert payload["used_model"] == "gpt5.4mini"
    assert payload["fallback_used"] is True
    assert payload["attempt_count"] == 2
    assert fake_gateway.requested_models == [ModelAlias.GPT_55]

    detail_response = await client.get(f"/api/chat/sessions/{session_id}")
    assert [message["role"] for message in detail_response.json()["messages"]] == [
        "user",
        "assistant",
    ]

    model_calls = await test_db_session.scalars(
        select(ModelCall)
        .where(ModelCall.session_id == session_id)
        .order_by(ModelCall.attempt_number)
    )
    saved_model_calls = list(model_calls.all())
    assert len(saved_model_calls) == 2
    assert str(saved_model_calls[1].id) == payload["model_call_id"]
    assert {call.invocation_id for call in saved_model_calls} == {fake_gateway.invocation_id}
    assert [call.model_alias for call in saved_model_calls] == [
        ModelAlias.GPT_55,
        ModelAlias.GPT_54_MINI,
    ]
    assert [call.success for call in saved_model_calls] == [False, True]
    assert [call.retryable for call in saved_model_calls] == [True, False]
    assert saved_model_calls[0].error_code == "rate_limit"
    assert saved_model_calls[1].error_code is None


async def test_send_message_passes_none_when_model_is_omitted(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "默认模型测试"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "设计一个销售工作流"},
    )

    assert response.status_code == 201
    assert fake_gateway.requested_models == [None]
    assert response.json()["requested_model"] == "deepseek-v4-flash"
    assert response.json()["used_model"] == "deepseek-v4-flash"
    assert response.json()["fallback_used"] is False
    assert response.json()["attempt_count"] == 1


async def test_send_message_rejects_unknown_model_before_calling_gateway(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "测试", "model": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert fake_gateway.called is False


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
