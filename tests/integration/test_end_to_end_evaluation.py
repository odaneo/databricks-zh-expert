import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.api.dependencies import (
    get_chat_context_service,
    get_model_gateway,
)
from databricks_zh_expert.chat.context import ChatContextBundle
from databricks_zh_expert.db.models import ChatSession, ModelCall
from databricks_zh_expert.evaluation.dataset import (
    END_TO_END_EVALUATION_PATH,
    load_evaluation_dataset,
)
from databricks_zh_expert.evaluation.runner import EvaluationRunner
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.gateway import ModelAttempt
from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider
from databricks_zh_expert.main import create_app
from databricks_zh_expert.observability.model_trace import ModelTraceSink
from databricks_zh_expert.rag.context import (
    KnowledgeContextBuilder,
    RankedKnowledgeChunk,
)
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.types import WorkspaceDefinition

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

VALID_DAILY_SALES_SQL = """```sql
-- HALF_UP 四位小数由 Databricks SQL ROUND 对 DECIMAL 值完成。
CREATE OR REPLACE VIEW gold.daily_sales AS
WITH line_amounts AS (
  SELECT
    o.order_id,
    o.shipped_date AS sales_date,
    o.freight,
    CAST(ROUND(
      CAST(od.unit_price AS DECIMAL(18, 4))
      * CAST(od.quantity AS DECIMAL(18, 4))
      * (1 - CAST(od.discount AS DECIMAL(9, 6))),
      4
    ) AS DECIMAL(20, 4)) AS line_net_sales
  FROM orders AS o
  JOIN order_details AS od ON o.order_id = od.order_id
  WHERE o.shipped_date IS NOT NULL
),
order_totals AS (
  SELECT
    order_id,
    sales_date,
    MAX(freight) AS freight,
    SUM(line_net_sales) AS order_net_sales
  FROM line_amounts
  GROUP BY order_id, sales_date
)
SELECT
  sales_date,
  SUM(order_net_sales) AS net_sales,
  SUM(COALESCE(freight, 0)) AS freight_amount,
  SUM(CASE WHEN freight IS NULL THEN 1 ELSE 0 END) AS freight_missing_order_count
FROM order_totals
GROUP BY sales_date;
```"""


class FakeModelGateway:
    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        resolved = requested_model or ModelAlias.DEEPSEEK_V4_FLASH
        yield ModelAttempt(
            invocation_id=uuid4(),
            requested_model=resolved,
            model_alias=resolved,
            provider=ModelProvider.DEEPSEEK,
            litellm_model=f"deepseek/{resolved.value}",
            attempt_number=1,
            request={
                "model": f"deepseek/{resolved.value}",
                "messages": [
                    {"role": message.role, "content": message.content} for message in messages
                ],
            },
            response={
                "object": "chat.completion",
                "model": f"deepseek/{resolved.value}",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": VALID_DAILY_SALES_SQL},
                        "finish_reason": "stop",
                    }
                ],
            },
            content=VALID_DAILY_SALES_SQL,
            prompt_tokens=120,
            completion_tokens=60,
            latency_ms=25,
            success=True,
            retryable=False,
            error=None,
        )


class FakeChatContextService:
    def __init__(self) -> None:
        chunk = RankedKnowledgeChunk(
            chunk_id=uuid4(),
            chunk_hash="b" * 64,
            document_id=uuid4(),
            source_key="docs.sql",
            title="Databricks SQL",
            canonical_url="https://docs.databricks.com/aws/en/sql/",
            chunk_index=0,
            heading_path=("Databricks SQL",),
            content="Databricks SQL supports SQL workloads.",
            token_count=8,
            source_ref="https://docs.databricks.com/aws/en/sql/",
            vector_similarity=0.9,
            lexical_score=1.0,
            vector_rank=1,
            lexical_rank=1,
            fused_score=0.03,
        )
        self.official = KnowledgeContextBuilder().build("Databricks SQL", (chunk,))

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
            WorkspaceContextBuilder().build_for_prompt(
                query,
                workspace=workspace,
                prompt_name=prompt_spec.name.value,
            )
            if workspace is not None and prompt_spec.use_workspace_context
            else None
        )
        return ChatContextBundle(expert=None, official=self.official, workspace=workspace_context)


async def test_runner_uses_formal_chat_api_and_preserves_database_and_trace(
    tmp_path: Path,
    settings_factory,
    test_database_url: str,
    test_db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
    settings = settings_factory(
        database_url=test_database_url,
        deepseek_api_key="test-deepseek-key",
    )
    gateway = FakeModelGateway()
    context_service = FakeChatContextService()

    def app_factory(settings, trace_sink: ModelTraceSink) -> FastAPI:
        app = create_app(settings=settings, model_trace_sink=trace_sink)
        app.dependency_overrides[get_model_gateway] = lambda: gateway
        app.dependency_overrides[get_chat_context_service] = lambda: context_service
        return app

    runner = EvaluationRunner(
        dataset=dataset,
        settings=settings,
        output_root=tmp_path,
        app_factory=app_factory,
    )

    with caplog.at_level(logging.INFO, logger="databricks_zh_expert.evaluation.runner"):
        result = await runner.run(
            run_id="stage10-integration",
            model=ModelAlias.DEEPSEEK_V4_FLASH,
            case_id="nw_sql_daily_sales",
        )

    assert result.automated_passed is True
    assert result.summary.case_count == 1
    assert result.summary.passed_count == 1
    assert result.summary.prompt_tokens == 120
    assert result.summary.completion_tokens == 60
    case = result.cases[0]
    assert case.session_id is not None
    assert case.model_call_ids
    assert case.citation_urls == ("https://docs.databricks.com/aws/en/sql/",)
    assert case.manual_review.status.value == "pending"

    trace_path = tmp_path / "stage10-integration" / "deepseek-v4-flash" / "trace.jsonl"
    traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(traces) == 1
    assert traces[0]["schema_version"] == "1.7"
    assert traces[0]["trace"]["model_call_id"] == str(case.model_call_ids[0])

    stored_session = await test_db_session.scalar(
        select(ChatSession).where(ChatSession.id == case.session_id)
    )
    stored_call = await test_db_session.scalar(
        select(ModelCall).where(ModelCall.id == case.model_call_ids[0])
    )
    assert stored_session is not None
    assert "stage10-integration" in stored_session.title
    assert stored_call is not None
    assert stored_call.workspace_id == "northwind_psql"
    assert stored_call.workspace_context
    assert stored_call.success is True
    stderr = capsys.readouterr().err
    assert "Case 开始：1/1 nw_sql_daily_sales" in stderr
    assert "Case 完成：1/1 nw_sql_daily_sales" in stderr


async def test_runner_rejects_reusing_a_model_output_directory(
    tmp_path: Path,
    settings_factory,
) -> None:
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
    output = tmp_path / "duplicate" / "deepseek-v4-flash"
    output.mkdir(parents=True)
    (output / "trace.jsonl").write_text("existing\n", encoding="utf-8")
    runner = EvaluationRunner(
        dataset=dataset,
        settings=settings_factory(),
        output_root=tmp_path,
    )

    with pytest.raises(ValueError, match="已存在"):
        await runner.run(
            run_id="duplicate",
            model=ModelAlias.DEEPSEEK_V4_FLASH,
            case_id="nw_sql_daily_sales",
        )
