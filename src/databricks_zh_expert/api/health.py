from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert import __version__
from databricks_zh_expert.api.dependencies import (
    get_app_settings,
    get_db_session,
    get_expert_template_registry,
    get_expert_template_repository,
)
from databricks_zh_expert.core.config import Settings
from databricks_zh_expert.core.errors import (
    AppError,
    ExpertTemplateIndexNotReadyAppError,
)
from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository

router = APIRouter(tags=["系统"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    database: Literal["ok"]
    expert_templates: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
        version=__version__,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    expert_repository: Annotated[
        ExpertTemplateRepository,
        Depends(get_expert_template_repository),
    ],
    expert_registry: Annotated[
        ExpertTemplateRegistry,
        Depends(get_expert_template_registry),
    ],
) -> ReadinessResponse:
    try:
        await session.execute(text("SELECT 1"))
        expert_status = await expert_repository.get_index_status(expert_registry.source_hash)
    except SQLAlchemyError as error:
        raise AppError(
            code="database_unavailable",
            message="数据库暂时不可用。",
            status_code=503,
        ) from error
    if not expert_status.queryable:
        raise ExpertTemplateIndexNotReadyAppError()
    return ReadinessResponse(
        status="ready",
        database="ok",
        expert_templates="ok",
    )
