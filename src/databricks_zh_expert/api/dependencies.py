from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.llm.client import ModelTransport
from databricks_zh_expert.llm.gateway import (
    FallbackModelGateway,
    ModelGateway,
)
from databricks_zh_expert.llm.litellm_client import LiteLLMTransport
from databricks_zh_expert.llm.model_registry import ModelRegistry
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


def get_model_registry(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelRegistry:
    return ModelRegistry.from_settings(settings)


def get_model_transport(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ModelTransport:
    return LiteLLMTransport(settings)


def get_model_gateway(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
    transport: Annotated[ModelTransport, Depends(get_model_transport)],
) -> ModelGateway:
    return FallbackModelGateway(registry, transport)


def get_model_trace_sink(request: Request) -> ModelTraceSink:
    return cast(ModelTraceSink, request.app.state.model_trace_sink)


def get_chat_service(
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    model_gateway: Annotated[ModelGateway, Depends(get_model_gateway)],
    trace_sink: Annotated[ModelTraceSink, Depends(get_model_trace_sink)],
) -> ChatService:
    return ChatService(repository, model_gateway, trace_sink)
