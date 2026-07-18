from collections.abc import AsyncIterator
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
from databricks_zh_expert.db.models import ModelCall
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.types import WorkspaceDefinition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

VALID_DDL = """```sql
CREATE TABLE IF NOT EXISTS retail.bronze.customers_cdc (
  customer_id BIGINT,
  source_operation STRING,
  source_commit_ts TIMESTAMP
) USING DELTA;
```"""


class WorkspaceContextService:
    def __init__(self) -> None:
        self.builder = WorkspaceContextBuilder()

    async def build(
        self,
        query: str,
        *,
        prompt_spec,
        expert_profile: str,
        workspace: WorkspaceDefinition | None = None,
    ) -> ChatContextBundle:
        del expert_profile
        workspace_context = (
            self.builder.build_for_prompt(
                query,
                workspace=workspace,
                prompt_name=prompt_spec.name.value,
            )
            if prompt_spec.use_workspace_context and workspace is not None
            else None
        )
        return ChatContextBundle(
            expert=None,
            official=None,
            workspace=workspace_context,
        )


class FakeModelGateway:
    def __init__(self) -> None:
        self.messages: list[ModelMessage] = []

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        self.messages = messages
        yield ModelAttempt(
            invocation_id=uuid4(),
            requested_model=requested_model or ModelAlias.DEEPSEEK_V4_FLASH,
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
                "object": "chat.completion",
                "model": "deepseek/deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": VALID_DDL},
                        "finish_reason": "stop",
                    }
                ],
            },
            content=VALID_DDL,
            prompt_tokens=100,
            completion_tokens=40,
            latency_ms=25,
            success=True,
            retryable=False,
            error=None,
        )


async def test_workspace_ddl_request_persists_proposal_context_and_relative_paths(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    gateway = FakeModelGateway()
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    test_app.dependency_overrides[get_chat_context_service] = WorkspaceContextService
    create_response = await client.post(
        "/api/chat/sessions",
        json={
            "title": "客户 CDC DDL",
            "workspace_id": "retail_sales_demo",
        },
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "根据 public.customers 生成客户 CDC Databricks DDL",
            "prompt": "ddl_generation",
        },
    )

    assert response.status_code == 201
    assert response.json()["artifact"]["project_fact_status"] == "proposal"
    assert "仅来自用户提供的全新项目事实" in gateway.messages[1].content
    assert gateway.messages[-1].content == "根据 public.customers 生成客户 CDC Databricks DDL"
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.workspace_id == "retail_sales_demo"
    assert model_call.workspace_mode == "greenfield"
    assert model_call.project_fact_status == "proposal"
    assert model_call.workspace_context
    assert all(
        not str(selection["source_path"]).startswith(("C:\\", "/"))
        for selection in model_call.workspace_context
    )
