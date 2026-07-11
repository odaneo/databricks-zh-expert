from __future__ import annotations

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
    supports_custom_temperature: bool


MODEL_SPECS: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        alias=ModelAlias.GPT_55,
        display_name="GPT-5.5",
        provider=ModelProvider.OPENAI,
        litellm_model="openai/gpt-5.5",
        supports_custom_temperature=False,
    ),
    ModelSpec(
        alias=ModelAlias.GPT_54_MINI,
        display_name="GPT-5.4 mini",
        provider=ModelProvider.OPENAI,
        litellm_model="openai/gpt-5.4-mini",
        supports_custom_temperature=False,
    ),
    ModelSpec(
        alias=ModelAlias.DEEPSEEK_V4_FLASH,
        display_name="DeepSeek V4 Flash",
        provider=ModelProvider.DEEPSEEK,
        litellm_model="deepseek/deepseek-v4-flash",
        supports_custom_temperature=True,
    ),
    ModelSpec(
        alias=ModelAlias.DEEPSEEK_V4_PRO,
        display_name="DeepSeek V4 Pro",
        provider=ModelProvider.DEEPSEEK,
        litellm_model="deepseek/deepseek-v4-pro",
        supports_custom_temperature=True,
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
    supports_custom_temperature: bool


class ModelRegistry:
    def __init__(
        self,
        *,
        default_model: ModelAlias,
        fallback_models: tuple[ModelAlias, ...],
        models: tuple[ModelDefinition, ...],
    ) -> None:
        self._default_model: ModelAlias = default_model
        self._fallback_models: tuple[ModelAlias, ...] = fallback_models
        self._models: tuple[ModelDefinition, ...] = models
        self._by_alias: dict[ModelAlias, ModelDefinition] = {model.alias: model for model in models}

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
    def from_settings(cls, settings: Settings) -> ModelRegistry:
        provider_configuration = {
            ModelProvider.OPENAI: bool(
                settings.openai_api_key and settings.openai_api_key.get_secret_value().strip()
            ),
            ModelProvider.DEEPSEEK: bool(
                settings.deepseek_api_key and settings.deepseek_api_key.get_secret_value().strip()
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
                    supports_custom_temperature=spec.supports_custom_temperature,
                )
                for spec in MODEL_SPECS
            ),
        )

    def get(self, alias: ModelAlias) -> ModelDefinition:
        return self._by_alias[alias]
