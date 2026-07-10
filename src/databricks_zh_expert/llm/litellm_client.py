from collections.abc import Awaitable, Callable
from typing import Any

import litellm

from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import ModelMessage, ModelResult

CompletionFunction = Callable[..., Awaitable[Any]]


class LiteLLMModelClient:
    def __init__(
        self,
        settings: Settings,
        completion: CompletionFunction | None = None,
    ) -> None:
        self._settings = settings
        self._completion = completion or litellm.acompletion

    @property
    def provider(self) -> str:
        if "/" not in self.model:
            return "unknown"
        return self.model.split("/", maxsplit=1)[0]

    @property
    def model(self) -> str:
        return self._settings.default_model

    async def complete(self, messages: list[ModelMessage]) -> ModelResult:
        api_key = self._get_api_key()
        response = await self._completion(
            model=self.model,
            messages=[{"role": item.role, "content": item.content} for item in messages],
            timeout=self._settings.model_request_timeout_seconds,
            api_key=api_key,
        )

        content = self._read_content(response)
        usage = getattr(response, "usage", None)
        return ModelResult(
            content=content,
            provider=self.provider,
            model=self.model,
            prompt_tokens=self._read_usage(usage, "prompt_tokens"),
            completion_tokens=self._read_usage(usage, "completion_tokens"),
        )

    def _get_api_key(self) -> str:
        provider_keys = {
            "deepseek": self._settings.deepseek_api_key,
            "openai": self._settings.openai_api_key,
        }
        if self.provider not in provider_keys:
            raise AppError(
                code="model_not_supported",
                message="当前模型供应商不受支持。",
                status_code=400,
                details={"model": self.model},
            )

        secret = provider_keys[self.provider]
        api_key = secret.get_secret_value() if secret is not None else ""
        if not api_key:
            raise AppError(
                code="model_not_configured",
                message="当前模型尚未配置 API 密钥。",
                status_code=503,
                details={"provider": self.provider, "model": self.model},
            )
        return api_key

    @staticmethod
    def _read_content(response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as error:
            raise AppError(
                code="model_invalid_response",
                message="模型返回了无法解析的响应。",
                status_code=502,
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise AppError(
                code="model_empty_response",
                message="模型返回了空内容。",
                status_code=502,
            )
        return content

    @staticmethod
    def _read_usage(usage: Any, field: str) -> int | None:
        if usage is None:
            return None
        value = getattr(usage, field, None)
        return value if isinstance(value, int) else None
