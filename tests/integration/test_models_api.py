from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient

from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.main import create_app

type SettingsFactory = Callable[..., Settings]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_models_returns_aliases_without_internal_ids_or_keys(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "deepseek-v4-flash"
    assert payload["fallback_models"] == ["deepseek-v4-flash", "gpt5.4mini"]
    assert [model["alias"] for model in payload["models"]] == [
        "gpt5.5",
        "gpt5.4mini",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert all(
        set(model) == {"alias", "display_name", "provider", "configured"}
        for model in payload["models"]
    )
    assert "api_key" not in response.text.casefold()
    assert "openai/gpt-5.5" not in response.text


async def test_list_models_marks_configuration_by_provider(
    settings_factory: SettingsFactory,
) -> None:
    app = create_app(
        settings=settings_factory(
            openai_api_key="openai-test-key",
            deepseek_api_key=None,
        )
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/models")

    assert response.status_code == 200
    configured_by_alias = {
        model["alias"]: model["configured"] for model in response.json()["models"]
    }
    assert configured_by_alias == {
        "gpt5.5": True,
        "gpt5.4mini": True,
        "deepseek-v4-flash": False,
        "deepseek-v4-pro": False,
    }
    assert "openai-test-key" not in response.text
