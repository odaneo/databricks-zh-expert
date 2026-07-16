import asyncio
import os
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import pytest
import pytest_asyncio
from alembic.config import Config
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from databricks_zh_expert.api.dependencies import get_db_session
from databricks_zh_expert.core.config import Settings, get_settings
from databricks_zh_expert.db.models import (
    ChatSession,
    ExpertTemplateChunkRecord,
    ExpertTemplateRecord,
    ExpertTemplateSyncRun,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.sync import ExpertTemplateSyncService
from databricks_zh_expert.main import create_app
from databricks_zh_expert.rag.embeddings import EmbeddingResult


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
        model_trace_enabled: bool = False,
        model_trace_path: Path = Path(".local/logs/model-calls.jsonl"),
        default_model: str = "deepseek-v4-flash",
        fallback_models: str | tuple[str, ...] = "deepseek-v4-flash,gpt5.4mini",
        default_temperature: float = 0.2,
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


class _DeterministicExpertEmbeddingClient:
    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[EmbeddingResult, ...]:
        return tuple(
            EmbeddingResult(index=index, embedding=(0.01,) * 1536) for index, _ in enumerate(texts)
        )


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
def migrated_test_database_url(test_database_url: str) -> str:
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()
    return test_database_url


@pytest_asyncio.fixture
async def test_engine(migrated_test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        await session.execute(delete(ChatSession))
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(delete(ChatSession))
            await session.commit()


@pytest.fixture(scope="session")
def expert_template_registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


async def _clear_expert_template_index(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await session.execute(update(ExpertTemplateRecord).values(extends_id=None))
        await session.execute(delete(ExpertTemplateChunkRecord))
        await session.execute(delete(ExpertTemplateRecord))
        await session.execute(delete(ExpertTemplateSyncRun))


@pytest_asyncio.fixture
async def empty_expert_template_index(
    test_engine: AsyncEngine,
) -> AsyncIterator[None]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    await _clear_expert_template_index(session_factory)
    try:
        yield
    finally:
        await _clear_expert_template_index(session_factory)


@pytest_asyncio.fixture
async def ready_expert_template_index(
    test_engine: AsyncEngine,
    expert_template_registry: ExpertTemplateRegistry,
) -> AsyncIterator[ExpertTemplateRepository]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    await _clear_expert_template_index(session_factory)
    repository = ExpertTemplateRepository(
        session_factory,
        registry=expert_template_registry,
    )
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=_DeterministicExpertEmbeddingClient(),
    )
    await service.sync(expert_template_registry)
    try:
        yield repository
    finally:
        await _clear_expert_template_index(session_factory)


@pytest_asyncio.fixture
async def test_app(
    settings_factory: SettingsFactory,
    test_database_url: str,
    test_db_session: AsyncSession,
) -> AsyncIterator[FastAPI]:
    app = create_app(settings=settings_factory(database_url=test_database_url))

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        async with app.router.lifespan_context(app):
            yield app
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as async_client:
        yield async_client


@pytest_asyncio.fixture
async def ready_client(
    test_app: FastAPI,
    ready_expert_template_index: ExpertTemplateRepository,
) -> AsyncIterator[AsyncClient]:
    del ready_expert_template_index
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as async_client:
        yield async_client


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
        model_trace_enabled: bool = False,
        model_trace_path: Path = Path(".local/logs/model-calls.jsonl"),
        default_model: str = "deepseek-v4-flash",
        fallback_models: str | tuple[str, ...] = "deepseek-v4-flash,gpt5.4mini",
        default_temperature: float = 0.2,
        database_url: str = ("postgresql+psycopg://user:password@localhost:5432/test_database"),
        postgres_schema: str = "test_schema",
        openai_api_key: str | SecretStr | None = None,
        deepseek_api_key: str | SecretStr | None = None,
    ) -> Settings:
        settings_values: dict[str, Any] = {
            "app_name": app_name,
            "app_env": app_env,
            "app_host": app_host,
            "app_port": app_port,
            "log_level": log_level,
            "model_request_timeout_seconds": model_request_timeout_seconds,
            "model_trace_enabled": model_trace_enabled,
            "model_trace_path": model_trace_path,
            "default_model": default_model,
            "fallback_models": fallback_models,
            "default_temperature": default_temperature,
            "database_url": database_url,
            "postgres_schema": postgres_schema,
            "openai_api_key": (
                SecretStr(openai_api_key) if isinstance(openai_api_key, str) else openai_api_key
            ),
            "deepseek_api_key": (
                SecretStr(deepseek_api_key)
                if isinstance(deepseek_api_key, str)
                else deepseek_api_key
            ),
        }
        return Settings(**settings_values)

    return create_settings
