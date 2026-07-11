import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from databricks_zh_expert.llm.client import JsonObject
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.observability.model_trace import (
    JsonlModelTraceSink,
    ModelCallTrace,
)


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
        request={
            "model": "deepseek/deepseek-v4-flash",
            "messages": [
                {"role": "user", "content": "请分析销售数据。"},
                {"role": "assistant", "content": "请提供字段定义。"},
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
    )


@pytest.mark.asyncio
async def test_jsonl_trace_sink_writes_complete_utf8_input_and_output(tmp_path) -> None:
    trace_path = tmp_path / "logs" / "model-calls.jsonl"
    trace = make_trace()
    sink = JsonlModelTraceSink(trace_path)

    await sink.write(trace)

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": "1.2",
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
        },
        "request": trace.request,
        "response": trace.response,
        "error": None,
    }


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
