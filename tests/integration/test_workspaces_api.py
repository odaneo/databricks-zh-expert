import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_workspaces_returns_safe_northwind_metadata(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "northwind_psql",
            "display_name": "Northwind AWS 销售分析",
            "description": (
                "基于公开 Northwind PostgreSQL Schema 设计 AWS Databricks 销售分析项目。"
            ),
            "version": "1.0.0",
            "cloud": "aws",
            "source_count": 3,
            "source_hash": response.json()[0]["source_hash"],
            "source_paths": [
                ".databricks-expert/business-rules.md",
                ".databricks-expert/requirements.md",
                ".databricks-expert/source-schema/northwind-schema.sql",
            ],
        }
    ]
    assert len(response.json()[0]["source_hash"]) == 64
    assert "CREATE TABLE" not in response.text
    assert "full_name" not in response.text
    assert "C:\\" not in response.text


async def test_get_workspace_returns_detail_without_source_content(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/northwind_psql")

    assert response.status_code == 200
    assert response.json()["id"] == "northwind_psql"
    assert "workspace_mode" not in response.json()
    assert "is_mock" not in response.json()
    assert response.json()["source_count"] == 3
    assert "content" not in response.text


async def test_get_unknown_workspace_uses_domain_error(client: AsyncClient) -> None:
    response = await client.get("/api/workspaces/unknown")

    assert response.status_code == 404
    assert response.json() == {
        "code": "workspace_not_found",
        "message": "项目工作区不存在。",
        "details": None,
    }
