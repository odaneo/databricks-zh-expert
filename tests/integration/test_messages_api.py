from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.api.dependencies import get_model_client
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.llm.client import ModelMessage, ModelResult

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FakeModelClient:
    provider = "deepseek"
    model = "deepseek/deepseek-v4-flash"

    async def complete(self, messages: list[ModelMessage]) -> ModelResult:
        assert messages[-1].content == "设计一个销售工作流"
        return ModelResult(
            content="## 工作流方案\n\n使用 Bronze、Silver、Gold 三层。",
            provider=self.provider,
            model=self.model,
            prompt_tokens=20,
            completion_tokens=15,
        )


async def test_send_message_persists_messages_and_model_call(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    test_app.dependency_overrides[get_model_client] = lambda: FakeModelClient()
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
    assert saved_model_call.success is True


async def test_send_message_rejects_missing_session(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    test_app.dependency_overrides[get_model_client] = lambda: FakeModelClient()

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "测试"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


async def test_send_message_rejects_empty_content(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    test_app.dependency_overrides[get_model_client] = lambda: FakeModelClient()

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": ""},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
