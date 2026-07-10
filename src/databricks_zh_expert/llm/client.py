from dataclasses import dataclass
from typing import Literal, Protocol

ModelRole = Literal["system", "user", "assistant"]


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


class ModelClient(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, messages: list[ModelMessage]) -> ModelResult: ...
