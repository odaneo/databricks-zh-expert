# 阶段 2：LiteLLM 模型网关实施计划

> **给后续 agentic workers 的说明：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行并在每个任务后复核。所有步骤使用复选框跟踪。

**目标：** 在现有 FastAPI 聊天链路中加入只支持 OpenAI 和 DeepSeek 的应用内模型网关，使每次请求可以通过固定业务别名选择模型，并在可重试故障时执行有审计记录的串行 fallback。

**架构：** `ModelRegistry` 负责固定白名单和环境配置解析，`LiteLLMTransport` 只执行一次无隐式重试的 Chat Completions 调用，`FallbackModelGateway` 负责候选顺序、错误分类和尝试产出。`ChatService` 消费异步尝试流，并在请求下一次 fallback 前把本次尝试写入 PostgreSQL 和本地 Trace。

**技术栈：** Python 3.12.10、uv 0.11.28、FastAPI 0.139.0、Pydantic 2.13.4、pydantic-settings 2.14.2、LiteLLM 1.91.1、SQLAlchemy 2.0.51、Alembic 1.18.5、PostgreSQL 18、pytest 9.1.1、Ruff 0.15.21、Pyright 1.1.411。

## 全局约束

1. Python 固定为 `3.12.10`，所有命令通过项目内 `.venv` 和 `uv run --locked` 执行。
2. 本阶段不新增 Python 依赖，不修改 `pyproject.toml` 或 `uv.lock` 中的依赖版本。
3. 供应商只允许 `openai` 和 `deepseek`，不得加入 Claude、Gemini、Azure OpenAI 或其他供应商。
4. API 只接受 `gpt5.5`、`gpt5.4mini`、`deepseek-v4-flash`、`deepseek-v4-pro` 四个业务别名，不接受 LiteLLM ID；四个实际 ID 固定在代码 `MODEL_SPECS` 中，不写入环境变量。
5. 默认开发配置固定为 `DEFAULT_MODEL=deepseek-v4-flash`、`FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini`、`DEFAULT_TEMPERATURE=0.2`。
6. 每次消息请求的 `model` 可选；省略时使用 `DEFAULT_MODEL`，temperature 不允许由请求覆盖。
7. 每个候选模型只调用一次，并向 LiteLLM 显式传入 `num_retries=0`。
8. 只有超时、HTTP 429、连接失败和供应商 HTTP 5xx 可以触发 fallback。
9. 非法别名、缺少密钥、认证或权限失败、错误参数、模型不存在、空响应和无效响应不得触发 fallback。
10. 每次实际模型尝试必须独立写入 `model_calls` 和 Trace；数据库写入失败时不得继续调用下一个模型。
11. HTTP、数据库、Trace 和应用日志均不得包含 API Key、认证头或供应商原始错误文本。
12. 外部模型调用期间不得持有数据库事务；Trace 写入失败只记录警告，不中断聊天和 fallback。
13. 自动测试不得访问真实模型网络；真实验收只各调用一次 `deepseek-v4-flash` 和 `gpt5.4mini`。
14. README 只保留启动所需步骤，不加入架构说明、测试案例或预期输出长文。
15. 所有新增文档、注释说明和用户可见错误使用中文；代码标识符、API 字段和环境变量使用英文。
16. 每次修改 Python 代码后必须运行 Ruff 格式、Ruff lint、Pyright、pytest 和覆盖率门禁。
17. 本阶段不实现 RAG、Prompt Registry、Responses API、流式响应、工具调用、LangGraph、成本金额计算或前端。

---

## 文件结构映射

```text
src/databricks_zh_expert/core/config.py              模型环境配置、CSV 解析和启动校验
src/databricks_zh_expert/llm/model_registry.py       固定业务别名、模型定义和配置状态
src/databricks_zh_expert/llm/client.py               传输层消息、请求结果和 Protocol
src/databricks_zh_expert/llm/litellm_client.py       单次 LiteLLM Chat Completions 传输适配器
src/databricks_zh_expert/llm/gateway.py              fallback 状态机、错误分类和 ModelAttempt
src/databricks_zh_expert/chat/service.py             尝试流消费、持久化顺序和 API 错误映射
src/databricks_zh_expert/chat/repository.py          扩展后的 model_calls 写入
src/databricks_zh_expert/chat/schemas.py             请求模型枚举和成功响应元数据
src/databricks_zh_expert/api/model_schemas.py        模型列表响应结构
src/databricks_zh_expert/api/models.py               GET /api/models
src/databricks_zh_expert/api/dependencies.py         Registry、Transport、Gateway 和 Service 装配
src/databricks_zh_expert/api/chat.py                 把请求模型传入 ChatService
src/databricks_zh_expert/db/models.py                model_calls 尝试分组字段和约束
src/databricks_zh_expert/observability/model_trace.py Trace 1.1 尝试元数据
src/databricks_zh_expert/main.py                     注册模型列表路由
alembic/versions/0002_model_gateway_attempts.py      历史数据回填和新约束迁移
tests/unit/test_model_registry.py                    白名单与注册表测试
tests/unit/test_litellm_client.py                    单次传输、参数能力和脱敏测试
tests/unit/test_model_gateway.py                     候选顺序、错误分类和 fallback 测试
tests/unit/test_chat_service.py                      每次尝试持久化及错误映射测试
tests/unit/test_model_trace.py                       Trace 1.1 序列化测试
tests/unit/test_config.py                            环境配置和启动校验测试
tests/unit/test_models.py                            SQLAlchemy 字段和约束测试
tests/integration/test_migrations.py                 迁移结构和历史数据回填测试
tests/integration/test_messages_api.py               请求选模和 fallback 持久化测试
tests/integration/test_models_api.py                 模型列表 API 测试
tests/conftest.py                                    阶段 2 Settings 工厂
.env.example                                         四个模型 ID、默认模型、fallback 和 temperature
README.md                                            最小启动配置步骤
docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md  同步阶段 2 配置键
```

---

### 任务 1：建立固定模型注册表和环境配置校验

**文件：**

- 创建：`src/databricks_zh_expert/llm/model_registry.py`
- 创建：`tests/unit/test_model_registry.py`
- 修改：`src/databricks_zh_expert/core/config.py`
- 修改：`src/databricks_zh_expert/llm/litellm_client.py`
- 修改：`tests/unit/test_config.py`
- 修改：`tests/unit/test_litellm_client.py`
- 修改：`tests/conftest.py`
- 修改：`.env.example`

**接口：**

- 产出：继承 `StrEnum` 的 `ModelAlias` 和 `ModelProvider`。
- 产出：不可变 `MODEL_SPECS`，作为四个业务别名、显示名、供应商和 LiteLLM ID 的唯一来源。
- 产出：`ModelDefinition(alias, display_name, provider, litellm_model, configured)`。
- 产出：`ModelRegistry.from_settings(settings: Settings) -> ModelRegistry`。
- 产出：`ModelRegistry.get(alias: ModelAlias) -> ModelDefinition` 和只读属性 `models`、`default_model`、`fallback_models`。
- 后续依赖：Task 2 使用 `ModelDefinition`，Task 3 使用注册表候选顺序，Task 6 使用 `configured` 构造模型列表 API。

- [x] **步骤 1：先写固定白名单和注册表失败测试**

在 `tests/unit/test_model_registry.py` 写入以下测试形状，四个别名的顺序也作为 API 稳定契约：

```python
from databricks_zh_expert.llm.model_registry import (
    MODEL_ALIASES,
    MODEL_SPECS,
    ModelAlias,
    ModelProvider,
    ModelRegistry,
)


def test_registry_exposes_only_the_fixed_model_aliases(settings_factory) -> None:
    registry = ModelRegistry.from_settings(
        settings_factory(openai_api_key="openai-key", deepseek_api_key=None)
    )

    assert MODEL_ALIASES == (
        ModelAlias.GPT_55,
        ModelAlias.GPT_54_MINI,
        ModelAlias.DEEPSEEK_V4_FLASH,
        ModelAlias.DEEPSEEK_V4_PRO,
    )
    assert [model.alias for model in registry.models] == list(MODEL_ALIASES)
    assert registry.get(ModelAlias.GPT_55).litellm_model == "openai/gpt-5.5"
    assert registry.get(ModelAlias.DEEPSEEK_V4_FLASH).provider is ModelProvider.DEEPSEEK


def test_model_specs_are_the_single_fixed_model_catalog() -> None:
    assert [spec.litellm_model for spec in MODEL_SPECS] == [
        "openai/gpt-5.5",
        "openai/gpt-5.4-mini",
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
    ]


def test_registry_reports_provider_key_configuration(settings_factory) -> None:
    registry = ModelRegistry.from_settings(
        settings_factory(openai_api_key="openai-key", deepseek_api_key=None)
    )

    assert registry.get(ModelAlias.GPT_54_MINI).configured is True
    assert registry.get(ModelAlias.DEEPSEEK_V4_PRO).configured is False
```

- [x] **步骤 2：补充 Settings 的失败测试矩阵**

在 `tests/unit/test_config.py` 固定以下行为：

```python
from typing import Any

import pytest
from pydantic import ValidationError


def test_fallback_models_parse_ordered_csv(settings_factory) -> None:
    settings = settings_factory(
        fallback_models="deepseek-v4-flash,gpt5.4mini",
    )
    assert settings.fallback_models == ("deepseek-v4-flash", "gpt5.4mini")


def test_empty_fallback_models_disable_fallback(settings_factory) -> None:
    assert settings_factory(fallback_models="").fallback_models == ()


@pytest.mark.parametrize(
    ("override", "expected_fragment"),
    [
        ({"default_model": "unknown"}, "default_model"),
        ({"fallback_models": "gpt5.5,gpt5.5"}, "不能包含重复项"),
        ({"default_temperature": -0.1}, "greater than or equal to 0"),
        ({"default_temperature": 2.1}, "less than or equal to 2"),
        ({"model_request_timeout_seconds": 0}, "greater than 0"),
    ],
)
def test_model_configuration_rejects_invalid_values(
    settings_factory,
    override: dict[str, Any],
    expected_fragment: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        settings_factory(**override)
    assert expected_fragment in str(error.value)
```

同时把 `FALLBACK_MODELS` 和 `DEFAULT_TEMPERATURE` 加入必填字段测试和环境变量清理列表，并断言四个固定模型 ID 不属于 `Settings.model_fields`。

- [x] **步骤 3：运行定向测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_model_registry.py tests/unit/test_config.py -v
```

预期：`MODEL_SPECS`、`StrEnum` 模型类型或阶段 2 Settings 字段尚未实现，测试失败；不得出现真实模型网络请求。

- [x] **步骤 4：实现模型类型和注册表**

`src/databricks_zh_expert/llm/model_registry.py` 使用以下完整公共结构：

```python
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from databricks_zh_expert.core.config import Settings


class ModelAlias(StrEnum):
    GPT_55 = "gpt5.5"
    GPT_54_MINI = "gpt5.4mini"
    DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
    DEEPSEEK_V4_PRO = "deepseek-v4-pro"


class ModelProvider(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    alias: ModelAlias
    display_name: str
    provider: ModelProvider
    litellm_model: str


MODEL_SPECS: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(ModelAlias.GPT_55, "GPT-5.5", ModelProvider.OPENAI, "openai/gpt-5.5"),
    ModelSpec(
        ModelAlias.GPT_54_MINI,
        "GPT-5.4 mini",
        ModelProvider.OPENAI,
        "openai/gpt-5.4-mini",
    ),
    ModelSpec(
        ModelAlias.DEEPSEEK_V4_FLASH,
        "DeepSeek V4 Flash",
        ModelProvider.DEEPSEEK,
        "deepseek/deepseek-v4-flash",
    ),
    ModelSpec(
        ModelAlias.DEEPSEEK_V4_PRO,
        "DeepSeek V4 Pro",
        ModelProvider.DEEPSEEK,
        "deepseek/deepseek-v4-pro",
    ),
)
MODEL_ALIASES: Final[tuple[ModelAlias, ...]] = tuple(spec.alias for spec in MODEL_SPECS)


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    alias: ModelAlias
    display_name: str
    provider: ModelProvider
    litellm_model: str
    configured: bool


class ModelRegistry:
    def __init__(
        self,
        *,
        default_model: ModelAlias,
        fallback_models: tuple[ModelAlias, ...],
        models: tuple[ModelDefinition, ...],
    ) -> None:
        self._default_model = default_model
        self._fallback_models = fallback_models
        self._models = models
        self._by_alias = {model.alias: model for model in models}

    @property
    def default_model(self) -> ModelAlias:
        return self._default_model

    @property
    def fallback_models(self) -> tuple[ModelAlias, ...]:
        return self._fallback_models

    @property
    def models(self) -> tuple[ModelDefinition, ...]:
        return self._models

    @classmethod
    def from_settings(cls, settings: "Settings") -> "ModelRegistry":
        provider_configuration = {
            ModelProvider.OPENAI: bool(
                settings.openai_api_key
                and settings.openai_api_key.get_secret_value().strip()
            ),
            ModelProvider.DEEPSEEK: bool(
                settings.deepseek_api_key
                and settings.deepseek_api_key.get_secret_value().strip()
            ),
        }
        return cls(
            default_model=settings.default_model,
            fallback_models=settings.fallback_models,
            models=tuple(
                ModelDefinition(
                    alias=spec.alias,
                    display_name=spec.display_name,
                    provider=spec.provider,
                    litellm_model=spec.litellm_model,
                    configured=provider_configuration[spec.provider],
                )
                for spec in MODEL_SPECS
            ),
        )

    def get(self, alias: ModelAlias) -> ModelDefinition:
        return self._by_alias[alias]
```

四个 provider-qualified ID 只允许出现在 `MODEL_SPECS`；Settings、`.env.example` 和测试工厂不得再定义一份。

- [x] **步骤 5：实现 Settings 的 CSV 解析和启动校验**

`src/databricks_zh_expert/core/config.py` 使用以下完整结构；所有部署字段继续由 `.env` 或进程环境注入，不在 Python 中设置部署默认值：

```python
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from databricks_zh_expert.llm.model_registry import ModelAlias

FallbackModels = Annotated[tuple[ModelAlias, ...], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str
    app_env: str
    app_host: str
    app_port: int
    log_level: str
    model_request_timeout_seconds: int = Field(gt=0)
    model_trace_enabled: bool
    model_trace_path: Path
    default_model: ModelAlias
    fallback_models: FallbackModels
    default_temperature: float = Field(ge=0, le=2)
    openai_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    database_url: str
    postgres_schema: str

    @field_validator("fallback_models", mode="before")
    @classmethod
    def parse_fallback_models(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return ()
        return tuple(item.strip() for item in value.split(","))

    @model_validator(mode="after")
    def validate_model_configuration(self) -> Self:
        if len(set(self.fallback_models)) != len(self.fallback_models):
            raise ValueError("FALLBACK_MODELS 不能包含重复项。")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
```

- [x] **步骤 6：保持阶段 1 LiteLLM 客户端在配置迁移期间可用**

`DEFAULT_MODEL` 改为业务别名后，先把现有 `LiteLLMModelClient.model` 改为通过注册表解析实际 ID：

```python
@property
def model(self) -> str:
    registry = ModelRegistry.from_settings(self._settings)
    return registry.get(registry.default_model).litellm_model
```

`provider` 继续从这个 provider-qualified ID 读取前缀。`tests/unit/test_litellm_client.py` 中选择 OpenAI 的 Settings 改为 `default_model="gpt5.4mini"`，实际请求断言仍为 `openai/gpt-5.4-mini`。这样 Task 1 提交后，现有 ChatService 仍能使用默认模型；Task 2 再把调用逻辑收窄到 Transport。

- [x] **步骤 7：同步测试 Settings 工厂和环境模板**

`tests/conftest.py` 的 `SettingsFactory` Protocol 与 `create_settings()` 增加完全相同的参数：

```python
default_model: str = "deepseek-v4-flash"
fallback_models: str | tuple[str, ...] = "deepseek-v4-flash,gpt5.4mini"
default_temperature: float = 0.2
```

`.env.example` 的模型段落替换为：

```dotenv
# 模型网关配置（必填）
DEFAULT_MODEL=deepseek-v4-flash
FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini
DEFAULT_TEMPERATURE=0.2
MODEL_REQUEST_TIMEOUT_SECONDS=60
MODEL_TRACE_ENABLED=true
MODEL_TRACE_PATH=.local/logs/model-calls.jsonl
```

- [x] **步骤 8：运行任务 1 测试和静态检查**

```powershell
uv run --locked pytest tests/unit/test_model_registry.py tests/unit/test_config.py tests/unit/test_litellm_client.py -v
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
```

预期：定向测试全部通过，Ruff 与 Pyright 为 0 errors；`uv lock --check` 不报告锁文件变化。

- [x] **步骤 9：建议提交点**

```powershell
git add .env.example src/databricks_zh_expert/core/config.py src/databricks_zh_expert/llm/model_registry.py src/databricks_zh_expert/llm/litellm_client.py tests/conftest.py tests/unit/test_config.py tests/unit/test_litellm_client.py tests/unit/test_model_registry.py
git commit -m "feat: add fixed model registry configuration"
```

---

### 任务 2：把 LiteLLM 客户端收窄为单次传输适配器

**文件：**

- 修改：`src/databricks_zh_expert/llm/client.py`
- 修改：`src/databricks_zh_expert/llm/litellm_client.py`
- 修改：`tests/unit/test_litellm_client.py`

**接口：**

- 消费：Task 1 的 `ModelDefinition`。
- 产出：`ModelTransport.build_request(model, messages) -> JsonObject`。
- 产出：`await ModelTransport.complete(model, request) -> ModelTransportResult`。
- 产出：`LiteLLMTransport(settings, completion=None, supported_params=None)`。
- 保证：每次 `complete()` 只调用一次 `litellm.acompletion()`，且 `request` 不包含 API Key、timeout 或 SDK 重试参数。

- [ ] **步骤 1：先改写传输层失败测试**

`tests/unit/test_litellm_client.py` 使用显式 `ModelDefinition`，固定以下行为：

```python
def make_deepseek_model(configured: bool = True) -> ModelDefinition:
    return ModelDefinition(
        alias="deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        provider="deepseek",
        litellm_model="deepseek/deepseek-v4-flash",
        configured=configured,
    )


def test_build_request_adds_temperature_only_when_supported(settings_factory) -> None:
    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="key"),
        supported_params=lambda **kwargs: ["temperature"],
    )
    request = transport.build_request(
        make_deepseek_model(),
        [ModelMessage(role="user", content="你好")],
    )
    assert request == {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0.2,
    }


def test_build_request_omits_unsupported_temperature(settings_factory) -> None:
    transport = LiteLLMTransport(
        settings_factory(deepseek_api_key="key"),
        supported_params=lambda **kwargs: [],
    )
    request = transport.build_request(make_deepseek_model(), [])
    assert "temperature" not in request
```

把现有成功响应、usage 缺失、空响应、响应脱敏和安全回退测试迁移到 `LiteLLMTransport`，并把实际调用断言固定为：

```python
assert captured == {
    "model": "deepseek/deepseek-v4-flash",
    "messages": [{"role": "user", "content": "生成 Markdown"}],
    "temperature": 0.2,
    "timeout": 60,
    "api_key": "local-test-key",
    "num_retries": 0,
}
```

- [ ] **步骤 2：运行传输测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_litellm_client.py -v
```

预期：`LiteLLMTransport`、`ModelTransportResult` 和新方法尚不存在，测试失败。

- [ ] **步骤 3：定义传输层契约并保留短期兼容接口**

`src/databricks_zh_expert/llm/client.py` 保留 JSON 类型、`ModelMessage`、阶段 1 的 `ModelClient` 与 `ModelResult`，并新增以下接口。旧接口在 Task 5 完成 ChatService 切换后删除，使 Task 2 提交后现有聊天链路仍可导入和运行：

```python
from dataclasses import dataclass
from typing import Literal, Protocol

from databricks_zh_expert.llm.model_registry import ModelDefinition


@dataclass(frozen=True, slots=True)
class ModelTransportResult:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    api_response: JsonObject


class ModelTransport(Protocol):
    def build_request(
        self,
        model: ModelDefinition,
        messages: list[ModelMessage],
    ) -> JsonObject: ...

    async def complete(
        self,
        model: ModelDefinition,
        request: JsonObject,
    ) -> ModelTransportResult: ...
```

- [ ] **步骤 4：实现请求能力检查**

在现有文件中新增 `LiteLLMTransport`。构造函数注入 `litellm.acompletion` 和 `litellm.get_supported_openai_params`，`build_request()` 必须：

```python
supported = self._supported_params(
    model=model.litellm_model,
    custom_llm_provider=model.provider,
    request_type="chat_completion",
) or []
request: JsonObject = {
    "model": model.litellm_model,
    "messages": [
        {"role": message.role, "content": message.content}
        for message in messages
    ],
}
if "temperature" in supported:
    request["temperature"] = self._settings.default_temperature
return request
```

该方法只使用 LiteLLM 本地能力表，不进行网络请求。Trace 后续直接记录这个返回值，因此不得加入 `api_key`、`timeout` 或 `num_retries`。

- [ ] **步骤 5：实现单次 complete 调用**

`complete()` 根据 `model.provider` 选择 SecretStr；缺少密钥时抛出阶段 1 已有的安全错误：

```python
AppError(
    code="model_not_configured",
    message="当前模型尚未配置 API 密钥。",
    status_code=503,
    details={"provider": model.provider, "model": model.alias},
)
```

实际调用固定为：

```python
kwargs: dict[str, Any] = dict(request)
kwargs.update(
    timeout=self._settings.model_request_timeout_seconds,
    api_key=api_key,
    num_retries=0,
)
response = await self._completion(**kwargs)
```

沿用现有响应读取、空响应拒绝、usage 提取和递归脱敏逻辑，传输接口返回 `ModelTransportResult`；安全回退响应中的 `model` 使用 `model.litellm_model`。

阶段 1 的 `LiteLLMModelClient` 暂时改为薄包装器：从 `ModelRegistry` 取默认定义，调用同文件的 `LiteLLMTransport.build_request()` 和 `complete()`，再把结果映射回旧 `ModelResult`。包装器继续暴露 `provider`、`model` 和 `complete(messages)`，其中 `model` 返回实际 provider-qualified ID。Task 5 删除该包装器及旧协议。

- [ ] **步骤 6：运行任务 2 定向检查**

```powershell
uv run --locked pytest tests/unit/test_litellm_client.py -v
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
```

预期：传输测试全部通过，Fake completion 只收到一次调用，且捕获参数明确包含 `num_retries=0`。

- [ ] **步骤 7：建议提交点**

```powershell
git add src/databricks_zh_expert/llm/client.py src/databricks_zh_expert/llm/litellm_client.py tests/unit/test_litellm_client.py
git commit -m "refactor: add single attempt litellm transport"
```

---

### 任务 3：实现 fallback 状态机和安全错误分类

**文件：**

- 创建：`src/databricks_zh_expert/llm/gateway.py`
- 创建：`tests/unit/test_model_gateway.py`

**接口：**

- 消费：Task 1 的 `ModelRegistry`，Task 2 的 `ModelTransport`。
- 产出：`ModelAttempt`，字段固定为 `invocation_id`、`requested_model`、`model_alias`、`provider`、`litellm_model`、`attempt_number`、`request`、`response`、`content`、`prompt_tokens`、`completion_tokens`、`latency_ms`、`success`、`retryable`、`error`。
- 产出：`ModelGateway.run(messages, requested_model) -> AsyncIterator[ModelAttempt]`。
- 产出：`FallbackModelGateway(registry, transport)` 和终止异常 `ModelGatewayFailure`。

- [ ] **步骤 1：先写候选顺序和默认模型失败测试**

`tests/unit/test_model_gateway.py` 创建不会联网的 `FakeModelTransport`，其 `build_request()` 返回标准 Chat Completions 请求，其 `complete()` 按模型别名弹出预设结果或异常。固定以下断言：

```python
async def collect(gateway, requested_model=None) -> list[ModelAttempt]:
    return [
        attempt
        async for attempt in gateway.run(
            [ModelMessage(role="user", content="测试")],
            requested_model,
        )
    ]


@pytest.mark.asyncio
async def test_missing_request_model_uses_default_and_skips_duplicate_fallback(
    gateway_factory,
) -> None:
    gateway, transport = gateway_factory(success_alias="deepseek-v4-flash")
    attempts = await collect(gateway)

    assert [attempt.model_alias for attempt in attempts] == ["deepseek-v4-flash"]
    assert transport.called_aliases == ["deepseek-v4-flash"]
    assert attempts[0].requested_model == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_explicit_request_model_overrides_default(gateway_factory) -> None:
    gateway, transport = gateway_factory(success_alias="gpt5.5")
    attempts = await collect(gateway, "gpt5.5")
    assert transport.called_aliases == ["gpt5.5"]
    assert attempts[0].requested_model == "gpt5.5"
```

- [ ] **步骤 2：先写 fallback 与终止错误失败测试**

使用带 `status_code` 的 Fake provider exception，精确覆盖：

```python
@pytest.mark.asyncio
async def test_retryable_429_falls_back_and_keeps_one_invocation_id(
    gateway_factory,
) -> None:
    gateway, _ = gateway_factory(
        outcomes={
            "gpt5.5": FakeProviderError(429),
            "deepseek-v4-flash": make_transport_result("成功"),
        },
        fallback_models=("deepseek-v4-flash",),
    )
    attempts = await collect(gateway, "gpt5.5")

    assert [attempt.success for attempt in attempts] == [False, True]
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert len({attempt.invocation_id for attempt in attempts}) == 1
    assert attempts[0].retryable is True


@pytest.mark.asyncio
async def test_authentication_failure_does_not_fallback(gateway_factory) -> None:
    gateway, transport = gateway_factory(
        outcomes={"gpt5.5": FakeProviderError(401)},
        fallback_models=("deepseek-v4-flash",),
    )
    iterator = gateway.run([], "gpt5.5")
    failed_attempt = await anext(iterator)
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)

    assert failed_attempt.retryable is False
    assert error.value.code == "model_authentication_failed"
    assert transport.called_aliases == ["gpt5.5"]


@pytest.mark.asyncio
async def test_all_retryable_candidates_raise_fallback_exhausted(gateway_factory) -> None:
    gateway, _ = gateway_factory(
        outcomes={
            "gpt5.5": FakeProviderError(429),
            "deepseek-v4-flash": FakeProviderError(503),
        },
        fallback_models=("deepseek-v4-flash",),
    )
    iterator = gateway.run([], "gpt5.5")
    assert (await anext(iterator)).attempt_number == 1
    assert (await anext(iterator)).attempt_number == 2
    with pytest.raises(ModelGatewayFailure) as error:
        await anext(iterator)
    assert error.value.code == "model_fallback_exhausted"
```

再用参数化测试断言 400、401、403、404、空响应 `AppError` 和 `model_not_configured` 均不请求第二个模型；429、500、502、503、504 会请求下一候选。

- [ ] **步骤 3：运行网关测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_model_gateway.py -v
```

预期：`gateway.py` 尚不存在，测试失败。

- [ ] **步骤 4：定义尝试结果和终止异常**

`src/databricks_zh_expert/llm/gateway.py` 定义：

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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
```

- [ ] **步骤 5：实现不解析异常文本的错误分类**

定义内部不可变 `ErrorClassification`，并严格使用异常类型和 `status_code`：

```python
RETRYABLE_EXCEPTION_TYPES = (
    litellm.Timeout,
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
)


@dataclass(frozen=True, slots=True)
class ErrorClassification:
    attempt_code: str
    terminal_code: str
    message: str
    status_code: int
    retryable: bool
```

分类表固定为：

| 条件 | `attempt_code` | `terminal_code` | 可重试 |
| --- | --- | --- | --- |
| `litellm.Timeout` | `model_timeout` | `model_fallback_exhausted` | 是 |
| `litellm.RateLimitError` 或 429 | `model_rate_limited` | `model_fallback_exhausted` | 是 |
| `litellm.APIConnectionError` | `model_connection_failed` | `model_fallback_exhausted` | 是 |
| LiteLLM 5xx 类型或状态码 500-599 | `model_provider_unavailable` | `model_fallback_exhausted` | 是 |
| `AppError.code == model_not_configured` | `model_not_configured` | `model_not_configured` | 否 |
| `litellm.AuthenticationError` 或 401/403 | `model_authentication_failed` | `model_authentication_failed` | 否 |
| `litellm.BadRequestError`、`litellm.NotFoundError`、400/404、空响应、无效响应及未知异常 | `model_request_failed` | `model_request_failed` | 否 |

终止 HTTP 状态固定为：`model_not_configured` 和 `model_authentication_failed` 使用 503，`model_request_failed` 和 `model_fallback_exhausted` 使用 502。

安全错误对象固定为：

```python
{
    "message": classification.message,
    "type": type(error).__name__,
    "param": None,
    "code": classification.attempt_code,
}
```

其中可重试错误摘要统一为“模型服务暂时不可用。”，认证错误为“模型认证或权限校验失败。”，其他错误为“模型调用失败，请检查请求和模型配置。”；不得使用 `str(error)`。

- [ ] **步骤 6：实现串行 fallback 异步生成器**

`FallbackModelGateway.run()` 按以下结构实现：

辅助函数签名固定为：

```python
def elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def classify_model_error(error: Exception) -> ErrorClassification:
    status_code = getattr(error, "status_code", None)
    if isinstance(error, AppError) and error.code == "model_not_configured":
        return ErrorClassification(
            "model_not_configured",
            "model_not_configured",
            "当前模型尚未配置 API 密钥。",
            503,
            False,
        )
    if isinstance(error, litellm.Timeout):
        attempt_code = "model_timeout"
    elif isinstance(error, litellm.RateLimitError) or status_code == 429:
        attempt_code = "model_rate_limited"
    elif isinstance(error, litellm.APIConnectionError):
        attempt_code = "model_connection_failed"
    elif isinstance(
        error,
        (litellm.InternalServerError, litellm.ServiceUnavailableError),
    ) or (isinstance(status_code, int) and 500 <= status_code <= 599):
        attempt_code = "model_provider_unavailable"
    else:
        attempt_code = ""

    if attempt_code:
        return ErrorClassification(
            attempt_code,
            "model_fallback_exhausted",
            "模型服务暂时不可用。",
            502,
            True,
        )
    if isinstance(error, litellm.AuthenticationError) or status_code in (401, 403):
        return ErrorClassification(
            "model_authentication_failed",
            "model_authentication_failed",
            "模型认证或权限校验失败。",
            503,
            False,
        )
    return ErrorClassification(
        "model_request_failed",
        "model_request_failed",
        "模型调用失败，请检查请求和模型配置。",
        502,
        False,
    )

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
```

这些函数只能按本任务定义的字段映射构造值，不执行 I/O；`classify_model_error()` 完整实现上一张分类表。

```python
resolved_model = requested_model or self._registry.default_model
candidates = tuple(
    dict.fromkeys((resolved_model, *self._registry.fallback_models))
)
invocation_id = uuid4()

for attempt_number, alias in enumerate(candidates, start=1):
    definition = self._registry.get(alias)
    request = {
        "model": definition.litellm_model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
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
    "model_fallback_exhausted",
    "模型调用失败，请稍后重试。",
    502,
)
```

`elapsed_ms()` 使用 `max(0, round((time.perf_counter() - started_at) * 1000))`。成功尝试的 `retryable=False`、`error=None`；失败尝试的 `response=None`、`content=None`、token 为 `None`。

- [ ] **步骤 7：运行任务 3 定向检查**

```powershell
uv run --locked pytest tests/unit/test_model_gateway.py -v
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
```

预期：所有候选顺序和错误矩阵测试通过；测试中的 Fake transport 明确证明每个候选最多调用一次。

- [ ] **步骤 8：建议提交点**

```powershell
git add src/databricks_zh_expert/llm/gateway.py tests/unit/test_model_gateway.py
git commit -m "feat: add model gateway fallback state machine"
```

---

### 任务 4：扩展 model_calls 并迁移历史审计数据

**文件：**

- 创建：`alembic/versions/0002_model_gateway_attempts.py`
- 修改：`src/databricks_zh_expert/db/models.py`
- 修改：`src/databricks_zh_expert/chat/repository.py`
- 修改：`tests/unit/test_models.py`
- 修改：`tests/integration/test_migrations.py`

**接口：**

- 消费：Task 3 的 `ModelAttempt` 字段定义。
- 产出：`model_calls.invocation_id`、`model_alias`、`attempt_number`、`retryable`、`error_code`。
- 产出：唯一约束 `uq_model_calls_invocation_attempt` 和检查约束 `ck_model_calls_attempt_number`。
- 产出：扩展后的 `ChatRepository.create_model_call()`，最终参数由 Task 5 全部传入。

- [ ] **步骤 1：先写 SQLAlchemy 元数据失败测试**

在 `tests/unit/test_models.py` 把 `ModelCall` 字段断言改为：

```python
assert set(ModelCall.__table__.columns.keys()) == {
    "id",
    "session_id",
    "invocation_id",
    "provider",
    "model",
    "model_alias",
    "attempt_number",
    "prompt_tokens",
    "completion_tokens",
    "latency_ms",
    "success",
    "retryable",
    "error_code",
    "error_message",
    "created_at",
}
```

并检查约束名称和索引集合：

```python
constraint_names = {constraint.name for constraint in ModelCall.__table__.constraints}
assert "uq_model_calls_invocation_attempt" in constraint_names
assert "ck_model_calls_attempt_number" in constraint_names
assert {index.name for index in ModelCall.__table__.indexes} == {
    "ix_model_calls_session_created_at"
}
```

- [ ] **步骤 2：同步未提交的本地模型配置**

在 `.env` 中补入 Task 1 的 `FALLBACK_MODELS` 和 `DEFAULT_TEMPERATURE`，把旧的 provider-qualified `DEFAULT_MODEL` 改为业务别名 `deepseek-v4-flash`。四个固定模型 ID 不写入 `.env`；保留现有真实 API Key，不提交 `.env`。

- [ ] **步骤 3：先写迁移结构和历史回填失败测试**

`tests/integration/test_migrations.py` 增加结构断言：

```python
model_call_columns = await connection.run_sync(
    lambda sync_connection: {
        column["name"]: column
        for column in inspect(sync_connection).get_columns("model_calls")
    }
)
assert model_call_columns["invocation_id"]["nullable"] is False
assert model_call_columns["model_alias"]["nullable"] is False
assert model_call_columns["attempt_number"]["nullable"] is False
assert model_call_columns["retryable"]["nullable"] is False
assert model_call_columns["error_code"]["nullable"] is True
```

再增加同步迁移测试 `test_model_gateway_migration_backfills_historical_calls`，测试顺序固定为：

1. 通过 `monkeypatch.setenv("DATABASE_URL", test_database_url)` 指向名称以 `_test` 结尾的数据库，并在 Alembic 调用前后执行 `get_settings.cache_clear()`。
2. 执行 `command.downgrade(Config("alembic.ini"), "0001_initial")`。
3. 使用 `psycopg.connect(make_url(test_database_url).set(drivername="postgresql").render_as_string(hide_password=False))` 插入一个会话和两条旧 `model_calls`：模型分别为 `openai/gpt-5.5` 和 `custom/legacy-model`。
4. 执行 `command.upgrade(config, "head")`。
5. 查询并断言：两行 `invocation_id == id`、`attempt_number == 1`、`retryable is false`、`error_code is null`；已知模型映射为 `gpt5.5`，未知模型保留为 `custom/legacy-model`。
6. 在 `finally` 中执行 `command.upgrade(config, "head")`，确保后续测试始终面对最新 schema。

该测试不启用 pytest-xdist，迁移期间不得并行运行其他数据库测试。

- [ ] **步骤 4：运行模型和迁移测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py -v
```

预期：新列和迁移 revision 尚不存在，测试失败；失败原因不得是连接到开发数据库。

- [ ] **步骤 5：扩展 SQLAlchemy ModelCall**

`src/databricks_zh_expert/db/models.py` 的 `ModelCall` 使用：

```python
class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_model_calls_attempt_number"),
        UniqueConstraint(
            "invocation_id",
            "attempt_number",
            name="uq_model_calls_invocation_attempt",
        ),
        Index("ix_model_calls_session_created_at", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    invocation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
```

- [ ] **步骤 6：实现 0002 迁移和历史映射**

创建 `alembic/versions/0002_model_gateway_attempts.py`，revision 固定为 `0002_model_gateway_attempts`，`down_revision="0001_initial"`。`upgrade()` 顺序固定为：

```python
op.add_column(
    "model_calls",
    sa.Column("invocation_id", postgresql.UUID(as_uuid=True), nullable=True),
)
op.add_column("model_calls", sa.Column("model_alias", sa.String(100), nullable=True))
op.add_column("model_calls", sa.Column("attempt_number", sa.Integer(), nullable=True))
op.add_column("model_calls", sa.Column("retryable", sa.Boolean(), nullable=True))
op.add_column("model_calls", sa.Column("error_code", sa.String(100), nullable=True))

op.execute(
    """
    UPDATE model_calls
    SET invocation_id = id,
        model_alias = CASE model
            WHEN 'openai/gpt-5.5' THEN 'gpt5.5'
            WHEN 'openai/gpt-5.4-mini' THEN 'gpt5.4mini'
            WHEN 'deepseek/deepseek-v4-flash' THEN 'deepseek-v4-flash'
            WHEN 'deepseek/deepseek-v4-pro' THEN 'deepseek-v4-pro'
            ELSE model
        END,
        attempt_number = 1,
        retryable = false
    """
)

op.alter_column("model_calls", "invocation_id", nullable=False)
op.alter_column("model_calls", "model_alias", nullable=False)
op.alter_column("model_calls", "attempt_number", nullable=False)
op.alter_column("model_calls", "retryable", nullable=False)
op.create_check_constraint(
    "ck_model_calls_attempt_number",
    "model_calls",
    "attempt_number >= 1",
)
op.create_unique_constraint(
    "uq_model_calls_invocation_attempt",
    "model_calls",
    ["invocation_id", "attempt_number"],
)
```

`downgrade()` 先删除唯一约束和检查约束，再按 `error_code`、`retryable`、`attempt_number`、`model_alias`、`invocation_id` 的顺序删列。不要额外创建与唯一约束重复的索引。

- [ ] **步骤 7：扩展 Repository 写入参数**

`ChatRepository.create_model_call()` 最终签名固定为：

```python
async def create_model_call(
    self,
    *,
    session_id: UUID,
    invocation_id: UUID,
    provider: str,
    model: str,
    model_alias: str,
    attempt_number: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
    success: bool,
    retryable: bool,
    error_code: str | None,
    error_message: str | None,
) -> ModelCall:
```

构造 `ModelCall` 时逐字段传入，不从 `model` 猜测 alias，不在 Repository 中实现 fallback 规则。Task 5 同一提交批次内同步所有调用方和 Fake Repository 后，再运行完整测试。

- [ ] **步骤 8：执行开发库、测试库迁移和定向测试**

```powershell
uv run --locked alembic upgrade head
$env:DATABASE_URL="postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent_test"
uv run --locked alembic upgrade head
Remove-Item Env:DATABASE_URL
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py -v
uv run --locked alembic check
```

预期：开发库和测试库均位于 `0002_model_gateway_attempts`；结构、历史回填和 Alembic drift 检查通过。

- [ ] **步骤 9：建议提交点**

该提交和 Task 5 的服务调用方修改连续执行，避免把 Repository 新签名单独推送为不可运行版本。Task 5 验证通过后统一提交以下文件。

---

### 任务 5：让 ChatService 持久化每次尝试并升级 Trace 1.1

**文件：**

- 修改：`src/databricks_zh_expert/chat/service.py`
- 修改：`src/databricks_zh_expert/observability/model_trace.py`
- 修改：`src/databricks_zh_expert/llm/client.py`
- 修改：`src/databricks_zh_expert/llm/litellm_client.py`
- 修改：`tests/unit/test_chat_service.py`
- 修改：`tests/unit/test_model_trace.py`

**接口：**

- 消费：Task 3 的 `ModelGateway` 和 `ModelAttempt`，Task 4 的 Repository 签名。
- 产出：`ChatService.send_message(session_id, content, requested_model=None) -> SendMessageResult`。
- 产出：`SendMessageResult` 的 `model_invocation_id`、`requested_model`、`used_model`、`fallback_used`、`attempt_count` 和最终成功 `model_call`。
- 产出：Trace `schema_version="1.1"`，每次尝试一行。

- [ ] **步骤 1：先把 ChatService Fake 切换为异步尝试流**

在 `tests/unit/test_chat_service.py` 删除 `FakeModelClient`，新增实现 `ModelGateway` 的 Fake。成功与 fallback 测试使用同一个 `invocation_id`，并返回完整 `ModelAttempt`。关键成功断言固定为：

```python
result = await service.send_message(
    session.id,
    "设计一个销售工作流",
    "gpt5.5",
)

assert result.requested_model == "gpt5.5"
assert result.used_model == "gpt5.4mini"
assert result.fallback_used is True
assert result.attempt_count == 2
assert result.model_call.id == repository.model_calls[1].id
assert [call.attempt_number for call in repository.model_calls] == [1, 2]
assert repository.model_calls[0].success is False
assert repository.model_calls[1].success is True
assert repository.model_calls[0].invocation_id == repository.model_calls[1].invocation_id
```

Fake Repository 的事件断言固定为：

```python
assert repository.events[-4:] == [
    "message:user",
    "model_call:1",
    "model_call:2",
    "message:assistant",
]
```

- [ ] **步骤 2：先写数据库失败不得继续 fallback 的测试**

Fake Repository 在第一次 `create_model_call()` 抛出 `RuntimeError("数据库写入失败")`，Fake Gateway 在第一次 yield 后只有被继续迭代才记录 `resumed=True`：

```python
with pytest.raises(RuntimeError, match="数据库写入失败"):
    await service.send_message(session.id, "测试", "gpt5.5")

assert fake_gateway.resumed is False
assert [message.role for message in repository.messages] == ["user"]
```

再覆盖：不可重试失败映射为对应 `AppError`；全部可重试失败映射为 `model_fallback_exhausted`；失败时不创建 assistant message；每个已产出尝试各写一次 Trace。

- [ ] **步骤 3：先写 Trace 1.1 失败测试**

`tests/unit/test_model_trace.py` 的 `make_trace()` 增加：

```python
invocation_id=uuid4(),
requested_model="gpt5.5",
model_alias="gpt5.4mini",
attempt_number=2,
retryable=False,
```

序列化断言改为：

```python
assert payload["schema_version"] == "1.1"
assert payload["trace"] == {
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
}
```

- [ ] **步骤 4：运行服务和 Trace 测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_chat_service.py tests/unit/test_model_trace.py -v
```

预期：ChatService 仍依赖 `ModelClient`，Trace 仍输出 1.0，测试失败。

- [ ] **步骤 5：实现 ChatService 的逐次持久化顺序**

`SendMessageResult` 定义为：

```python
@dataclass(frozen=True, slots=True)
class SendMessageResult:
    user_message: Message
    assistant_message: Message
    model_call: ModelCall
    model_invocation_id: UUID
    requested_model: ModelAlias
    used_model: ModelAlias
    fallback_used: bool
    attempt_count: int
```

构造函数把 `model_client` 改为 `model_gateway: ModelGateway`。保留会话检查、先保存 user message 和最近 20 条消息逻辑，然后按以下顺序消费：

```python
try:
    async for attempt in self.model_gateway.run(model_messages, requested_model):
        error_code = (
            str(attempt.error["code"])
            if attempt.error is not None and attempt.error.get("code") is not None
            else None
        )
        error_message = (
            str(attempt.error["message"])
            if attempt.error is not None and attempt.error.get("message") is not None
            else None
        )
        model_call = await self.repository.create_model_call(
            session_id=session_id,
            invocation_id=attempt.invocation_id,
            provider=attempt.provider,
            model=attempt.litellm_model,
            model_alias=attempt.model_alias,
            attempt_number=attempt.attempt_number,
            prompt_tokens=attempt.prompt_tokens,
            completion_tokens=attempt.completion_tokens,
            latency_ms=attempt.latency_ms,
            success=attempt.success,
            retryable=attempt.retryable,
            error_code=error_code,
            error_message=error_message,
        )
        await self.trace_sink.write(build_trace(model_call, session_id, attempt))

        if attempt.success:
            if attempt.content is None:
                raise RuntimeError("成功的模型尝试缺少输出内容。")
            assistant_message = await self.repository.create_message(
                session_id,
                "assistant",
                attempt.content,
            )
            return SendMessageResult(
                user_message=user_message,
                assistant_message=assistant_message,
                model_call=model_call,
                model_invocation_id=attempt.invocation_id,
                requested_model=attempt.requested_model,
                used_model=attempt.model_alias,
                fallback_used=attempt.attempt_number > 1,
                attempt_count=attempt.attempt_number,
            )
except ModelGatewayFailure as error:
    raise AppError(
        code=error.code,
        message=error.message,
        status_code=error.status_code,
    ) from None
```

异步迭代器正常结束但没有成功尝试时抛出 `RuntimeError("模型网关未返回成功尝试。")`；该情况只代表网关实现违反内部契约。

- [ ] **步骤 6：升级 ModelCallTrace 和 JSONL schema**

`ModelCallTrace` 增加精确字段：

```python
invocation_id: UUID
requested_model: ModelAlias
model_alias: ModelAlias
attempt_number: int
retryable: bool
```

`chat/service.py` 中的纯映射辅助函数签名和实现固定为：

```python
def build_trace(
    model_call: ModelCall,
    session_id: UUID,
    attempt: ModelAttempt,
) -> ModelCallTrace:
    return ModelCallTrace(
        model_call_id=model_call.id,
        invocation_id=attempt.invocation_id,
        session_id=session_id,
        recorded_at=model_call.created_at,
        requested_model=attempt.requested_model,
        model_alias=attempt.model_alias,
        provider=attempt.provider,
        attempt_number=attempt.attempt_number,
        latency_ms=attempt.latency_ms,
        success=attempt.success,
        retryable=attempt.retryable,
        request=attempt.request,
        response=attempt.response,
        error=attempt.error,
    )
```

`JsonlModelTraceSink._serialize()` 把 `schema_version` 改为 `1.1`，并把以上字段写入 `trace`。保留顶层 `protocol="openai.chat.completions"`、`request`、`response`、`error`；成功行 `error=None`，失败行 `response=None`。旧 JSONL 文件不迁移、不覆盖。

- [ ] **步骤 7：删除阶段 1 的临时模型客户端接口**

确认 ChatService 和依赖装配不再引用后，从 `llm/client.py` 删除 `ModelResult`、`ModelClient`，从 `llm/litellm_client.py` 删除 Task 2 保留的 `LiteLLMModelClient` 薄包装器。项目中只保留 `ModelTransport`、`LiteLLMTransport` 和 `ModelGateway` 三个边界。

- [ ] **步骤 8：运行任务 4 和任务 5 的联合门禁**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py -v
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
```

预期：迁移、Repository、服务和 Trace 测试全部通过；Pyright 不再出现旧 `ModelClient` 引用。

- [ ] **步骤 9：建议提交点**

```powershell
git add alembic/versions/0002_model_gateway_attempts.py src/databricks_zh_expert/db/models.py src/databricks_zh_expert/chat/repository.py src/databricks_zh_expert/chat/service.py src/databricks_zh_expert/observability/model_trace.py src/databricks_zh_expert/llm tests/unit/test_models.py tests/integration/test_migrations.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py
git commit -m "feat: persist model gateway attempts"
```

---

### 任务 6：开放请求级模型选择和模型列表 API

**文件：**

- 创建：`src/databricks_zh_expert/api/model_schemas.py`
- 创建：`src/databricks_zh_expert/api/models.py`
- 创建：`tests/integration/test_models_api.py`
- 修改：`src/databricks_zh_expert/chat/schemas.py`
- 修改：`src/databricks_zh_expert/api/chat.py`
- 修改：`src/databricks_zh_expert/api/dependencies.py`
- 修改：`src/databricks_zh_expert/main.py`
- 修改：`tests/integration/test_messages_api.py`
- 修改：`tests/conftest.py`

**接口：**

- 产出：`GET /api/models -> ModelListResponse`。
- 产出：`SendMessageRequest.model: ModelAlias | None`。
- 产出：消息成功响应新增 `model_invocation_id`、`requested_model`、`used_model`、`fallback_used`、`attempt_count`。
- 产出：FastAPI 依赖 `get_model_registry()`、`get_model_transport()`、`get_model_gateway()`。

- [ ] **步骤 1：先写模型列表 API 失败测试**

创建 `tests/integration/test_models_api.py`：

```python
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_models_returns_aliases_without_internal_ids_or_keys(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "deepseek-v4-flash"
    assert payload["fallback_models"] == ["deepseek-v4-flash", "gpt5.4mini"]
    assert [model["alias"] for model in payload["models"]] == [
        "gpt5.5",
        "gpt5.4mini",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert all("litellm_model" not in model for model in payload["models"])
    assert "api_key" not in response.text.casefold()
```

使用 `settings_factory(openai_api_key="key", deepseek_api_key=None)` 的独立 app 再断言两个 OpenAI 模型 `configured=true`，两个 DeepSeek 模型 `configured=false`。

- [ ] **步骤 2：先改写消息 API 的请求选模和 fallback 测试**

`tests/integration/test_messages_api.py` 把依赖覆盖从 `get_model_client` 改为 `get_model_gateway`。Fake Gateway 对显式 `gpt5.5` 依次 yield 一次可重试失败和一次 `gpt5.4mini` 成功，固定断言：

```python
response = await client.post(
    f"/api/chat/sessions/{session_id}/messages",
    json={"content": "设计一个销售工作流", "model": "gpt5.5"},
)

assert response.status_code == 201
payload = response.json()
assert payload["requested_model"] == "gpt5.5"
assert payload["used_model"] == "gpt5.4mini"
assert payload["fallback_used"] is True
assert payload["attempt_count"] == 2
assert payload["model_invocation_id"] == str(fake_gateway.invocation_id)
```

查询数据库并断言同一 `invocation_id` 有两条记录，`model_call_id` 等于第二条成功记录。另增加：省略 `model` 时 Fake Gateway 收到 `None`；`model="unknown"` 返回 422 和 `validation_error`，且 Fake Gateway 未被调用。

- [ ] **步骤 3：运行 API 测试并确认失败**

```powershell
uv run --locked pytest tests/integration/test_models_api.py tests/integration/test_messages_api.py -v
```

预期：模型列表路由、新 Schema 和新依赖尚不存在，测试失败。

- [ ] **步骤 4：定义模型列表 Schema 和路由**

`src/databricks_zh_expert/api/model_schemas.py`：

```python
from pydantic import BaseModel

from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider


class ModelInfoResponse(BaseModel):
    alias: ModelAlias
    display_name: str
    provider: ModelProvider
    configured: bool


class ModelListResponse(BaseModel):
    default_model: ModelAlias
    fallback_models: list[ModelAlias]
    models: list[ModelInfoResponse]
```

`src/databricks_zh_expert/api/models.py` 创建 `APIRouter(prefix="/api/models", tags=["模型"])`，GET 根路径从注入的 `ModelRegistry` 构造上述响应。不得返回 `litellm_model` 或任何 SecretStr。

- [ ] **步骤 5：扩展聊天请求与响应 Schema**

`src/databricks_zh_expert/chat/schemas.py` 修改为：

```python
class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    model: ModelAlias | None = None


class SendMessageResponse(BaseModel):
    session_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    model_invocation_id: UUID
    model_call_id: UUID
    requested_model: ModelAlias
    used_model: ModelAlias
    fallback_used: bool
    attempt_count: int
```

`api/chat.py` 调用 `await service.send_message(session_id, payload.content, payload.model)`，并逐字段映射 `SendMessageResult`；`model_call_id` 始终取最终成功尝试。

- [ ] **步骤 6：重写依赖装配**

`api/dependencies.py` 删除 `get_model_client()`，增加：

```python
def get_model_registry(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelRegistry:
    return ModelRegistry.from_settings(settings)


def get_model_transport(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelTransport:
    return LiteLLMTransport(settings)


def get_model_gateway(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
    transport: Annotated[ModelTransport, Depends(get_model_transport)],
) -> ModelGateway:
    return FallbackModelGateway(registry, transport)
```

`get_chat_service()` 注入 `ModelGateway`。`main.py` 导入并注册 `models_router`，保留 health 和 chat 路由顺序。测试通过覆盖 `get_model_gateway` 保证不访问公网。

- [ ] **步骤 7：运行 API 与完整自动测试**

```powershell
uv run --locked pytest tests/integration/test_models_api.py tests/integration/test_messages_api.py -v
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
```

预期：全部测试通过，分支覆盖率不低于 80%，Ruff 和 Pyright 为 0 errors；自动测试期间没有真实模型调用。

- [ ] **步骤 8：建议提交点**

```powershell
git add src/databricks_zh_expert/api src/databricks_zh_expert/chat/schemas.py src/databricks_zh_expert/main.py tests/conftest.py tests/integration/test_messages_api.py tests/integration/test_models_api.py
git commit -m "feat: expose request level model selection"
```

---

### 任务 7：同步启动文档并完成真实双供应商验收

**文件：**

- 修改：`README.md`
- 修改：`docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md`
- 复核：`.env.example`

**接口：**

- 产出：启动步骤只引用阶段 2 的有效配置键。
- 产出：DeepSeek Flash 与 GPT-5.4 mini 各一次真实成功调用的验收记录留在数据库和本地 Trace，验收会话随后删除。
- 产出：最终质量门禁和 Alembic drift 检查全部通过。

- [ ] **步骤 1：精简同步 README 启动配置**

README 第 4 步只补充一句，不增加新的长章节：

```markdown
`DEFAULT_MODEL` 和 `FALLBACK_MODELS` 使用 `.env.example` 中的业务别名；四个固定 LiteLLM 模型 ID 由代码模型目录统一维护。
```

保留现有环境准备、uv、数据库、迁移、检查、启动和停止步骤，不加入内部架构、fallback 状态机、测试输出示例或 Trace 格式说明。

- [ ] **步骤 2：同步总计划的阶段 2 配置草案**

在 `docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md` 删除 `DEV_MODEL`、`SUPPORTED_OPENAI_MODELS`、`SUPPORTED_DEEPSEEK_MODELS` 和 `LITELLM_TIMEOUT_SECONDS`，配置块精确替换为：

```text
PYTHON_VERSION=3.12.10
DEFAULT_MODEL=deepseek-v4-flash
FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini
DEFAULT_TEMPERATURE=0.2
MODEL_REQUEST_TIMEOUT_SECONDS=60
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

在核心能力中明确“每次消息请求可指定业务模型别名，省略时使用默认模型”。

- [ ] **步骤 3：执行锁文件、迁移和质量门禁**

```powershell
uv lock --check
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

预期：锁文件无变化，Alembic current 为 `0002_model_gateway_attempts (head)`，无 schema drift，全部测试通过且分支覆盖率不低于 80%。

- [ ] **步骤 4：启动服务并检查模型列表**

在一个 PowerShell 启动：

```powershell
uv run --locked databricks-zh-expert
```

另一个 PowerShell 执行：

```powershell
$models = Invoke-RestMethod http://127.0.0.1:8000/api/models
$models | ConvertTo-Json -Depth 5
```

确认只出现四个业务别名，OpenAI 和 DeepSeek 均为 `configured=true`，响应中没有实际 LiteLLM ID 或密钥。

- [ ] **步骤 5：执行一次 DeepSeek Flash 真实冒烟**

```powershell
$deepseekSession = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat/sessions -ContentType "application/json" -Body '{"title":"[阶段2冒烟] DeepSeek"}'
$deepseekBody = @{ content = "请只回复：DeepSeek 冒烟成功"; model = "deepseek-v4-flash" } | ConvertTo-Json
$deepseekResult = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/chat/sessions/$($deepseekSession.id)/messages" -ContentType "application/json" -Body $deepseekBody
$deepseekResult | ConvertTo-Json -Depth 5
```

确认 `requested_model` 和 `used_model` 均为 `deepseek-v4-flash`、`fallback_used=false`、`attempt_count=1`。

- [ ] **步骤 6：执行一次 GPT-5.4 mini 真实冒烟**

```powershell
$openaiSession = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat/sessions -ContentType "application/json" -Body '{"title":"[阶段2冒烟] OpenAI"}'
$openaiBody = @{ content = "请只回复：OpenAI 冒烟成功"; model = "gpt5.4mini" } | ConvertTo-Json
$openaiResult = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/chat/sessions/$($openaiSession.id)/messages" -ContentType "application/json" -Body $openaiBody
$openaiResult | ConvertTo-Json -Depth 5
```

确认 `requested_model` 和 `used_model` 均为 `gpt5.4mini`、`fallback_used=false`、`attempt_count=1`。不通过制造真实供应商故障验证 fallback。

- [ ] **步骤 7：核对数据库尝试记录和 Trace 1.1 脱敏**

```powershell
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "SELECT s.title, mc.invocation_id, mc.model_alias, mc.attempt_number, mc.success, mc.retryable, mc.error_code FROM model_calls mc JOIN sessions s ON s.id = mc.session_id WHERE s.title LIKE '[阶段2冒烟]%' ORDER BY mc.created_at;"
Get-Content .local/logs/model-calls.jsonl -Tail 2
```

数据库应有两个成功尝试且 `attempt_number=1`。最后两行 JSONL 应为 `schema_version=1.1`，请求与响应完整可解析。再运行以下本地脱敏检查：

```powershell
@'
from pathlib import Path
from databricks_zh_expert.core.config import get_settings

settings = get_settings()
content = Path(settings.model_trace_path).read_text(encoding="utf-8")
for secret in (settings.openai_api_key, settings.deepseek_api_key):
    if secret is not None:
        assert secret.get_secret_value() not in content
print("Trace 密钥脱敏检查通过。")
'@ | uv run --locked python -
```

- [ ] **步骤 8：删除真实冒烟会话并复跑最终门禁**

```powershell
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "DELETE FROM sessions WHERE title LIKE '[阶段2冒烟]%';"
uv run --locked alembic check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

删除会话会通过外键级联删除对应消息和 `model_calls`；本地 Trace 保留两行脱敏记录供开发调试。

- [ ] **步骤 9：建议提交点**

```powershell
git add README.md .env.example docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md
git commit -m "docs: complete stage two model gateway setup"
```

---

## 阶段 2 验收清单

- [ ] API 只接受四个固定业务模型别名，非法值在进入 ChatService 前返回 422。
- [ ] 同一会话的不同消息请求可以选择不同模型，省略模型时使用 `DEFAULT_MODEL`。
- [ ] ChatService 只依赖 `ModelGateway`，不识别供应商 API 或 LiteLLM ID。
- [ ] temperature 仅在 LiteLLM 声明当前模型支持时发送，请求不能覆盖全局值。
- [ ] LiteLLM 隐式重试关闭，每个候选在同一 invocation 中最多调用一次。
- [ ] 只有超时、429、连接失败和 5xx 触发 fallback；不可重试错误立即终止。
- [ ] 每个尝试都拥有相同 invocation 下唯一的 `attempt_number`，并分别写入数据库和 Trace。
- [ ] 成功 API 返回最终 `model_call_id`、`requested_model`、`used_model`、`fallback_used` 和 `attempt_count`。
- [ ] `GET /api/models` 不返回 API Key 或内部 LiteLLM ID。
- [ ] 历史 `model_calls` 已无损回填，未知历史模型标识被保留。
- [ ] Trace 1.1 保留实际请求和脱敏响应，失败记录不包含供应商原始错误文本。
- [ ] DeepSeek Flash 与 GPT-5.4 mini 各完成一次真实冒烟；fallback 只由 Fake transport 自动测试。
- [ ] Ruff、Pyright、pytest、覆盖率、Alembic current 和 Alembic check 全部通过。

## 参考资料

1. [阶段 2 模型网关设计](../specs/2026-07-11-stage-2-model-gateway-design.md)
2. [OpenAI GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5)
3. [OpenAI GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
4. [DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models)
5. [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)
6. [LiteLLM 文档](https://docs.litellm.ai/)
