import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import (
    JsonObject,
    ModelMessage,
    ModelTransport,
    ModelTransportResult,
)
from databricks_zh_expert.llm.model_registry import (
    ModelAlias,
    ModelDefinition,
    ModelProvider,
    ModelRegistry,
)

RETRYABLE_EXCEPTION_TYPES = (
    Timeout,
    RateLimitError,
    APIConnectionError,
    InternalServerError,
    ServiceUnavailableError,
)
API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
BEARER_PATTERN = re.compile(r"(?i)(\bBearer\s+)[^\s,;\"']+")
NAMED_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|"
    r"client[_-]?secret)\b[\"']?\s*[:=]\s*[\"']?)([^\"',;\s\[\]{}]+)"
)


@dataclass(frozen=True, slots=True)
class ModelAttempt:
    invocation_id: UUID
    requested_model: ModelAlias
    model_alias: ModelAlias
    provider: ModelProvider
    litellm_model: str
    attempt_number: int
    request: JsonObject
    response: JsonObject | None
    content: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    success: bool
    retryable: bool
    error: JsonObject | None


@dataclass(frozen=True, slots=True)
class ErrorClassification:
    attempt_code: str
    terminal_code: str
    message: str
    status_code: int
    retryable: bool


class ModelGatewayFailure(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ModelGateway(Protocol):
    def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]: ...


def elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def classify_model_error(error: Exception) -> ErrorClassification:
    if isinstance(error, AppError):
        if error.code == "model_not_configured":
            return ErrorClassification(
                attempt_code="model_not_configured",
                terminal_code="model_not_configured",
                message="当前模型尚未配置 API 密钥。",
                status_code=503,
                retryable=False,
            )
        return ErrorClassification(
            attempt_code="model_request_failed",
            terminal_code="model_request_failed",
            message="模型调用失败，请检查请求和模型配置。",
            status_code=502,
            retryable=False,
        )

    status_code = getattr(error, "status_code", None)
    if isinstance(error, Timeout):
        attempt_code = "model_timeout"
    elif isinstance(error, RateLimitError) or status_code == 429:
        attempt_code = "model_rate_limited"
    elif isinstance(error, APIConnectionError):
        attempt_code = "model_connection_failed"
    elif isinstance(
        error,
        (InternalServerError, ServiceUnavailableError),
    ) or (isinstance(status_code, int) and 500 <= status_code <= 599):
        attempt_code = "model_provider_unavailable"
    else:
        attempt_code = ""

    if attempt_code:
        return ErrorClassification(
            attempt_code=attempt_code,
            terminal_code="model_fallback_exhausted",
            message="模型服务暂时不可用。",
            status_code=502,
            retryable=True,
        )

    if isinstance(error, AuthenticationError) or status_code in (401, 403):
        return ErrorClassification(
            attempt_code="model_authentication_failed",
            terminal_code="model_authentication_failed",
            message="模型认证或权限校验失败。",
            status_code=503,
            retryable=False,
        )

    return ErrorClassification(
        attempt_code="model_request_failed",
        terminal_code="model_request_failed",
        message="模型调用失败，请检查请求和模型配置。",
        status_code=502,
        retryable=False,
    )


def redact_sensitive_text(value: str, sensitive_values: tuple[str, ...]) -> str:
    redacted = value
    for sensitive_value in sorted(set(sensitive_values), key=len, reverse=True):
        if sensitive_value:
            redacted = redacted.replace(sensitive_value, "[REDACTED]")
    redacted = API_KEY_PATTERN.sub("[REDACTED]", redacted)
    redacted = BEARER_PATTERN.sub(r"\1[REDACTED]", redacted)
    return NAMED_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]", redacted)


def build_provider_error(
    error: Exception,
    sensitive_values: tuple[str, ...],
) -> JsonObject:
    status_code = getattr(error, "status_code", None)
    provider_code = getattr(error, "code", None)
    request_id = getattr(error, "request_id", None)
    return {
        "message": redact_sensitive_text(str(error), sensitive_values),
        "status_code": status_code if isinstance(status_code, int) else None,
        "code": (
            redact_sensitive_text(str(provider_code), sensitive_values)
            if provider_code is not None
            else None
        ),
        "request_id": (
            redact_sensitive_text(str(request_id), sensitive_values)
            if request_id is not None
            else None
        ),
    }


def build_failed_attempt(
    *,
    invocation_id: UUID,
    requested_model: ModelAlias,
    definition: ModelDefinition,
    attempt_number: int,
    request: JsonObject,
    latency_ms: int,
    error: Exception,
    classification: ErrorClassification,
    sensitive_values: tuple[str, ...],
) -> ModelAttempt:
    return ModelAttempt(
        invocation_id=invocation_id,
        requested_model=requested_model,
        model_alias=definition.alias,
        provider=definition.provider,
        litellm_model=definition.litellm_model,
        attempt_number=attempt_number,
        request=request,
        response=None,
        content=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=latency_ms,
        success=False,
        retryable=classification.retryable,
        error={
            "message": classification.message,
            "type": type(error).__name__,
            "param": None,
            "code": classification.attempt_code,
            "provider_error": build_provider_error(error, sensitive_values),
        },
    )


def build_successful_attempt(
    *,
    invocation_id: UUID,
    requested_model: ModelAlias,
    definition: ModelDefinition,
    attempt_number: int,
    request: JsonObject,
    latency_ms: int,
    result: ModelTransportResult,
) -> ModelAttempt:
    return ModelAttempt(
        invocation_id=invocation_id,
        requested_model=requested_model,
        model_alias=definition.alias,
        provider=definition.provider,
        litellm_model=definition.litellm_model,
        attempt_number=attempt_number,
        request=request,
        response=result.api_response,
        content=result.content,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=latency_ms,
        success=True,
        retryable=False,
        error=None,
    )


class FallbackModelGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        transport: ModelTransport,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._sensitive_values = sensitive_values

    async def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]:
        resolved_model = requested_model or self._registry.default_model
        candidates = tuple(dict.fromkeys((resolved_model, *self._registry.fallback_models)))
        invocation_id = uuid4()

        for attempt_number, alias in enumerate(candidates, start=1):
            definition = self._registry.get(alias)
            request: JsonObject = {
                "model": definition.litellm_model,
                "messages": [
                    {"role": message.role, "content": message.content} for message in messages
                ],
            }
            started_at = time.perf_counter()
            try:
                request = self._transport.build_request(definition, messages)
                result = await self._transport.complete(definition, request)
            except Exception as error:
                classification = classify_model_error(error)
                yield build_failed_attempt(
                    invocation_id=invocation_id,
                    requested_model=resolved_model,
                    definition=definition,
                    attempt_number=attempt_number,
                    request=request,
                    latency_ms=elapsed_ms(started_at),
                    error=error,
                    classification=classification,
                    sensitive_values=self._sensitive_values,
                )
                if not classification.retryable:
                    raise ModelGatewayFailure(
                        classification.terminal_code,
                        classification.message,
                        classification.status_code,
                    ) from None
                continue

            yield build_successful_attempt(
                invocation_id=invocation_id,
                requested_model=resolved_model,
                definition=definition,
                attempt_number=attempt_number,
                request=request,
                latency_ms=elapsed_ms(started_at),
                result=result,
            )
            return

        raise ModelGatewayFailure(
            code="model_fallback_exhausted",
            message="模型调用失败，请稍后重试。",
            status_code=502,
        )
