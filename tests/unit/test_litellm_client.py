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
async def test_completion_maps_request_and_response_without_network_access(
    settings_factory,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="## 回答\n\n测试完成。"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
        )

    settings = settings_factory(deepseek_api_key="local-test-key")
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
