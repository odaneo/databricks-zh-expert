from pydantic import BaseModel

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.prompts.registry import PromptName, PromptSpec


class PromptSummary(BaseModel):
    name: PromptName
    display_name: str
    description: str
    artifact_type: ArtifactType
    version: str
    available: bool
    unavailable_reason: str | None

    @classmethod
    def from_spec(cls, spec: PromptSpec) -> "PromptSummary":
        return cls(
            name=spec.name,
            display_name=spec.display_name,
            description=spec.description,
            artifact_type=spec.artifact_type,
            version=spec.version,
            available=spec.available,
            unavailable_reason=spec.unavailable_reason,
        )


class PromptListResponse(BaseModel):
    default_prompt: PromptName
    prompts: list[PromptSummary]
