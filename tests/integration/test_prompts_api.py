import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_prompts_exposes_catalog_without_template_text(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/prompts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_prompt"] == "databricks_qa"
    assert [prompt["name"] for prompt in payload["prompts"]] == [
        "databricks_qa",
        "sql_generation",
        "pyspark_generation",
        "workflow_design",
        "document_summary",
        "knowledge_qa",
        "proposal_generation",
        "self_check",
    ]
    assert all(
        set(prompt)
        == {
            "name",
            "display_name",
            "description",
            "artifact_type",
            "version",
            "available",
            "unavailable_reason",
        }
        for prompt in payload["prompts"]
    )
    knowledge = next(prompt for prompt in payload["prompts"] if prompt["name"] == "knowledge_qa")
    assert knowledge["available"] is True
    assert knowledge["version"] == "1.2.0"
    assert knowledge["unavailable_reason"] is None
    assert "base_system.jinja2" not in response.text
    assert "template_name" not in response.text
    assert "system_message" not in response.text
