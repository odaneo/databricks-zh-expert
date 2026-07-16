from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.db.models import ChatSession, Message

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_and_get_session(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "每日销售分析"},
    )

    assert create_response.status_code == 201
    session_id = create_response.json()["id"]
    assert create_response.json()["expert_profile"] == "generic"

    get_response = await client.get(f"/api/chat/sessions/{session_id}")

    assert get_response.status_code == 200
    assert get_response.json()["title"] == "每日销售分析"
    assert get_response.json()["expert_profile"] == "generic"
    assert get_response.json()["messages"] == []
    stored_profile = await test_db_session.scalar(
        select(ChatSession.expert_profile).where(ChatSession.id == UUID(session_id))
    )
    assert stored_profile == "generic"


async def test_create_session_persists_profile_in_list_and_detail(
    client: AsyncClient,
) -> None:
    create_response = await client.post(
        "/api/chat/sessions",
        json={
            "title": "零售销售设计",
            "expert_profile": "retail_sales_demo",
        },
    )

    assert create_response.status_code == 201
    assert create_response.json()["expert_profile"] == "retail_sales_demo"
    session_id = create_response.json()["id"]

    list_response = await client.get("/api/chat/sessions")
    detail_response = await client.get(f"/api/chat/sessions/{session_id}")

    assert list_response.status_code == 200
    assert list_response.json()[0]["expert_profile"] == "retail_sales_demo"
    assert detail_response.status_code == 200
    assert detail_response.json()["expert_profile"] == "retail_sales_demo"


async def test_create_session_rejects_unknown_expert_profile(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/chat/sessions",
        json={"title": "错误会话", "expert_profile": "unknown"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "expert_profile_not_found",
        "message": "专家配置不存在。",
        "details": None,
    }


async def test_historical_session_without_explicit_profile_returns_generic(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    session_id = await test_db_session.scalar(
        insert(ChatSession).values(title="历史会话").returning(ChatSession.id)
    )
    await test_db_session.commit()
    assert session_id is not None

    response = await client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["expert_profile"] == "generic"


async def test_session_profile_has_no_update_route(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "不可变 Profile"},
    )
    session_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/chat/sessions/{session_id}",
        json={"expert_profile": "retail_sales_demo"},
    )

    assert response.status_code == 405


async def test_create_session_uses_default_title_and_rejects_empty_title(
    client: AsyncClient,
) -> None:
    default_response = await client.post("/api/chat/sessions", json={})
    invalid_response = await client.post(
        "/api/chat/sessions",
        json={"title": ""},
    )

    assert default_response.status_code == 201
    assert default_response.json()["title"] == "新会话"
    assert invalid_response.status_code == 422
    assert invalid_response.json()["code"] == "validation_error"


async def test_get_missing_session_returns_domain_error(client: AsyncClient) -> None:
    response = await client.get("/api/chat/sessions/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {
        "code": "session_not_found",
        "message": "会话不存在。",
        "details": None,
    }


async def test_list_sessions_orders_by_update_time_and_applies_pagination(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    session_ids: list[UUID] = []
    for title in ("最早", "中间", "最新"):
        response = await client.post("/api/chat/sessions", json={"title": title})
        assert response.status_code == 201
        session_ids.append(UUID(response.json()["id"]))

    for session_id, updated_at in zip(
        session_ids,
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        ),
        strict=True,
    ):
        await test_db_session.execute(
            update(ChatSession).where(ChatSession.id == session_id).values(updated_at=updated_at)
        )
    await test_db_session.commit()

    response = await client.get(
        "/api/chat/sessions",
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert [session["title"] for session in response.json()] == ["中间"]


async def test_get_session_lists_messages_in_creation_order(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "消息排序"},
    )
    assert create_response.status_code == 201
    session_id = UUID(create_response.json()["id"])
    test_db_session.add_all(
        [
            Message(
                session_id=session_id,
                role="assistant",
                content="第二条",
                artifact_type=ArtifactType.SQL.value,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
            Message(
                session_id=session_id,
                role="user",
                content="第一条",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    await test_db_session.commit()

    response = await client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == [
        "第一条",
        "第二条",
    ]
    assert [message["artifact_type"] for message in response.json()["messages"]] == [
        None,
        "sql",
    ]
