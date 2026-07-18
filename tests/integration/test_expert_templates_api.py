import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.db.models import ExpertTemplateRecord
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_expert_profiles_returns_registered_profiles_and_default(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/expert-profiles")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_profile"] == "generic"
    assert [profile["id"] for profile in payload["profiles"]] == [
        "generic",
        "retail_sales_demo",
    ]
    assert "is_mock" not in payload["profiles"][0]
    assert payload["profiles"][1]["cloud"] == "aws"
    assert "is_mock" not in payload["profiles"][1]


async def test_list_expert_templates_filters_and_paginates_active_metadata(
    ready_client: AsyncClient,
) -> None:
    response = await ready_client.get(
        "/api/expert-templates",
        params={
            "profile": "generic",
            "kind": "blueprint",
            "category": "ingestion",
            "limit": 2,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["template_id"] for item in payload] == [
        "ingestion.dms_s3_cdc",
        "ingestion.kinesis_streaming",
    ]
    assert set(payload[0]) == {
        "template_id",
        "version",
        "name",
        "summary",
        "kind",
        "category",
        "layer",
        "profile_id",
        "cloud",
        "prompt_names",
        "tags",
    }
    assert {
        "content",
        "embedding",
        "source_path",
        "vector_similarity",
        "lexical_score",
    }.isdisjoint(payload[0])

    next_page = await ready_client.get(
        "/api/expert-templates",
        params={
            "profile": "generic",
            "kind": "blueprint",
            "category": "ingestion",
            "limit": 1,
            "offset": 1,
        },
    )
    assert next_page.status_code == 200
    assert [item["template_id"] for item in next_page.json()] == ["ingestion.kinesis_streaming"]


async def test_list_expert_templates_excludes_inactive_versions(
    ready_client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    await test_db_session.execute(
        update(ExpertTemplateRecord)
        .where(ExpertTemplateRecord.template_id == "checklist.cost")
        .values(status="inactive")
    )
    await test_db_session.commit()

    response = await ready_client.get(
        "/api/expert-templates",
        params={"category": "cost"},
    )

    assert response.status_code == 200
    assert "checklist.cost" not in {item["template_id"] for item in response.json()}


async def test_list_expert_templates_rejects_unknown_profile(
    ready_client: AsyncClient,
) -> None:
    response = await ready_client.get(
        "/api/expert-templates",
        params={"profile": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "expert_profile_not_found"


async def test_get_expert_template_index_status_reports_current_source(
    ready_client: AsyncClient,
    expert_template_registry: ExpertTemplateRegistry,
) -> None:
    response = await ready_client.get("/api/expert-templates/index/status")

    assert response.status_code == 200
    assert response.json() == {
        "latest_run_status": "succeeded",
        "source_hash_matches": True,
        "active_template_count": len(expert_template_registry.templates),
        "chunk_count": response.json()["chunk_count"],
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "queryable": True,
    }
    assert response.json()["chunk_count"] > 0


async def test_expert_template_api_has_no_content_or_write_endpoint(
    ready_client: AsyncClient,
) -> None:
    detail_response = await ready_client.get("/api/expert-templates/ingestion.s3_auto_loader")
    write_response = await ready_client.post("/api/expert-templates", json={})

    assert detail_response.status_code == 404
    assert write_response.status_code == 405
