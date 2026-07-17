from typing import Annotated

import pytest
from fastapi import Query
from httpx import ASGITransport, AsyncClient

import databricks_zh_expert.core.errors as errors_module
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.main import create_app


@pytest.mark.parametrize(
    ("class_name", "code", "message", "status_code"),
    (
        (
            "ExpertProfileNotFoundAppError",
            "expert_profile_not_found",
            "专家配置不存在。",
            422,
        ),
        (
            "ExpertTemplateIndexNotReadyAppError",
            "expert_template_index_not_ready",
            "专家模板索引尚未就绪。",
            503,
        ),
        (
            "WorkspaceNotFoundAppError",
            "workspace_not_found",
            "项目工作区不存在。",
            422,
        ),
    ),
)
def test_expert_template_errors_have_stable_contract(
    class_name: str,
    code: str,
    message: str,
    status_code: int,
) -> None:
    error_type = getattr(errors_module, class_name, None)

    assert callable(error_type)
    error = error_type()
    assert isinstance(error, AppError)
    assert error.code == code
    assert error.message == message
    assert error.status_code == status_code


@pytest.mark.asyncio
async def test_app_error_uses_the_standard_error_response(settings_factory) -> None:
    app = create_app(settings=settings_factory())

    @app.get("/test-error")
    async def raise_test_error() -> None:
        raise AppError(
            code="test_error",
            message="测试错误。",
            status_code=409,
            details={"field": "value"},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/test-error")

    assert response.status_code == 409
    assert response.json() == {
        "code": "test_error",
        "message": "测试错误。",
        "details": {"field": "value"},
    }


@pytest.mark.asyncio
async def test_validation_error_uses_the_standard_error_response(settings_factory) -> None:
    app = create_app(settings=settings_factory())

    @app.get("/test-validation")
    async def validate_query(value: Annotated[str, Query(min_length=2)]) -> dict[str, str]:
        return {"value": value}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/test-validation", params={"value": ""})

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "validation_error"
    assert payload["message"] == "请求参数不合法。"
    assert isinstance(payload["details"], list)
