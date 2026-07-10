import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.litellm_client import LiteLLMModelClient


@pytest.mark.asyncio
async def test_deepseek_model_requires_an_api_key(settings_factory) -> None:
    settings = settings_factory(deepseek_api_key=None)
    client = LiteLLMModelClient(settings=settings)

    with pytest.raises(AppError) as error:
        await client.complete([ModelMessage(role="user", content="你好")])

    assert error.value.code == "model_not_configured"
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_openai_model_requires_an_api_key(settings_factory) -> None:
    settings = settings_factory(
        default_model="openai/gpt-5.4-mini",
        openai_api_key=None,
    )
    client = LiteLLMModelClient(settings=settings)

    with pytest.raises(AppError) as error:
        await client.complete([ModelMessage(role="user", content="你好")])

    assert error.value.code == "model_not_configured"
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_completion_maps_request_and_response_without_network_access(
    settings_factory,
) -> None:
    captured: dict[str, Any] = {}
    api_key = "local-test-key"

    class FakeResponse(SimpleNamespace):
        def model_dump(self) -> dict[str, Any]:
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1767225600,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "## 回答\n\n测试完成。",
                            "reasoning_content": "先检查需求。",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 6,
                    "total_tokens": 16,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
                "provider_extension": {
                    "trace_id": "safe-provider-trace",
                    "access_token": api_key,
                    "client_secret": "provider-client-secret",
                    "proxy_authorization": "provider-proxy-authorization",
                    "session_token": "provider-session-token",
                },
                "response_headers": {"authorization": f"Bearer {api_key}"},
                "_hidden_params": {"api_key": api_key},
            }

    async def fake_completion(**kwargs: Any) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse(
            choices=[SimpleNamespace(message=SimpleNamespace(content="## 回答\n\n测试完成。"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
        )

    settings = settings_factory(deepseek_api_key=api_key)
    client = LiteLLMModelClient(settings=settings, completion=fake_completion)

    result = await client.complete([ModelMessage(role="user", content="生成 Markdown")])

    assert captured == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "生成 Markdown"}],
        "timeout": 60,
        "api_key": "local-test-key",
    }
    assert result.content == "## 回答\n\n测试完成。"
    assert result.provider == "deepseek"
    assert result.model == "deepseek/deepseek-v4-flash"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 6
    assert result.api_response == {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1767225600,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "## 回答\n\n测试完成。",
                    "reasoning_content": "先检查需求。",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 6,
            "total_tokens": 16,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
        "provider_extension": {"trace_id": "safe-provider-trace"},
    }
    assert api_key not in json.dumps(result.api_response, ensure_ascii=False)
    assert "provider-client-secret" not in json.dumps(result.api_response)
    assert "provider-proxy-authorization" not in json.dumps(result.api_response)
    assert "provider-session-token" not in json.dumps(result.api_response)


@pytest.mark.asyncio
async def test_completion_uses_safe_fallback_when_response_normalization_fails(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenDumpResponse(SimpleNamespace):
        def model_dump(self) -> dict[str, Any]:
            raise RuntimeError("归一化异常中包含 local-test-key")

    async def fake_completion(**kwargs: Any) -> BrokenDumpResponse:
        del kwargs
        return BrokenDumpResponse(
            choices=[SimpleNamespace(message=SimpleNamespace(content="模型回答仍然有效。"))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
        )

    client = LiteLLMModelClient(
        settings=settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
    )

    with caplog.at_level(logging.WARNING):
        result = await client.complete([ModelMessage(role="user", content="测试回退")])

    assert result.content == "模型回答仍然有效。"
    assert result.api_response == {
        "object": "chat.completion",
        "model": "deepseek/deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "模型回答仍然有效。",
                },
                "finish_reason": None,
            }
        ],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": 5,
        },
        "trace_metadata": {"response_normalization": "fallback"},
    }
    assert "模型响应 Trace 归一化失败" in caplog.text
    assert "local-test-key" not in caplog.text


@pytest.mark.asyncio
async def test_completion_returns_none_tokens_when_usage_is_missing(
    settings_factory,
) -> None:
    async def fake_completion(**kwargs: Any) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="回答"))])

    client = LiteLLMModelClient(
        settings=settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
    )

    result = await client.complete([ModelMessage(role="user", content="测试")])

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


@pytest.mark.asyncio
async def test_completion_rejects_empty_content(settings_factory) -> None:
    async def fake_completion(**kwargs: Any) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))])

    client = LiteLLMModelClient(
        settings=settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
    )

    with pytest.raises(AppError) as error:
        await client.complete([ModelMessage(role="user", content="测试")])

    assert error.value.code == "model_empty_response"
