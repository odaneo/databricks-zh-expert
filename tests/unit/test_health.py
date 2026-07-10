import pytest
from httpx import ASGITransport, AsyncClient

import databricks_zh_expert.main as main_module

create_app = main_module.create_app


def test_application_runner_uses_environment_settings(settings_factory) -> None:
    captured: dict[str, object] = {}

    def fake_server(app_path: str, **kwargs: object) -> None:
        captured["app_path"] = app_path
        captured.update(kwargs)

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
    }


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


@pytest.mark.asyncio
async def test_health_returns_injected_application_status_without_database_dependency(
    settings_factory,
) -> None:
    app = create_app(settings=settings_factory())
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
