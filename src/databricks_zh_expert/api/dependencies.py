from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.artifacts.markdown import MarkdownArtifactParser
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.llm.client import ModelTransport
from databricks_zh_expert.llm.gateway import (
    FallbackModelGateway,
    ModelGateway,
)
from databricks_zh_expert.llm.litellm_client import LiteLLMTransport
from databricks_zh_expert.llm.model_registry import ModelRegistry
from databricks_zh_expert.observability.model_trace import ModelTraceSink
from databricks_zh_expert.prompts.registry import PromptRegistry
from databricks_zh_expert.rag.embeddings import OpenAIEmbeddingClient
from databricks_zh_expert.rag.repository import KnowledgeRepository
from databricks_zh_expert.rag.retrieval import KnowledgeRetriever


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
    settings: Annotated[Settings, Depends(get_app_settings)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
    transport: Annotated[ModelTransport, Depends(get_model_transport)],
) -> ModelGateway:
    sensitive_values = tuple(
        secret.get_secret_value()
        for secret in (settings.openai_api_key, settings.deepseek_api_key)
        if secret is not None and secret.get_secret_value()
    )
    return FallbackModelGateway(registry, transport, sensitive_values)


def get_model_trace_sink(request: Request) -> ModelTraceSink:
    return cast(ModelTraceSink, request.app.state.model_trace_sink)


def get_prompt_registry(request: Request) -> PromptRegistry:
    return cast(PromptRegistry, request.app.state.prompt_registry)


def get_artifact_parser(request: Request) -> MarkdownArtifactParser:
    return cast(MarkdownArtifactParser, request.app.state.artifact_parser)


def get_expert_template_registry(request: Request) -> ExpertTemplateRegistry:
    return cast(
        ExpertTemplateRegistry,
        request.app.state.expert_template_registry,
    )


def get_expert_template_repository(request: Request) -> ExpertTemplateRepository:
    return cast(
        ExpertTemplateRepository,
        request.app.state.expert_template_repository,
    )


def get_knowledge_repository(request: Request) -> KnowledgeRepository:
    database = cast(Database, request.app.state.database)
    return KnowledgeRepository(database.session_factory)


def get_embedding_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> OpenAIEmbeddingClient:
    return OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.model_request_timeout_seconds,
    )


def get_knowledge_retriever(
    repository: Annotated[KnowledgeRepository, Depends(get_knowledge_repository)],
    embedding_client: Annotated[OpenAIEmbeddingClient, Depends(get_embedding_client)],
) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        repository=repository,
        embedding_client=embedding_client,
    )


def get_chat_service(
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    model_gateway: Annotated[ModelGateway, Depends(get_model_gateway)],
    trace_sink: Annotated[ModelTraceSink, Depends(get_model_trace_sink)],
    prompt_registry: Annotated[PromptRegistry, Depends(get_prompt_registry)],
    artifact_parser: Annotated[MarkdownArtifactParser, Depends(get_artifact_parser)],
    knowledge_retriever: Annotated[KnowledgeRetriever, Depends(get_knowledge_retriever)],
    knowledge_repository: Annotated[
        KnowledgeRepository,
        Depends(get_knowledge_repository),
    ],
) -> ChatService:
    return ChatService(
        repository=repository,
        model_gateway=model_gateway,
        trace_sink=trace_sink,
        prompt_registry=prompt_registry,
        artifact_parser=artifact_parser,
        knowledge_retriever=knowledge_retriever,
        knowledge_status_provider=knowledge_repository,
    )
