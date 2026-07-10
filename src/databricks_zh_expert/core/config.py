from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    model_request_timeout_seconds: int
    default_model: str
    database_url: str
    postgres_schema: str
    openai_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    # 必填字段由 BaseSettings 从环境变量或 .env 注入。
    return Settings()  # pyright: ignore[reportCallIssue]
