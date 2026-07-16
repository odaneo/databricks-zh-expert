from pydantic import BaseModel, ConfigDict

from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName


class ExpertProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: str
    cloud: str
    is_mock: bool


class ExpertProfileListResponse(BaseModel):
    default_profile: str
    profiles: list[ExpertProfileResponse]


class ExpertTemplateMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_id: str
    version: str
    name: str
    summary: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: str
    profile_id: str | None
    cloud: str
    prompt_names: list[PromptName]
    tags: list[str]
    is_mock: bool


class ExpertTemplateIndexStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    latest_run_status: str | None
    source_hash_matches: bool
    active_template_count: int
    chunk_count: int
    embedding_model: str | None
    embedding_dimensions: int | None
    queryable: bool
