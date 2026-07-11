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
