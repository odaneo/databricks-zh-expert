from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI

from databricks_zh_expert import __version__
from databricks_zh_expert.api.health import router as health_router
from databricks_zh_expert.core.config import Settings, get_settings
from databricks_zh_expert.core.errors import register_exception_handlers
from databricks_zh_expert.core.logging import configure_logging

ServerRunner = Callable[..., Any]


def run(
    settings: Settings | None = None,
    server: ServerRunner = uvicorn.run,
) -> None:
    settings = settings or get_settings()
    server(
        "databricks_zh_expert.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Databricks 顾问型 Agent Demo API",
    )
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(health_router)
    return app
