from collections.abc import Callable, Mapping

import pytest
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from databricks_zh_expert.api.dependencies import get_model_gateway
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.llm.client import (
    JsonObject,
    ModelMessage,
    ModelTransportResult,
)
from databricks_zh_expert.llm.gateway import (
    FallbackModelGateway,
    ModelAttempt,
    ModelGatewayFailure,
    classify_model_error,
)
from databricks_zh_expert.llm.model_registry import (
    ModelAlias,
    ModelDefinition,
    ModelRegistry,
)

type SettingsFactory = Callable[..., Settings]
type TransportOutcome = ModelTransportResult | Exception


class FakeProviderError(Exception):
    def __init__(
        self,
        status_code: int | None,
        message: str = "供应商原始错误详情",
        *,
        code: str | None = "provider_error_code",
        request_id: str | None = "req-test-123",
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        super().__init__(message)


class FakeModelTransport:
    def __init__(self, outcomes: Mapping[ModelAlias, TransportOutcome]) -> None:
        self._outcomes = dict(outcomes)
        self.built_aliases: list[ModelAlias] = []
        self.called_aliases: list[ModelAlias] = []

    def build_request(
        self,
        model: ModelDefinition,
        messages: list[ModelMessage],
    ) -> JsonObject:
        self.built_aliases.append(model.alias)
        return {
            "model": model.litellm_model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }

    async def complete(
        self,
        model: ModelDefinition,
        request: JsonObject,
    ) -> ModelTransportResult:
        del request
        self.called_aliases.append(model.alias)
        outcome = self._outcomes[model.alias]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_transport_result(content: str = "成功") -> ModelTransportResult:
    return ModelTransportResult(
        content=content,
        prompt_tokens=5,
        completion_tokens=3,
        api_response={
            "object": "chat.completion",
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def make_gateway(
    settings_factory: SettingsFactory,
    *,
    outcomes: Mapping[ModelAlias, TransportOutcome],
    default_model: ModelAlias = ModelAlias.DEEPSEEK_V4_FLASH,
    fallback_models: tuple[ModelAlias, ...] = (
        ModelAlias.DEEPSEEK_V4_FLASH,
        ModelAlias.GPT_54_MINI,
    ),
) -> tuple[FallbackModelGateway, FakeModelTransport]:
    settings = settings_factory(
        default_model=default_model.value,
        fallback_models=tuple(alias.value for alias in fallback_models),
        openai_api_key="openai-key",
        deepseek_api_key="deepseek-key",
    )
    transport = FakeModelTransport(outcomes)
    gateway = FallbackModelGateway(
        registry=ModelRegistry.from_settings(settings),
        transport=transport,
        sensitive_values=("openai-key", "deepseek-key"),
    )
    return gateway, transport


async def collect(
    gateway: FallbackModelGateway,
    requested_model: ModelAlias | None = None,
) -> list[ModelAttempt]:
    return [
        attempt
        async for attempt in gateway.run(
            [ModelMessage(role="user", content="测试")],
            requested_model,
        )
    ]


@pytest.mark.asyncio
async def test_missing_request_model_uses_default_and_skips_duplicate_fallback(
    settings_factory: SettingsFactory,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={ModelAlias.DEEPSEEK_V4_FLASH: make_transport_result()},
    )

    attempts = await collect(gateway)

    assert [attempt.model_alias for attempt in attempts] == [ModelAlias.DEEPSEEK_V4_FLASH]
    assert transport.built_aliases == [ModelAlias.DEEPSEEK_V4_FLASH]
    assert transport.called_aliases == [ModelAlias.DEEPSEEK_V4_FLASH]
    assert attempts[0].requested_model is ModelAlias.DEEPSEEK_V4_FLASH


@pytest.mark.asyncio
async def test_explicit_request_model_overrides_default(
    settings_factory: SettingsFactory,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={ModelAlias.GPT_55: make_transport_result()},
    )

    attempts = await collect(gateway, ModelAlias.GPT_55)

    assert transport.called_aliases == [ModelAlias.GPT_55]
    assert attempts[0].requested_model is ModelAlias.GPT_55
    assert attempts[0].model_alias is ModelAlias.GPT_55


@pytest.mark.asyncio
async def test_retryable_429_falls_back_and_keeps_one_invocation_id(
    settings_factory: SettingsFactory,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={
            ModelAlias.GPT_55: FakeProviderError(429),
            ModelAlias.DEEPSEEK_V4_FLASH: make_transport_result("fallback 成功"),
        },
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )

    attempts = await collect(gateway, ModelAlias.GPT_55)

    assert transport.called_aliases == [ModelAlias.GPT_55, ModelAlias.DEEPSEEK_V4_FLASH]
    assert [attempt.success for attempt in attempts] == [False, True]
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert len({attempt.invocation_id for attempt in attempts}) == 1
    assert attempts[0].retryable is True
    assert attempts[0].error == {
        "message": "模型服务暂时不可用。",
        "type": "FakeProviderError",
        "param": None,
        "code": "model_rate_limited",
        "provider_error": {
            "message": "供应商原始错误详情",
            "status_code": 429,
            "code": "provider_error_code",
            "request_id": "req-test-123",
        },
    }
    assert attempts[0].response is None
    assert attempts[0].content is None
    assert attempts[0].prompt_tokens is None
    assert attempts[0].completion_tokens is None
    assert attempts[1].retryable is False
    assert attempts[1].error is None
    assert attempts[1].content == "fallback 成功"
    assert attempts[1].prompt_tokens == 5
    assert attempts[1].completion_tokens == 3
    assert attempts[1].response == make_transport_result("fallback 成功").api_response
    assert all(attempt.latency_ms >= 0 for attempt in attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [None, 400, 401, 429, 500])
async def test_every_failed_attempt_includes_original_provider_error(
    settings_factory: SettingsFactory,
    status_code: int | None,
) -> None:
    gateway, _ = make_gateway(
        settings_factory,
        outcomes={ModelAlias.GPT_55: FakeProviderError(status_code)},
        fallback_models=(),
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure):
        await anext(iterator)

    assert failed_attempt.error is not None
    assert failed_attempt.error["provider_error"] == {
        "message": "供应商原始错误详情",
        "status_code": status_code,
        "code": "provider_error_code",
        "request_id": "req-test-123",
    }


@pytest.mark.asyncio
async def test_gateway_dependency_redacts_credentials_from_original_error(
    settings_factory: SettingsFactory,
) -> None:
    settings = settings_factory(
        default_model="gpt5.5",
        fallback_models=(),
        openai_api_key="openai-private-value",
        deepseek_api_key="deepseek-private-value",
    )
    registry = ModelRegistry.from_settings(settings)
    transport = FakeModelTransport(
        {
            ModelAlias.GPT_55: FakeProviderError(
                400,
                message=(
                    "Authorization: Bearer openai-private-value; "
                    "api_key=sk-unconfigured-sensitive-value; "
                    "details=deepseek-private-value; "
                    'payload={"api_key":"unconfigured-json-key",'
                    '"password":"plain-password"}'
                ),
            )
        }
    )
    gateway = get_model_gateway(
        settings=settings,
        registry=registry,
        transport=transport,
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure):
        await anext(iterator)

    assert failed_attempt.error is not None
    assert failed_attempt.error["provider_error"] == {
        "message": (
            "Authorization: Bearer [REDACTED]; api_key=[REDACTED]; "
            'details=[REDACTED]; payload={"api_key":"[REDACTED]",'
            '"password":"[REDACTED]"}'
        ),
        "status_code": 400,
        "code": "provider_error_code",
        "request_id": "req-test-123",
    }


@pytest.mark.asyncio
async def test_authentication_failure_does_not_fallback(
    settings_factory: SettingsFactory,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={ModelAlias.GPT_55: FakeProviderError(401)},
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)

    assert failed_attempt.retryable is False
    assert failed_attempt.error is not None
    assert failed_attempt.error["code"] == "model_authentication_failed"
    assert error.value.code == "model_authentication_failed"
    assert error.value.status_code == 503
    assert transport.called_aliases == [ModelAlias.GPT_55]


@pytest.mark.asyncio
async def test_all_retryable_candidates_raise_fallback_exhausted(
    settings_factory: SettingsFactory,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={
            ModelAlias.GPT_55: FakeProviderError(429),
            ModelAlias.DEEPSEEK_V4_FLASH: FakeProviderError(503),
        },
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    assert (await anext(iterator)).attempt_number == 1
    assert (await anext(iterator)).attempt_number == 2
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)

    assert error.value.code == "model_fallback_exhausted"
    assert error.value.status_code == 502
    assert transport.called_aliases == [ModelAlias.GPT_55, ModelAlias.DEEPSEEK_V4_FLASH]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "attempt_code"),
    [
        (429, "model_rate_limited"),
        (500, "model_provider_unavailable"),
        (502, "model_provider_unavailable"),
        (503, "model_provider_unavailable"),
        (504, "model_provider_unavailable"),
    ],
)
async def test_retryable_provider_status_requests_the_next_candidate(
    settings_factory: SettingsFactory,
    status_code: int,
    attempt_code: str,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={
            ModelAlias.GPT_55: FakeProviderError(status_code),
            ModelAlias.DEEPSEEK_V4_FLASH: make_transport_result(),
        },
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )

    attempts = await collect(gateway, ModelAlias.GPT_55)

    assert transport.called_aliases == [ModelAlias.GPT_55, ModelAlias.DEEPSEEK_V4_FLASH]
    assert attempts[0].error is not None
    assert attempts[0].error["code"] == attempt_code
    assert attempts[0].retryable is True
    assert attempts[1].success is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "terminal_code", "terminal_status"),
    [
        (400, "model_request_failed", 502),
        (401, "model_authentication_failed", 503),
        (403, "model_authentication_failed", 503),
        (404, "model_request_failed", 502),
    ],
)
async def test_non_retryable_provider_status_stops_immediately(
    settings_factory: SettingsFactory,
    status_code: int,
    terminal_code: str,
    terminal_status: int,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={ModelAlias.GPT_55: FakeProviderError(status_code)},
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)

    assert failed_attempt.retryable is False
    assert error.value.code == terminal_code
    assert error.value.status_code == terminal_status
    assert transport.called_aliases == [ModelAlias.GPT_55]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_error", "terminal_code"),
    [
        (
            AppError(
                code="model_not_configured",
                message="原始配置错误 openai-key",
                status_code=503,
            ),
            "model_not_configured",
        ),
        (
            AppError(
                code="model_empty_response",
                message="原始空响应 openai-key",
                status_code=502,
            ),
            "model_request_failed",
        ),
        (
            AppError(
                code="model_invalid_response",
                message="原始无效响应 openai-key",
                status_code=502,
            ),
            "model_request_failed",
        ),
    ],
)
async def test_application_errors_never_fallback_even_with_5xx_status(
    settings_factory: SettingsFactory,
    app_error: AppError,
    terminal_code: str,
) -> None:
    gateway, transport = make_gateway(
        settings_factory,
        outcomes={ModelAlias.GPT_55: app_error},
        fallback_models=(ModelAlias.DEEPSEEK_V4_FLASH,),
    )
    iterator = gateway.run([], ModelAlias.GPT_55)

    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)

    assert failed_attempt.retryable is False
    assert error.value.code == terminal_code
    assert transport.called_aliases == [ModelAlias.GPT_55]
    assert "openai-key" not in str(failed_attempt.error)
    assert "[REDACTED]" in str(failed_attempt.error)
    assert "openai-key" not in error.value.message


@pytest.mark.parametrize(
    ("provider_error", "attempt_code", "terminal_code", "retryable"),
    [
        (
            Timeout(message="raw secret", model="m", llm_provider="p"),
            "model_timeout",
            "model_fallback_exhausted",
            True,
        ),
        (
            RateLimitError(message="raw secret", model="m", llm_provider="p"),
            "model_rate_limited",
            "model_fallback_exhausted",
            True,
        ),
        (
            APIConnectionError(message="raw secret", model="m", llm_provider="p"),
            "model_connection_failed",
            "model_fallback_exhausted",
            True,
        ),
        (
            InternalServerError(message="raw secret", model="m", llm_provider="p"),
            "model_provider_unavailable",
            "model_fallback_exhausted",
            True,
        ),
        (
            ServiceUnavailableError(
                message="raw secret",
                model="m",
                llm_provider="p",
            ),
            "model_provider_unavailable",
            "model_fallback_exhausted",
            True,
        ),
        (
            AuthenticationError(message="raw secret", model="m", llm_provider="p"),
            "model_authentication_failed",
            "model_authentication_failed",
            False,
        ),
        (
            BadRequestError(message="raw secret", model="m", llm_provider="p"),
            "model_request_failed",
            "model_request_failed",
            False,
        ),
        (
            NotFoundError(message="raw secret", model="m", llm_provider="p"),
            "model_request_failed",
            "model_request_failed",
            False,
        ),
    ],
)
def test_litellm_exception_types_have_explicit_safe_classification(
    provider_error: Exception,
    attempt_code: str,
    terminal_code: str,
    retryable: bool,
) -> None:
    classification = classify_model_error(provider_error)

    assert classification.attempt_code == attempt_code
    assert classification.terminal_code == terminal_code
    assert classification.retryable is retryable
    assert "raw secret" not in classification.message


def test_unknown_error_classification_does_not_expose_original_message() -> None:
    classification = classify_model_error(RuntimeError("数据库密码 secret"))

    assert classification.attempt_code == "model_request_failed"
    assert classification.terminal_code == "model_request_failed"
    assert classification.message == "模型调用失败，请检查请求和模型配置。"
    assert classification.status_code == 502
    assert classification.retryable is False
    assert "secret" not in classification.message
