from collections import Counter
from datetime import UTC, datetime
from io import BytesIO, TextIOWrapper

import pytest

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.devtools.seed_demo_data import (
    SeedResult,
    build_demo_records,
    seed_demo_data,
    write_seed_summary,
)


def test_build_demo_records_creates_expected_sessions_and_messages() -> None:
    sessions, messages = build_demo_records(datetime(2026, 1, 31, tzinfo=UTC))

    assert len(sessions) == 30
    assert len(messages) == 300
    assert all(session.title.startswith("[演示数据]") for session in sessions)

    messages_per_session = Counter(message.session_id for message in messages)
    assert set(messages_per_session.values()) == {10}
    assert {message.role for message in messages} == {"user", "assistant"}
    assistant_artifact_types = {
        message.artifact_type for message in messages if message.role == "assistant"
    }
    assert assistant_artifact_types <= {artifact.value for artifact in ArtifactType} | {None}
    assert "markdown" not in assistant_artifact_types


def test_write_seed_summary_supports_a_cp932_console() -> None:
    buffer = BytesIO()
    output = TextIOWrapper(buffer, encoding="cp932")

    write_seed_summary(
        SeedResult(database_name="databricks_agent", sessions=30, messages=300),
        output,
    )
    output.flush()

    summary = buffer.getvalue().decode("utf-8")
    assert "30 个会话" in summary
    assert "300 条消息" in summary


@pytest.mark.asyncio
async def test_seed_demo_data_rejects_test_database(settings_factory) -> None:
    settings = settings_factory(
        app_env="development",
        database_url=("postgresql+psycopg://user:password@localhost:5432/databricks_agent_test"),
    )

    with pytest.raises(RuntimeError, match="不能写入测试数据库"):
        await seed_demo_data(settings)
