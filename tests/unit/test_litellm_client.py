import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import ModelMessage
from databricks_zh_expert.llm.litellm_client import LiteLLMModelClient, LiteLLMTransport
from databricks_zh_expert.llm.model_registry import (
    ModelAlias,
    ModelDefinition,
    ModelProvider,
)


def make_deepseek_model(*, configured: bool = True) -> ModelDefinition:
    return ModelDefinition(
        alias=ModelAlias.DEEPSEEK_V4_FLASH,
        display_name="DeepSeek V4 Flash",
        provider=ModelProvider.DEEPSEEK,
        litellm_model="deepseek/deepseek-v4-flash",
        configured=configured,
    )


def make_openai_model(*, configured: bool = True) -> ModelDefinition:
    return ModelDefinition(
        alias=ModelAlias.GPT_54_MINI,
        display_name="GPT-5.4 mini",
        provider=ModelProvider.OPENAI,
        litellm_model="openai/gpt-5.4-mini",
        configured=configured,
    )


def test_build_request_adds_temperature_only_when_supported(settings_factory) -> None:
    captured: dict[str, Any] = {}

    def supported_params(**kwargs: Any) -> list[str]:
        captured.update(kwargs)
        return ["temperature"]

    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="key"),
        supported_params=supported_params,
    )

    request = transport.build_request(
        make_deepseek_model(),
        [ModelMessage(role="user", content="你好")],
    )

    assert captured == {
        "model": "deepseek/deepseek-v4-flash",
        "custom_llm_provider": ModelProvider.DEEPSEEK,
        "request_type": "chat_completion",
    }
    assert request == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0.2,
    }


def test_build_request_omits_unsupported_temperature(settings_factory) -> None:
    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="key"),
        supported_params=lambda **_: [],
    )

    request = transport.build_request(make_deepseek_model(), [])

    assert request == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "settings_override"),
    [
        (make_deepseek_model(configured=False), {"deepseek_api_key": None}),
        (
            make_openai_model(configured=False),
            {"default_model": "gpt5.4mini", "openai_api_key": None},
        ),
    ],
)
async def test_model_requires_its_provider_api_key(
    settings_factory,
    model: ModelDefinition,
    settings_override: dict[str, Any],
) -> None:
    transport = LiteLLMTransport(settings_factory(**settings_override))

    with pytest.raises(AppError) as error:
        await transport.complete(model, transport.build_request(model, []))

    assert error.value.code == "model_not_configured"
    assert error.value.status_code == 503
    assert error.value.details == {
        "provider": model.provider,
        "model": model.alias,
    }


@pytest.mark.asyncio
async def test_completion_maps_one_request_and_sanitizes_response(
    settings_factory,
) -> None:
    captured_calls: list[dict[str, Any]] = []
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
        captured_calls.append(kwargs)
        return FakeResponse(
            choices=[SimpleNamespace(message=SimpleNamespace(content="## 回答\n\n测试完成。"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
        )

    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key=api_key),
        completion=fake_completion,
        supported_params=lambda **_: ["temperature"],
    )
    model = make_deepseek_model()
    request = transport.build_request(
        model,
        [ModelMessage(role="user", content="生成 Markdown")],
    )

    result = await transport.complete(model, request)

    assert request == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "生成 Markdown"}],
        "temperature": 0.2,
    }
    assert captured_calls == [
        {
            "model": "deepseek/deepseek-v4-flash",
            "messages": [{"role": "user", "content": "生成 Markdown"}],
            "temperature": 0.2,
            "timeout": 60,
            "api_key": "local-test-key",
            "num_retries": 0,
        }
    ]
    assert result.content == "## 回答\n\n测试完成。"
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
    rendered_response = json.dumps(result.api_response, ensure_ascii=False)
    assert api_key not in rendered_response
    assert "provider-client-secret" not in rendered_response
    assert "provider-proxy-authorization" not in rendered_response
    assert "provider-session-token" not in rendered_response


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

    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
        supported_params=lambda **_: [],
    )
    model = make_deepseek_model()

    with caplog.at_level(logging.WARNING):
        result = await transport.complete(model, transport.build_request(model, []))

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

    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
        supported_params=lambda **_: [],
    )
    model = make_deepseek_model()

    result = await transport.complete(model, transport.build_request(model, []))

    assert result.prompt_tokens is None
    assert result.completion_tokens is None


@pytest.mark.asyncio
async def test_completion_rejects_empty_content(settings_factory) -> None:
    async def fake_completion(**kwargs: Any) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))])

    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
        supported_params=lambda **_: [],
    )
    model = make_deepseek_model()

    with pytest.raises(AppError) as error:
        await transport.complete(model, transport.build_request(model, []))

    assert error.value.code == "model_empty_response"


@pytest.mark.asyncio
async def test_legacy_model_client_preserves_existing_result_contract(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[dict[str, Any]] = []

    async def fake_completion(**kwargs: Any) -> SimpleNamespace:
        captured_calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="兼容回答"))],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
        )

    monkeypatch.setattr(
        "databricks_zh_expert.llm.litellm_client.litellm.get_supported_openai_params",
        lambda **_: [],
    )
    client = LiteLLMModelClient(
        settings=settings_factory(deepseek_api_key="local-test-key"),
        completion=fake_completion,
    )

    result = await client.complete([ModelMessage(role="user", content="兼容测试")])

    assert client.provider == "deepseek"
    assert client.model == "deepseek/deepseek-v4-flash"
    assert captured_calls == [
        {
            "model": "deepseek/deepseek-v4-flash",
            "messages": [{"role": "user", "content": "兼容测试"}],
            "timeout": 60,
            "api_key": "local-test-key",
            "num_retries": 0,
        }
    ]
    assert result.content == "兼容回答"
    assert result.provider == "deepseek"
    assert result.model == "deepseek/deepseek-v4-flash"
    assert result.prompt_tokens == 4
    assert result.completion_tokens == 2
