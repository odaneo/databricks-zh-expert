import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.llm.client import JsonObject
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.observability.model_trace import (
    ArtifactValidationTrace,
    ExpertTemplateCandidateTrace,
    ExpertTemplateSelectionTrace,
    ExpertTemplateTrace,
    JsonlModelTraceSink,
    ModelCallTrace,
    RetrievalCandidateTrace,
    RetrievalTrace,
    WorkspaceCandidateTrace,
    WorkspaceSelectionTrace,
    WorkspaceTrace,
)
from databricks_zh_expert.prompts.registry import PromptName


def make_trace() -> ModelCallTrace:
    return ModelCallTrace(
        model_call_id=uuid4(),
        invocation_id=uuid4(),
        session_id=uuid4(),
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        requested_model=ModelAlias.GPT_55,
        model_alias=ModelAlias.GPT_54_MINI,
        provider="openai",
        attempt_number=2,
        latency_ms=1250,
        success=True,
        retryable=False,
        prompt_name=PromptName.SQL_GENERATION,
        prompt_version="1.0.1",
        artifact_type=ArtifactType.SQL,
        artifact_validation=ArtifactValidationTrace(valid=True, violations=()),
        request={
            "model": "deepseek/deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "始终使用中文并直接输出 SQL。"},
                {"role": "user", "content": "请分析销售数据。"},
            ],
        },
        response={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1767225600,
            "model": "deepseek-chat",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "## 分析结果\n\n这是完整输出。",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        },
        error=None,
        expert_profile="generic",
    )


@pytest.mark.asyncio
async def test_jsonl_trace_sink_writes_complete_utf8_input_and_output(tmp_path) -> None:
    trace_path = tmp_path / "logs" / "model-calls.jsonl"
    trace = make_trace()
    sink = JsonlModelTraceSink(trace_path)

    await sink.write(trace)

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": "1.7",
        "protocol": "openai.chat.completions",
        "trace": {
            "model_call_id": str(trace.model_call_id),
            "invocation_id": str(trace.invocation_id),
            "session_id": str(trace.session_id),
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "requested_model": "gpt5.5",
            "model_alias": "gpt5.4mini",
            "provider": "openai",
            "attempt_number": 2,
            "latency_ms": 1250,
            "success": True,
            "retryable": False,
            "prompt_name": "sql_generation",
            "prompt_version": "1.0.1",
            "artifact_type": "sql",
            "artifact_validation": {
                "valid": True,
                "violations": [],
            },
            "expert_profile": "generic",
            "workspace_id": None,
            "workspace_version": None,
            "workspace_source_hash": None,
            "project_fact_status": None,
        },
        "retrieval": None,
        "expert_templates": None,
        "context": {"workspace": None},
        "request": trace.request,
        "response": trace.response,
        "error": None,
    }


def test_trace_serializes_missing_artifact_validation_for_provider_failure() -> None:
    trace = replace(
        make_trace(),
        success=False,
        artifact_validation=None,
    )

    payload = json.loads(JsonlModelTraceSink._serialize(trace))

    assert payload["trace"]["artifact_validation"] is None
    assert payload["retrieval"] is None


def test_trace_15_serializes_rag_scores_sources_and_actual_context() -> None:
    context = "【不可信资料开始】\n[S1] Retry guidance.\n【不可信资料结束】"
    retrieval = RetrievalTrace(
        embedding_model="text-embedding-3-small",
        latency_ms=37,
        candidates=(
            RetrievalCandidateTrace(
                chunk_id=uuid4(),
                rank=1,
                vector_rank=1,
                vector_score=0.92,
                lexical_rank=2,
                lexical_score=0.7,
                fused_score=0.0325,
                url="https://docs.databricks.com/aws/en/jobs/#retries",
                selected=True,
            ),
        ),
        selected_urls=("https://docs.databricks.com/aws/en/jobs/#retries",),
    )
    trace = replace(
        make_trace(),
        prompt_name=PromptName.KNOWLEDGE_QA,
        prompt_version="1.1.0",
        retrieval=retrieval,
        request={
            "model": "deepseek/deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "固定知识库系统 Prompt"},
                {"role": "user", "content": context},
                {"role": "user", "content": "如何配置失败重试？"},
            ],
        },
    )

    payload = json.loads(JsonlModelTraceSink._serialize(trace))

    assert payload["schema_version"] == "1.7"
    assert payload["retrieval"] == {
        "embedding_model": "text-embedding-3-small",
        "latency_ms": 37,
        "candidates": [
            {
                "chunk_id": str(retrieval.candidates[0].chunk_id),
                "rank": 1,
                "vector_rank": 1,
                "vector_score": 0.92,
                "lexical_rank": 2,
                "lexical_score": 0.7,
                "fused_score": 0.0325,
                "url": "https://docs.databricks.com/aws/en/jobs/#retries",
                "selected": True,
            }
        ],
        "selected_urls": ["https://docs.databricks.com/aws/en/jobs/#retries"],
    }
    assert payload["request"]["messages"][1]["content"] == context


def test_trace_15_serializes_expert_candidates_selections_and_actual_context() -> None:
    expert_context = "以下内容是内部专家模板。\n【内部专家模板开始】"
    expert_templates = ExpertTemplateTrace(
        status="selected",
        embedding_model="text-embedding-3-small",
        latency_ms=31,
        context_token_count=2140,
        candidates=(
            ExpertTemplateCandidateTrace(
                template_id="retail.workflow_dag",
                version="1.0.0",
                rank=1,
                vector_rank=1,
                vector_score=0.82,
                lexical_rank=2,
                lexical_score=0.17,
                fused_score=0.0325,
                selected=True,
            ),
        ),
        selected=(
            ExpertTemplateSelectionTrace(
                template_id="retail.workflow_dag",
                version="1.0.0",
                content_hash="a" * 64,
                layer="retail_sales_demo",
                profile="retail_sales_demo",
                rank=1,
                reason="semantic",
                extends="workflow.lakeflow_jobs@1.0.0",
            ),
        ),
    )
    trace = replace(
        make_trace(),
        prompt_name=PromptName.WORKFLOW_DESIGN,
        expert_profile="retail_sales_demo",
        expert_templates=expert_templates,
        request={
            "model": "deepseek/deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "工作流系统 Prompt"},
                {"role": "user", "content": expert_context},
                {"role": "user", "content": "官方知识上下文"},
                {"role": "user", "content": "设计零售工作流"},
            ],
        },
    )

    payload = json.loads(JsonlModelTraceSink._serialize(trace))

    assert payload["schema_version"] == "1.7"
    assert payload["trace"]["expert_profile"] == "retail_sales_demo"
    assert payload["expert_templates"] == {
        "status": "selected",
        "embedding_model": "text-embedding-3-small",
        "latency_ms": 31,
        "context_token_count": 2140,
        "candidates": [
            {
                "template_id": "retail.workflow_dag",
                "version": "1.0.0",
                "rank": 1,
                "vector_rank": 1,
                "vector_score": 0.82,
                "lexical_rank": 2,
                "lexical_score": 0.17,
                "fused_score": 0.0325,
                "selected": True,
            }
        ],
        "selected": [
            {
                "template_id": "retail.workflow_dag",
                "version": "1.0.0",
                "content_hash": "a" * 64,
                "layer": "retail_sales_demo",
                "profile": "retail_sales_demo",
                "rank": 1,
                "reason": "semantic",
                "extends": "workflow.lakeflow_jobs@1.0.0",
            }
        ],
    }
    assert payload["request"]["messages"][-3]["content"] == expert_context
    assert "source_path" not in json.dumps(payload["expert_templates"])
    assert "C:\\" not in json.dumps(payload["expert_templates"])


def test_trace_17_serializes_workspace_candidates_selections_and_proposal_status() -> None:
    workspace = WorkspaceTrace(
        context_token_count=640,
        candidates=(
            WorkspaceCandidateTrace(
                unit_id="source-rds-customer:1",
                source_id="source-rds-customer",
                kind="source_ddl",
                source_path="source-schema/rds-customer.sql",
                content_hash="b" * 64,
                rank=1,
                score=212.0,
                selected=True,
            ),
        ),
        selected=(
            WorkspaceSelectionTrace(
                unit_id="source-rds-customer:1",
                source_id="source-rds-customer",
                kind="source_ddl",
                source_path="source-schema/rds-customer.sql",
                content_hash="b" * 64,
                rank=1,
                reason="lexical",
            ),
        ),
    )
    trace = replace(
        make_trace(),
        workspace_id="retail_sales_demo",
        workspace_version="1.0.0",
        workspace_source_hash="c" * 64,
        project_fact_status="proposal",
        workspace=workspace,
    )

    payload = json.loads(JsonlModelTraceSink._serialize(trace))

    assert payload["schema_version"] == "1.7"
    assert "workspace_mode" not in payload["trace"]
    assert payload["trace"]["project_fact_status"] == "proposal"
    assert payload["context"]["workspace"]["selected"][0]["source_path"] == (
        "source-schema/rds-customer.sql"
    )
    assert "C:\\" not in json.dumps(payload["context"]["workspace"])


def test_rag_trace_does_not_contain_credentials_raw_html_or_embedding_arrays() -> None:
    retrieval = RetrievalTrace(
        embedding_model="text-embedding-3-small",
        latency_ms=10,
        candidates=(
            RetrievalCandidateTrace(
                chunk_id=uuid4(),
                rank=1,
                vector_rank=1,
                vector_score=0.9,
                lexical_rank=None,
                lexical_score=None,
                fused_score=1 / 61,
                url="https://docs.databricks.com/aws/en/jobs/",
                selected=True,
            ),
        ),
        selected_urls=("https://docs.databricks.com/aws/en/jobs/",),
    )
    trace = replace(make_trace(), retrieval=retrieval)

    serialized = JsonlModelTraceSink._serialize(trace)
    payload = json.loads(serialized)

    assert "sk-test-secret" not in serialized
    assert "Authorization" not in serialized
    assert "<html" not in serialized
    assert "embedding" not in payload["retrieval"]["candidates"][0]


@pytest.mark.asyncio
async def test_jsonl_trace_sink_serializes_concurrent_writes(tmp_path) -> None:
    trace_path = tmp_path / "model-calls.jsonl"
    sink = JsonlModelTraceSink(trace_path)
    traces = [replace(make_trace(), model_call_id=uuid4()) for _ in range(10)]

    await asyncio.gather(*(sink.write(trace) for trace in traces))

    payloads = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(payloads) == 10
    assert {payload["trace"]["model_call_id"] for payload in payloads} == {
        str(trace.model_call_id) for trace in traces
    }


@pytest.mark.asyncio
async def test_jsonl_trace_sink_does_not_break_chat_when_file_write_fails(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("占用路径", encoding="utf-8")
    sink = JsonlModelTraceSink(blocked_parent / "model-calls.jsonl")

    with caplog.at_level(logging.WARNING):
        await sink.write(make_trace())

    assert "模型调用 Trace 写入失败" in caplog.text


@pytest.mark.asyncio
async def test_jsonl_trace_sink_does_not_break_chat_when_serialization_fails(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    circular_response: dict[str, Any] = {}
    circular_response["self"] = circular_response
    trace = replace(
        make_trace(),
        response=cast(JsonObject, circular_response),
    )
    trace_path = tmp_path / "model-calls.jsonl"
    sink = JsonlModelTraceSink(trace_path)

    with caplog.at_level(logging.WARNING):
        await sink.write(trace)

    assert not trace_path.exists()
    assert "模型调用 Trace 写入失败" in caplog.text
