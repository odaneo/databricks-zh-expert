from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    artifact_type: str | None
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionResponse):
    messages: list[MessageResponse]
