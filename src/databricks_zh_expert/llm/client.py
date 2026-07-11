from dataclasses import dataclass
from typing import Literal, Protocol

from databricks_zh_expert.llm.model_registry import ModelDefinition

ModelRole = Literal["system", "user", "assistant"]
type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: ModelRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    api_response: JsonObject


@dataclass(frozen=True, slots=True)
class ModelTransportResult:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    api_response: JsonObject


class ModelClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, messages: list[ModelMessage]) -> ModelResult: ...


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
