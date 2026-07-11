from typing import Annotated

from fastapi import APIRouter, Depends

from databricks_zh_expert.api.dependencies import get_model_registry
from databricks_zh_expert.api.model_schemas import (
    ModelInfoResponse,
    ModelListResponse,
)
from databricks_zh_expert.llm.model_registry import ModelRegistry

router = APIRouter(prefix="/api/models", tags=["模型"])


@router.get("", response_model=ModelListResponse)
async def list_models(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> ModelListResponse:
    return ModelListResponse(
        default_model=registry.default_model,
        fallback_models=list(registry.fallback_models),
        models=[
            ModelInfoResponse(
                alias=model.alias,
                display_name=model.display_name,
                provider=model.provider,
                configured=model.configured,
            )
            for model in registry.models
        ],
    )
