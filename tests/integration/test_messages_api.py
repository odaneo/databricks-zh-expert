from collections.abc import AsyncIterator, Iterator
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
from databricks_zh_expert.chat.context import ChatContextBundle
from databricks_zh_expert.core.errors import KnowledgeIndexNotReadyAppError
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.workspace.types import WorkspaceDefinition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

VALID_ANSWER = """# Databricks 工作流建议

## 结论
建议使用 Bronze、Silver、Gold 三层工作流。

## 适用场景
每日销售分析。

## 详细说明
按数据质量和业务口径逐层处理。

## 注意事项
需要监控数据延迟与失败重试。

## 人工确认事项
确认数据源和调度时间。"""
VALID_SQL = """```sql
-- 汇总每日销售额
SELECT business_date, SUM(amount) AS total_amount
FROM silver_sales
GROUP BY business_date;
```"""


class FakeModelGateway:
    def __init__(self) -> None:
        self.invocation_id = uuid4()
        self.requested_models: list[ModelAlias | None] = []
        self.system_messages: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.requested_models)

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.requested_models.append(requested_model)
        assert messages[0].role == "system"
        assert "始终使用中文" in messages[0].content
        self.system_messages.append(messages[0].content)
        assert messages[-1].content == "设计一个销售工作流"
        response_content = VALID_SQL if "语言标识为 `sql`" in messages[0].content else VALID_ANSWER

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
                            "content": response_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
            content=response_content,
            prompt_tokens=20,
            completion_tokens=15,
            latency_ms=125,
            success=True,
            retryable=False,
            error=None,
        )


class FakeChatContextService:
    async def build(
        self,
        query: str,
        *,
        prompt_spec,
        expert_profile: str,
        workspace: WorkspaceDefinition | None = None,
    ) -> ChatContextBundle:
        del query, expert_profile, workspace
        if prompt_spec.name.value == "knowledge_qa":
            raise KnowledgeIndexNotReadyAppError()
        return ChatContextBundle(expert=None, official=None)


@pytest.fixture(autouse=True)
def override_chat_context_service(test_app: FastAPI) -> Iterator[None]:
    test_app.dependency_overrides[get_chat_context_service] = FakeChatContextService
    try:
        yield
    finally:
        test_app.dependency_overrides.pop(get_chat_context_service, None)


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
    assert payload["assistant_message"]["content"] == VALID_ANSWER
    assert payload["assistant_message"]["artifact_type"] == "answer"
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
    assert [call.prompt_name for call in saved_model_calls] == [
        "databricks_qa",
        "databricks_qa",
    ]
    assert [call.prompt_version for call in saved_model_calls] == ["1.0.1", "1.0.1"]
    assert [call.artifact_type for call in saved_model_calls] == ["answer", "answer"]
    assert [call.artifact_valid for call in saved_model_calls] == [None, True]
    assert [call.artifact_error_code for call in saved_model_calls] == [None, None]


async def test_send_message_accepts_sql_prompt_and_returns_artifact_metadata(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "SQL 生成"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "设计一个销售工作流",
            "prompt": "sql_generation",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["prompt_name"] == "sql_generation"
    assert payload["prompt_version"] == "1.1.0"
    assert payload["artifact"] == {
        "type": "sql",
        "format": "markdown",
        "title": "Databricks SQL",
        "project_fact_status": "proposal",
    }
    assert payload["assistant_message"]["content"] == VALID_SQL
    assert payload["assistant_message"]["artifact_type"] == "sql"
    assert "content" not in payload["artifact"]
    assert "语言标识为 `sql`" in fake_gateway.system_messages[0]


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
    assert response.json()["prompt_name"] == "databricks_qa"
    assert response.json()["prompt_version"] == "1.0.1"
    assert response.json()["artifact"] == {
        "type": "answer",
        "format": "markdown",
        "title": "Databricks 工作流建议",
        "project_fact_status": None,
    }


async def test_send_message_rejects_unknown_prompt_before_calling_gateway(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway

    response = await client.post(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "测试", "prompt": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert fake_gateway.called is False


async def test_knowledge_message_requires_index_and_keeps_user_message(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    fake_gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: fake_gateway
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "知识库问答"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "设计一个销售工作流",
            "prompt": "knowledge_qa",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "knowledge_index_not_ready"
    assert fake_gateway.called is False
    detail_response = await client.get(f"/api/chat/sessions/{session_id}")
    assert [
        (message["role"], message["content"], message["source_citations"])
        for message in detail_response.json()["messages"]
    ] == [("user", "设计一个销售工作流", None)]


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
