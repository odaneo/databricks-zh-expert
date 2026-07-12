from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI

from databricks_zh_expert import __version__
from databricks_zh_expert.api.chat import router as chat_router
from databricks_zh_expert.api.health import router as health_router
from databricks_zh_expert.api.models import router as models_router
from databricks_zh_expert.api.prompts import router as prompts_router
from databricks_zh_expert.artifacts.markdown import MarkdownArtifactParser
from databricks_zh_expert.core.config import Settings, get_settings
from databricks_zh_expert.core.errors import register_exception_handlers
from databricks_zh_expert.core.logging import configure_logging
from databricks_zh_expert.core.runtime import (
    configure_event_loop_policy,
    selector_event_loop_factory,
)
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.observability.model_trace import (
    JsonlModelTraceSink,
    ModelTraceSink,
    NullModelTraceSink,
)
from databricks_zh_expert.prompts.registry import PromptRegistry

ServerRunner = Callable[..., Any]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        database: Database = app.state.database
        await database.dispose()


def run(
    settings: Settings | None = None,
    server: ServerRunner = uvicorn.run,
) -> None:
    configure_event_loop_policy()
    settings = settings or get_settings()
    server(
        "databricks_zh_expert.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        loop=selector_event_loop_factory,
    )


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    model_trace_sink: ModelTraceSink | None = None,
    prompt_registry: PromptRegistry | None = None,
    artifact_parser: MarkdownArtifactParser | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    prompt_registry = prompt_registry or PromptRegistry.create_default()
    artifact_parser = artifact_parser or MarkdownArtifactParser()
    prompt_registry.validate_all()
    database = database or Database(settings.database_url)
    model_trace_sink = model_trace_sink or (
        JsonlModelTraceSink(settings.model_trace_path)
        if settings.model_trace_enabled
        else NullModelTraceSink()
    )
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Databricks 顾问型 Agent Demo API",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.model_trace_sink = model_trace_sink
    app.state.prompt_registry = prompt_registry
    app.state.artifact_parser = artifact_parser
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(models_router)
    app.include_router(prompts_router)
    return app
