from typing import Annotated

from fastapi import APIRouter, Depends

from databricks_zh_expert.api.dependencies import get_prompt_registry
from databricks_zh_expert.api.prompt_schemas import PromptListResponse, PromptSummary
from databricks_zh_expert.prompts.registry import PromptRegistry

router = APIRouter(prefix="/api/prompts", tags=["Prompt"])


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    registry: Annotated[PromptRegistry, Depends(get_prompt_registry)],
) -> PromptListResponse:
    return PromptListResponse(
        default_prompt=registry.default_prompt,
        prompts=[PromptSummary.from_spec(spec) for spec in registry.prompts],
    )
