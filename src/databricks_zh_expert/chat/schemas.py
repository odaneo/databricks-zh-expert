from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    artifact_type: ArtifactType | None
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionResponse):
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    model: ModelAlias | None = None
    prompt: PromptName | None = None


class ArtifactMetadataResponse(BaseModel):
    type: ArtifactType
    format: Literal["markdown"] = "markdown"
    title: str


class SendMessageResponse(BaseModel):
    session_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    model_invocation_id: UUID
    model_call_id: UUID
    requested_model: ModelAlias
    used_model: ModelAlias
    fallback_used: bool
    attempt_count: int
    prompt_name: PromptName
    prompt_version: str
    artifact: ArtifactMetadataResponse
