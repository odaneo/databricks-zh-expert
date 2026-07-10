import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from databricks_zh_expert.core.config import Settings


class SettingsFactory(Protocol):
    def __call__(
        self,
        *,
        app_name: str = "测试 Agent",
        app_env: str = "test",
        app_host: str = "127.0.0.1",
        app_port: int = 8000,
        log_level: str = "INFO",
        model_request_timeout_seconds: int = 60,
        default_model: str = "deepseek/deepseek-v4-flash",
        database_url: str = ("postgresql+psycopg://user:password@localhost:5432/test_database"),
        postgres_schema: str = "test_schema",
        openai_api_key: str | SecretStr | None = None,
        deepseek_api_key: str | SecretStr | None = None,
    ) -> Settings: ...


def pytest_asyncio_loop_factories(
    config: pytest.Config,
    item: pytest.Item,
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    del config, item
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture(scope="session")
def test_database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        dotenv_path = Path(__file__).resolve().parent.parent / ".env"
        dotenv_value = dotenv_values(dotenv_path).get("TEST_DATABASE_URL")
        value = dotenv_value if isinstance(dotenv_value, str) else None

    if not value:
        pytest.skip("未配置 TEST_DATABASE_URL，跳过数据库集成测试。")

    database_name = make_url(value).database
    if not database_name or not database_name.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL 必须指向名称以 _test 结尾的数据库。")
    return value


@pytest.fixture
def settings_factory() -> SettingsFactory:
    def create_settings(
        *,
        app_name: str = "测试 Agent",
        app_env: str = "test",
        app_host: str = "127.0.0.1",
        app_port: int = 8000,
        log_level: str = "INFO",
        model_request_timeout_seconds: int = 60,
        default_model: str = "deepseek/deepseek-v4-flash",
        database_url: str = ("postgresql+psycopg://user:password@localhost:5432/test_database"),
        postgres_schema: str = "test_schema",
        openai_api_key: str | SecretStr | None = None,
        deepseek_api_key: str | SecretStr | None = None,
    ) -> Settings:
        return Settings(
            app_name=app_name,
            app_env=app_env,
            app_host=app_host,
            app_port=app_port,
            log_level=log_level,
            model_request_timeout_seconds=model_request_timeout_seconds,
            default_model=default_model,
            database_url=database_url,
            postgres_schema=postgres_schema,
            openai_api_key=(
                SecretStr(openai_api_key) if isinstance(openai_api_key, str) else openai_api_key
            ),
            deepseek_api_key=(
                SecretStr(deepseek_api_key)
                if isinstance(deepseek_api_key, str)
                else deepseek_api_key
            ),
        )

    return create_settings
