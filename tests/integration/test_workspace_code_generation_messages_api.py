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
from databricks_zh_expert.artifacts.markdown import MAPPING_CSV_HEADER
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
VALID_SQL = """```sql
SELECT business_date, SUM(net_amount) AS daily_sales
FROM retail.silver.sales
GROUP BY business_date;
```"""
VALID_MAPPING = (
    f"```csv\n{MAPPING_CSV_HEADER}\n"
    "map_customer_id,public.customer,customer_id,retail.silver.customer,customer_id,,,,,\n```"
)
VALID_PYSPARK = """```python
from pyspark.sql import functions as F

source_df = spark.readStream.table("retail.bronze.customer_cdc")
clean_df = source_df.withColumn("ingested_at", F.current_timestamp())
```"""
VALID_NOTEBOOK = """```python
# Databricks notebook source
from pyspark.sql import functions as F

# COMMAND ----------
events_df = spark.readStream.table("retail.bronze.order_event")
display(events_df.select(F.col("order_id")))
```"""
VALID_ANSWER = """# Databricks 建议

## 结论
使用 Delta Lake。

## 适用场景
需要可靠批流处理的项目。

## 详细说明
根据业务 SLA 选择批处理或流处理。

## 注意事项
先确认数据质量规则。

## 人工确认事项
确认源系统与目标延迟。"""


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
    def __init__(self, response_content: str = VALID_DDL) -> None:
        self.messages: list[ModelMessage] = []
        self.response_content = response_content

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
                        "message": {
                            "role": "assistant",
                            "content": self.response_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
            content=self.response_content,
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
            "workspace_id": "northwind_psql",
        },
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "根据 orders 生成订单 CDC Databricks DDL",
            "prompt": "ddl_generation",
        },
    )

    assert response.status_code == 201
    assert response.json()["artifact"]["project_fact_status"] == "proposal"
    assert "仅来自用户提供的全新项目事实" in gateway.messages[1].content
    assert gateway.messages[-1].content == "根据 orders 生成订单 CDC Databricks DDL"
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.workspace_id == "northwind_psql"
    assert not hasattr(model_call, "workspace_mode")
    assert model_call.project_fact_status == "proposal"
    assert model_call.workspace_context
    assert all(
        not str(selection["source_path"]).startswith(("C:\\", "/"))
        for selection in model_call.workspace_context
    )


@pytest.mark.parametrize(
    ("prompt", "response_content", "expected_artifact_type"),
    (
        ("ddl_generation", VALID_DDL, "sql"),
        ("mapping_generation", VALID_MAPPING, "csv"),
        ("sql_generation", VALID_SQL, "sql"),
        ("pyspark_generation", VALID_PYSPARK, "pyspark"),
        ("notebook_generation", VALID_NOTEBOOK, "notebook"),
    ),
)
async def test_all_workspace_generation_artifacts_are_proposals(
    prompt: str,
    response_content: str,
    expected_artifact_type: str,
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    gateway = FakeModelGateway(response_content)
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    test_app.dependency_overrides[get_chat_context_service] = WorkspaceContextService
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": prompt, "workspace_id": "northwind_psql"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "根据 orders 生成项目提案", "prompt": prompt},
    )

    assert response.status_code == 201
    assert response.json()["artifact"]["type"] == expected_artifact_type
    assert response.json()["artifact"]["project_fact_status"] == "proposal"
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.project_fact_status == "proposal"
    assert model_call.workspace_context


async def test_bound_workspace_is_not_injected_for_normal_prompt(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    gateway = FakeModelGateway(VALID_ANSWER)
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    test_app.dependency_overrides[get_chat_context_service] = WorkspaceContextService
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "普通问答", "workspace_id": "northwind_psql"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "解释 Delta Lake", "prompt": "databricks_qa"},
    )

    assert response.status_code == 201
    assert all("仅来自用户提供的全新项目事实" not in item.content for item in gateway.messages)
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.workspace_id == "northwind_psql"
    assert model_call.workspace_context == []
    assert model_call.project_fact_status is None


async def test_proposal_without_workspace_keeps_generic_generation_behavior(
    client: AsyncClient,
    test_app: FastAPI,
    test_db_session: AsyncSession,
) -> None:
    gateway = FakeModelGateway(VALID_SQL)
    test_app.dependency_overrides[get_model_gateway] = lambda: gateway
    test_app.dependency_overrides[get_chat_context_service] = WorkspaceContextService
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "无 Workspace SQL"},
    )
    session_id = UUID(create_response.json()["id"])

    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "生成每日销售 SQL", "prompt": "sql_generation"},
    )

    assert response.status_code == 201
    assert response.json()["artifact"]["project_fact_status"] == "proposal"
    assert len(gateway.messages) == 2
    model_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.session_id == session_id)
    )
    assert model_call is not None
    assert model_call.workspace_id is None
    assert model_call.workspace_context is None
    assert model_call.project_fact_status == "proposal"
