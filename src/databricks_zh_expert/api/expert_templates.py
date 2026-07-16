from typing import Annotated

from fastapi import APIRouter, Depends, Query

from databricks_zh_expert.api.dependencies import (
    get_expert_template_registry,
    get_expert_template_repository,
)
from databricks_zh_expert.api.expert_template_schemas import (
    ExpertProfileListResponse,
    ExpertProfileResponse,
    ExpertTemplateIndexStatusResponse,
    ExpertTemplateMetadataResponse,
)
from databricks_zh_expert.core.errors import ExpertProfileNotFoundAppError
from databricks_zh_expert.expert_templates.registry import (
    ExpertTemplateRegistry,
    ExpertTemplateRegistryError,
)
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
    TemplateListQuery,
)

router = APIRouter(tags=["专家模板"])


@router.get("/api/expert-profiles", response_model=ExpertProfileListResponse)
async def list_expert_profiles(
    registry: Annotated[
        ExpertTemplateRegistry,
        Depends(get_expert_template_registry),
    ],
) -> ExpertProfileListResponse:
    return ExpertProfileListResponse(
        default_profile=registry.default_profile_id,
        profiles=[ExpertProfileResponse.model_validate(profile) for profile in registry.profiles],
    )


@router.get(
    "/api/expert-templates",
    response_model=list[ExpertTemplateMetadataResponse],
)
async def list_expert_templates(
    repository: Annotated[
        ExpertTemplateRepository,
        Depends(get_expert_template_repository),
    ],
    registry: Annotated[
        ExpertTemplateRegistry,
        Depends(get_expert_template_registry),
    ],
    profile: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    kind: ExpertTemplateKind | None = None,
    category: ExpertTemplateCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExpertTemplateMetadataResponse]:
    if profile is not None:
        try:
            registry.get_profile(profile)
        except ExpertTemplateRegistryError:
            raise ExpertProfileNotFoundAppError() from None
    records = await repository.list_active_templates(
        TemplateListQuery(
            profile_id=profile,
            kind=kind,
            category=category,
            limit=limit,
            offset=offset,
        )
    )
    return [ExpertTemplateMetadataResponse.model_validate(record) for record in records]


@router.get(
    "/api/expert-templates/index/status",
    response_model=ExpertTemplateIndexStatusResponse,
)
async def get_expert_template_index_status(
    repository: Annotated[
        ExpertTemplateRepository,
        Depends(get_expert_template_repository),
    ],
    registry: Annotated[
        ExpertTemplateRegistry,
        Depends(get_expert_template_registry),
    ],
) -> ExpertTemplateIndexStatusResponse:
    status = await repository.get_index_status(registry.source_hash)
    return ExpertTemplateIndexStatusResponse.model_validate(status)
