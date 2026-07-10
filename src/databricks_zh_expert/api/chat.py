from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from databricks_zh_expert.api.dependencies import get_chat_repository
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.schemas import (
    MessageResponse,
    SessionCreate,
    SessionDetail,
    SessionResponse,
)
from databricks_zh_expert.core.errors import AppError

router = APIRouter(prefix="/api/chat", tags=["会话"])


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: SessionCreate,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> SessionResponse:
    session = await repository.create_session(payload.title)
    return SessionResponse.model_validate(session)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionResponse]:
    sessions = await repository.list_sessions(limit=limit, offset=offset)
    return [SessionResponse.model_validate(session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: UUID,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
) -> SessionDetail:
    session = await repository.get_session(session_id)
    if session is None:
        raise AppError(
            code="session_not_found",
            message="会话不存在。",
            status_code=404,
        )

    messages = await repository.list_messages(session_id)
    return SessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[MessageResponse.model_validate(message) for message in messages],
    )
