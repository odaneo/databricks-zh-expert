from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from databricks_zh_expert import __version__
from databricks_zh_expert.api.dependencies import get_app_settings
from databricks_zh_expert.core.config import Settings

router = APIRouter(tags=["系统"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
        version=__version__,
    )
