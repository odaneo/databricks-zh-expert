import pytest
from httpx import ASGITransport, AsyncClient

from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.main import create_app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ready_health_reports_test_database_status(
    settings_factory,
    test_database_url: str,
    ready_expert_template_index: ExpertTemplateRepository,
) -> None:
    del ready_expert_template_index
    app = create_app(settings=settings_factory(database_url=test_database_url))

    async with app.router.lifespan_context(app):
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ready_health_rejects_unsynchronized_expert_index(
    settings_factory,
    test_database_url: str,
    empty_expert_template_index: None,
) -> None:
    del empty_expert_template_index
    app = create_app(settings=settings_factory(database_url=test_database_url))

    async with app.router.lifespan_context(app):
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
