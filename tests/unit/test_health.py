from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient
from jinja2 import DictLoader, TemplateSyntaxError
from sqlalchemy.exc import SQLAlchemyError

import databricks_zh_expert.main as main_module
from databricks_zh_expert.api.dependencies import get_db_session
from databricks_zh_expert.artifacts.markdown import MarkdownArtifactParser
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.types import ExpertTemplateIndexStatus
from databricks_zh_expert.observability.model_trace import (
    JsonlModelTraceSink,
    NullModelTraceSink,
)
from databricks_zh_expert.prompts.registry import (
    DEFAULT_PROMPT,
    PROMPT_SPECS,
    PromptRegistry,
)
from databricks_zh_expert.prompts.renderer import JinjaPromptRenderer

create_app = main_module.create_app


class HealthySession:
    async def execute(self, statement: object) -> None:
        assert str(statement) == "SELECT 1"


class UnavailableSession:
    async def execute(self, statement: object) -> None:
        del statement
        raise SQLAlchemyError("测试数据库不可用")


class FakeExpertTemplateStatusRepository:
    def __init__(self, *, queryable: bool = True) -> None:
        self.queryable = queryable
        self.source_hashes: list[str] = []

    async def get_index_status(self, current_source_hash: str) -> ExpertTemplateIndexStatus:
        self.source_hashes.append(current_source_hash)
        return ExpertTemplateIndexStatus(
            latest_run_status="succeeded" if self.queryable else None,
            source_hash_matches=self.queryable,
            active_template_count=37 if self.queryable else 0,
            chunk_count=100 if self.queryable else 0,
            embedding_model="text-embedding-3-small" if self.queryable else None,
            embedding_dimensions=1536 if self.queryable else None,
            queryable=self.queryable,
        )


async def healthy_db_session() -> AsyncIterator[HealthySession]:
    yield HealthySession()


async def unavailable_db_session() -> AsyncIterator[UnavailableSession]:
    yield UnavailableSession()


def test_application_runner_uses_environment_settings(settings_factory, monkeypatch) -> None:
    captured: dict[str, object] = {}
    event_loop_configured = False

    def fake_configure_event_loop_policy() -> None:
        nonlocal event_loop_configured
        event_loop_configured = True

    def fake_server(app_path: str, **kwargs: object) -> None:
        captured["app_path"] = app_path
        captured.update(kwargs)

    monkeypatch.setattr(
        main_module,
        "configure_event_loop_policy",
        fake_configure_event_loop_policy,
        raising=False,
    )
    run = getattr(main_module, "run", None)
    assert run is not None

    run(
        settings=settings_factory(
            app_host="0.0.0.0",
            app_port=9000,
            log_level="WARNING",
        ),
        server=fake_server,
    )

    assert captured == {
        "app_path": "databricks_zh_expert.main:create_app",
        "factory": True,
        "host": "0.0.0.0",
        "port": 9000,
        "log_level": "warning",
        "loop": main_module.selector_event_loop_factory,
    }
    assert event_loop_configured is True


def test_main_module_exposes_factory_without_global_app() -> None:
    assert not hasattr(main_module, "app")


def test_app_factory_uses_package_version(settings_factory, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "__version__", "9.9.9", raising=False)

    app = create_app(settings=settings_factory())

    assert app.version == "9.9.9"


def test_app_factory_uses_injected_settings(settings_factory) -> None:
    settings = settings_factory(app_name="自定义测试 Agent")

    app = create_app(settings=settings)

    assert app.title == "自定义测试 Agent"


def test_app_factory_uses_null_trace_sink_when_disabled(settings_factory) -> None:
    app = create_app(settings=settings_factory(model_trace_enabled=False))

    assert isinstance(app.state.model_trace_sink, NullModelTraceSink)


def test_app_factory_uses_configured_jsonl_trace_sink_when_enabled(
    settings_factory,
    tmp_path,
) -> None:
    trace_path = tmp_path / "model-calls.jsonl"
    app = create_app(
        settings=settings_factory(
            model_trace_enabled=True,
            model_trace_path=trace_path,
        )
    )

    assert isinstance(app.state.model_trace_sink, JsonlModelTraceSink)
    assert app.state.model_trace_sink.path == trace_path


def test_app_factory_validates_and_stores_prompt_components(
    settings_factory,
    monkeypatch,
) -> None:
    registry = PromptRegistry.create_default()
    artifact_parser = MarkdownArtifactParser()
    validation_calls = 0

    def validate_all() -> None:
        nonlocal validation_calls
        validation_calls += 1

    monkeypatch.setattr(registry, "validate_all", validate_all)

    app = create_app(
        settings=settings_factory(),
        prompt_registry=registry,
        artifact_parser=artifact_parser,
    )

    assert validation_calls == 1
    assert app.state.prompt_registry is registry
    assert app.state.artifact_parser is artifact_parser


def test_app_factory_stores_injected_expert_template_registry(
    settings_factory,
) -> None:
    registry = ExpertTemplateRegistry.create_default()

    app = create_app(
        settings=settings_factory(),
        expert_template_registry=registry,
    )

    assert app.state.expert_template_registry is registry


def test_app_factory_rejects_invalid_prompt_template_immediately(
    settings_factory,
) -> None:
    broken_spec = replace(PROMPT_SPECS[0], template_name="broken.jinja2")
    registry = PromptRegistry(
        renderer=JinjaPromptRenderer(
            loader=DictLoader({"broken.jinja2": "{% if %}"}),
        ),
        prompts=(broken_spec,),
        default_prompt=DEFAULT_PROMPT,
    )

    with pytest.raises(TemplateSyntaxError):
        create_app(
            settings=settings_factory(),
            prompt_registry=registry,
        )


@pytest.mark.asyncio
async def test_app_lifespan_disposes_database(settings_factory, monkeypatch) -> None:
    settings = settings_factory()
    database = Database(settings.database_url)
    disposed = False

    async def fake_dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(database, "dispose", fake_dispose)
    app = create_app(settings=settings, database=database)

    async with app.router.lifespan_context(app):
        pass

    assert disposed is True


@pytest.mark.asyncio
async def test_health_returns_injected_application_status_without_database_dependency(
    settings_factory,
) -> None:
    app = create_app(settings=settings_factory())
    repository = FakeExpertTemplateStatusRepository()
    app.state.expert_template_repository = repository
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "测试 Agent",
        "environment": "test",
        "version": "0.1.0",
    }
    assert repository.source_hashes == []


@pytest.mark.asyncio
async def test_live_health_uses_the_same_application_status(settings_factory) -> None:
    app = create_app(settings=settings_factory())
    repository = FakeExpertTemplateStatusRepository()
    app.state.expert_template_repository = repository
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "测试 Agent",
        "environment": "test",
        "version": "0.1.0",
    }
    assert repository.source_hashes == []


@pytest.mark.asyncio
async def test_ready_health_executes_the_database_probe(settings_factory) -> None:
    app = create_app(settings=settings_factory())
    repository = FakeExpertTemplateStatusRepository()
    app.state.expert_template_repository = repository
    app.dependency_overrides[get_db_session] = healthy_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "expert_templates": "ok",
    }
    assert repository.source_hashes == [app.state.expert_template_registry.source_hash]


@pytest.mark.asyncio
async def test_ready_health_maps_unready_expert_index_to_service_unavailable(
    settings_factory,
) -> None:
    app = create_app(settings=settings_factory())
    repository = FakeExpertTemplateStatusRepository(queryable=False)
    app.state.expert_template_repository = repository
    app.dependency_overrides[get_db_session] = healthy_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "expert_template_index_not_ready",
        "message": "专家模板索引尚未就绪。",
        "details": None,
    }


@pytest.mark.asyncio
async def test_ready_health_maps_database_errors_to_service_unavailable(
    settings_factory,
) -> None:
    app = create_app(settings=settings_factory())
    repository = FakeExpertTemplateStatusRepository()
    app.state.expert_template_repository = repository
    app.dependency_overrides[get_db_session] = unavailable_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "database_unavailable",
        "message": "数据库暂时不可用。",
        "details": None,
    }
    assert repository.source_hashes == []
