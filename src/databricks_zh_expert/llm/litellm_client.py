import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

import litellm

from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import (
    JsonObject,
    JsonValue,
    ModelMessage,
    ModelTransportResult,
)
from databricks_zh_expert.llm.model_registry import (
    ModelDefinition,
    ModelProvider,
)

CompletionFunction = Callable[..., Awaitable[Any]]
SupportedParamsFunction = Callable[..., list[str] | None]
logger = logging.getLogger(__name__)
SENSITIVE_RESPONSE_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "headers",
        "id_token",
        "password",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
)


class LiteLLMTransport:
    def __init__(
        self,
        settings: Settings,
        completion: CompletionFunction | None = None,
        supported_params: SupportedParamsFunction | None = None,
    ) -> None:
        self._settings = settings
        self._completion = completion or litellm.acompletion
        self._supported_params = supported_params or cast(
            SupportedParamsFunction,
            litellm.get_supported_openai_params,
        )

    def build_request(
        self,
        model: ModelDefinition,
        messages: list[ModelMessage],
    ) -> JsonObject:
        supported = (
            self._supported_params(
                model=model.litellm_model,
                custom_llm_provider=model.provider,
                request_type="chat_completion",
            )
            or []
        )
        request: JsonObject = {
            "model": model.litellm_model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }
        if "temperature" in supported:
            request["temperature"] = self._settings.default_temperature
        return request

    async def complete(
        self,
        model: ModelDefinition,
        request: JsonObject,
    ) -> ModelTransportResult:
        api_key = self._get_api_key(model)
        kwargs: dict[str, Any] = dict(request)
        kwargs.update(
            timeout=self._settings.model_request_timeout_seconds,
            api_key=api_key,
            num_retries=0,
        )
        response = await self._completion(**kwargs)

        content = self._read_content(response)
        usage = getattr(response, "usage", None)
        prompt_tokens = self._read_usage(usage, "prompt_tokens")
        completion_tokens = self._read_usage(usage, "completion_tokens")
        return ModelTransportResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            api_response=self._read_api_response(
                response,
                api_key=api_key,
                model=model.litellm_model,
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    def _get_api_key(self, model: ModelDefinition) -> str:
        provider_keys = {
            ModelProvider.DEEPSEEK: self._settings.deepseek_api_key,
            ModelProvider.OPENAI: self._settings.openai_api_key,
        }
        if model.provider not in provider_keys:
            raise AppError(
                code="model_not_supported",
                message="当前模型供应商不受支持。",
                status_code=400,
                details={"provider": model.provider, "model": model.alias},
            )

        secret = provider_keys[model.provider]
        api_key = secret.get_secret_value() if secret is not None else ""
        if not api_key:
            raise AppError(
                code="model_not_configured",
                message="当前模型尚未配置 API 密钥。",
                status_code=503,
                details={"provider": model.provider, "model": model.alias},
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

    @classmethod
    def _read_api_response(
        cls,
        response: Any,
        *,
        api_key: str,
        model: str,
        content: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> JsonObject:
        try:
            payload = cls._response_payload(response)
            sanitized = cls._sanitize_json_value(payload, api_key)
            if isinstance(sanitized, dict):
                choices = sanitized.get("choices")
                if isinstance(choices, list) and choices:
                    return sanitized
        except Exception:
            pass

        logger.warning("模型响应 Trace 归一化失败，已使用安全回退结构。")
        return cls._fallback_api_response(
            model=model,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    @staticmethod
    def _fallback_api_response(
        *,
        model: str,
        content: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> JsonObject:
        total_tokens = (
            prompt_tokens + completion_tokens
            if prompt_tokens is not None and completion_tokens is not None
            else None
        )
        return {
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "trace_metadata": {"response_normalization": "fallback"},
        }

    @staticmethod
    def _response_payload(response: Any) -> Any:
        if isinstance(response, Mapping):
            return response

        model_dump = getattr(response, "model_dump", None)
        if callable(model_dump):
            return model_dump()

        attributes = getattr(response, "__dict__", None)
        return attributes if isinstance(attributes, dict) else {}

    @classmethod
    def _sanitize_json_value(cls, value: Any, api_key: str) -> JsonValue:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return value.replace(api_key, "[REDACTED]") if api_key else value
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Enum):
            return cls._sanitize_json_value(value.value, api_key)
        if isinstance(value, Mapping):
            sanitized: JsonObject = {}
            for raw_key, raw_value in value.items():
                key = str(raw_key)
                if cls._is_sensitive_field(key):
                    continue
                sanitized[key] = cls._sanitize_json_value(raw_value, api_key)
            return sanitized
        if isinstance(value, list | tuple):
            return [cls._sanitize_json_value(item, api_key) for item in value]

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return cls._sanitize_json_value(model_dump(), api_key)

        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, dict):
            return cls._sanitize_json_value(attributes, api_key)
        return None

    @staticmethod
    def _is_sensitive_field(field: str) -> bool:
        normalized = field.casefold().replace("-", "_")
        return (
            normalized.startswith("_")
            or normalized in SENSITIVE_RESPONSE_FIELDS
            or normalized.endswith("_headers")
            or normalized.endswith(("_authorization", "_password", "_secret", "_token"))
            or "api_key" in normalized
        )
