from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.llm.client import ModelClient
from databricks_zh_expert.llm.litellm_client import LiteLLMModelClient
from databricks_zh_expert.observability.model_trace import ModelTraceSink


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


def get_model_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelClient:
    return LiteLLMModelClient(settings)


def get_model_trace_sink(request: Request) -> ModelTraceSink:
    return cast(ModelTraceSink, request.app.state.model_trace_sink)


def get_chat_service(
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    model_client: Annotated[ModelClient, Depends(get_model_client)],
    trace_sink: Annotated[ModelTraceSink, Depends(get_model_trace_sink)],
) -> ChatService:
    return ChatService(repository, model_client, trace_sink)
