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
    database_url: str
    postgres_schema: str
    openai_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None

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
    # 必填字段由 BaseSettings 从环境变量或 .env 注入。
    return Settings()  # pyright: ignore[reportCallIssue]
