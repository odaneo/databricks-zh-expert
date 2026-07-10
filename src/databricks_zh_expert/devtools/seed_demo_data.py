import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TextIO
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.engine import make_url

from databricks_zh_expert.core.config import Settings, get_settings
from databricks_zh_expert.core.runtime import selector_event_loop_factory
from databricks_zh_expert.db.models import ChatSession, Message
from databricks_zh_expert.db.session import Database

DEMO_TITLE_PREFIX = "[演示数据]"
DEMO_TITLES = (
    "每日销售分析",
    "Bronze 数据摄取设计",
    "Silver 数据清洗方案",
    "Gold 指标聚合设计",
    "Unity Catalog 权限规划",
    "Databricks SQL 性能优化",
    "PySpark 订单清洗",
    "流式数据管道设计",
    "批处理作业编排",
    "成本优化检查",
    "集群规格建议",
    "Delta Lake 表设计",
    "维度建模评审",
    "CDC 增量同步",
    "数据质量监控",
    "销售预测数据准备",
    "客户画像宽表",
    "库存分析工作流",
    "日志分析平台",
    "财务报表数据集市",
    "Notebook 拆分建议",
    "Workflow 调度设计",
    "慢 SQL 诊断",
    "小文件治理",
    "表分区策略",
    "Z-Ordering 优化",
    "权限审计方案",
    "数据血缘设计",
    "灾备与恢复建议",
    "项目交付设计书",
)
ARTIFACT_TYPES = ("markdown", "sql", "pyspark", "workflow_design", None)


@dataclass(frozen=True, slots=True)
class SeedResult:
    database_name: str
    sessions: int
    messages: int


def build_demo_records(
    reference_time: datetime | None = None,
) -> tuple[list[ChatSession], list[Message]]:
    reference_time = reference_time or datetime.now(UTC)
    first_session_time = reference_time - timedelta(days=len(DEMO_TITLES))
    sessions: list[ChatSession] = []
    messages: list[Message] = []

    for session_index, title in enumerate(DEMO_TITLES):
        session_id = uuid4()
        created_at = first_session_time + timedelta(days=session_index)
        session_messages: list[Message] = []

        for pair_index in range(5):
            user_time = created_at + timedelta(minutes=pair_index * 20 + 1)
            assistant_time = user_time + timedelta(minutes=2)
            session_messages.extend(
                [
                    Message(
                        id=uuid4(),
                        session_id=session_id,
                        role="user",
                        content=f"请为“{title}”提供第 {pair_index + 1} 轮分析建议。",
                        artifact_type=None,
                        created_at=user_time,
                    ),
                    Message(
                        id=uuid4(),
                        session_id=session_id,
                        role="assistant",
                        content=(
                            f"## {title}\n\n"
                            f"这是第 {pair_index + 1} 轮演示回答，包含设计假设、实施步骤和风险点。"
                        ),
                        artifact_type=ARTIFACT_TYPES[pair_index],
                        created_at=assistant_time,
                    ),
                ]
            )

        sessions.append(
            ChatSession(
                id=session_id,
                title=f"{DEMO_TITLE_PREFIX} {title}",
                created_at=created_at,
                updated_at=session_messages[-1].created_at,
            )
        )
        messages.extend(session_messages)

    return sessions, messages


async def seed_demo_data(settings: Settings | None = None) -> SeedResult:
    settings = settings or get_settings()
    database_name = make_url(settings.database_url).database or ""
    if settings.app_env.lower() != "development":
        raise RuntimeError("演示数据只能写入 development 环境。")
    if not database_name or database_name.endswith("_test"):
        raise RuntimeError("演示数据不能写入测试数据库。")

    sessions, messages = build_demo_records()
    database = Database(settings.database_url)
    try:
        async with database.session() as session:
            await session.execute(
                delete(ChatSession).where(ChatSession.title.startswith(DEMO_TITLE_PREFIX))
            )
            session.add_all(sessions)
            session.add_all(messages)
            await session.commit()
    finally:
        await database.dispose()

    return SeedResult(
        database_name=database_name,
        sessions=len(sessions),
        messages=len(messages),
    )


def write_seed_summary(result: SeedResult, output: TextIO) -> None:
    reconfigure = getattr(output, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    print(
        f"演示数据已写入 {result.database_name}："
        f"{result.sessions} 个会话，{result.messages} 条消息。",
        file=output,
    )


def run() -> None:
    with asyncio.Runner(loop_factory=selector_event_loop_factory) as runner:
        result = runner.run(seed_demo_data())
    write_seed_summary(result, sys.stdout)


if __name__ == "__main__":
    run()
