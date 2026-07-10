from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.db.session import Database


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async with database.session() as session:
        yield session


def get_chat_repository(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatRepository:
    return ChatRepository(db)
