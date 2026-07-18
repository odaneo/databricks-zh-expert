from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from databricks_zh_expert.api.dependencies import (
    get_chat_repository,
    get_chat_service,
    get_expert_template_registry,
    get_workspace_registry,
)
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.chat.schemas import (
    ArtifactMetadataResponse,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionCreate,
    SessionDetail,
    SessionResponse,
)
from databricks_zh_expert.chat.service import ChatService
from databricks_zh_expert.core.errors import (
    AppError,
    ExpertProfileNotFoundAppError,
    WorkspaceNotFoundAppError,
)
from databricks_zh_expert.expert_templates.registry import (
    ExpertTemplateRegistry,
    ExpertTemplateRegistryError,
)
from databricks_zh_expert.workspace.registry import (
    WorkspaceRegistry,
    WorkspaceRegistryError,
)

router = APIRouter(prefix="/api/chat", tags=["会话"])


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: SessionCreate,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    expert_registry: Annotated[
        ExpertTemplateRegistry,
        Depends(get_expert_template_registry),
    ],
    workspace_registry: Annotated[
        WorkspaceRegistry,
        Depends(get_workspace_registry),
    ],
) -> SessionResponse:
    try:
        expert_registry.get_profile(payload.expert_profile)
    except ExpertTemplateRegistryError:
        raise ExpertProfileNotFoundAppError() from None
    if payload.workspace_id is not None:
        try:
            workspace_registry.get(payload.workspace_id)
        except WorkspaceRegistryError:
            raise WorkspaceNotFoundAppError() from None
    session = await repository.create_session(
        payload.title,
        payload.expert_profile,
        payload.workspace_id,
    )
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
        expert_profile=session.expert_profile,
        workspace_id=session.workspace_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[MessageResponse.model_validate(message) for message in messages],
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    session_id: UUID,
    payload: SendMessageRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> SendMessageResponse:
    result = await service.send_message(
        session_id=session_id,
        content=payload.content,
        requested_model=payload.model,
        requested_prompt=payload.prompt,
    )
    return SendMessageResponse(
        session_id=session_id,
        user_message=MessageResponse.model_validate(result.user_message),
        assistant_message=MessageResponse.model_validate(result.assistant_message),
        model_invocation_id=result.model_invocation_id,
        model_call_id=result.model_call.id,
        requested_model=result.requested_model,
        used_model=result.used_model,
        fallback_used=result.fallback_used,
        attempt_count=result.attempt_count,
        prompt_name=result.prompt_name,
        prompt_version=result.prompt_version,
        artifact=ArtifactMetadataResponse(
            type=result.artifact.artifact_type,
            title=result.artifact.title,
            project_fact_status=result.project_fact_status,
        ),
    )
