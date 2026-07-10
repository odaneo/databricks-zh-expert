from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from databricks_zh_expert.core.config import Settings, get_settings

REQUIRED_SETTINGS = {
    "app_name": "Databricks 中文专家 Agent",
    "app_env": "development",
    "app_host": "127.0.0.1",
    "app_port": 8000,
    "log_level": "INFO",
    "model_request_timeout_seconds": 60,
    "model_trace_enabled": False,
    "model_trace_path": ".local/logs/model-calls.jsonl",
    "default_model": "deepseek/deepseek-v4-flash",
    "database_url": (
        "postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent"
    ),
    "postgres_schema": "databricks_agent",
}


def _clear_deployment_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_NAME",
        "APP_ENV",
        "APP_HOST",
        "APP_PORT",
        "LOG_LEVEL",
        "MODEL_REQUEST_TIMEOUT_SECONDS",
        "MODEL_TRACE_ENABLED",
        "MODEL_TRACE_PATH",
        "DEFAULT_MODEL",
        "DATABASE_URL",
        "POSTGRES_SCHEMA",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_deployment_settings_are_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_deployment_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    with pytest.raises(ValidationError) as error:
        get_settings()

    missing_fields = {item["loc"] for item in error.value.errors() if item["type"] == "missing"}
    assert {
        ("app_name",),
        ("app_env",),
        ("app_host",),
        ("app_port",),
        ("log_level",),
        ("model_request_timeout_seconds",),
        ("model_trace_enabled",),
        ("model_trace_path",),
        ("default_model",),
        ("database_url",),
        ("postgres_schema",),
    } <= missing_fields


def test_deployment_settings_can_come_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_deployment_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_NAME", "环境变量 Agent")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MODEL_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("MODEL_TRACE_ENABLED", "true")
    monkeypatch.setenv("MODEL_TRACE_PATH", ".local/custom/model-calls.jsonl")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-5.5")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost:5432/test_database",
    )
    monkeypatch.setenv("POSTGRES_SCHEMA", "test_schema")

    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()

    assert settings.app_name == "环境变量 Agent"
    assert settings.app_env == "test"
    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 9000
    assert settings.log_level == "WARNING"
    assert settings.model_request_timeout_seconds == 30
    assert settings.model_trace_enabled is True
    assert settings.model_trace_path == Path(".local/custom/model-calls.jsonl")
    assert settings.default_model == "openai/gpt-5.5"
    assert settings.database_url.endswith("/test_database")
    assert settings.postgres_schema == "test_schema"


def test_optional_model_keys_default_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    settings = Settings(
        **REQUIRED_SETTINGS,
        openai_api_key=None,
        deepseek_api_key=None,
    )

    assert settings.openai_api_key is None
    assert settings.deepseek_api_key is None


def test_secret_values_are_masked_when_settings_are_rendered() -> None:
    settings = Settings(
        **REQUIRED_SETTINGS,
        openai_api_key=SecretStr("openai-secret"),
        deepseek_api_key=SecretStr("deepseek-secret"),
    )

    rendered = str(settings.model_dump())

    assert "openai-secret" not in rendered
    assert "deepseek-secret" not in rendered
