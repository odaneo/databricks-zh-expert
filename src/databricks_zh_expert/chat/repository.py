from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from databricks_zh_expert.db.models import ChatSession, Message, ModelCall


class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_session(
        self,
        title: str,
        expert_profile: str,
        workspace_id: str | None = None,
    ) -> ChatSession:
        session = ChatSession(
            title=title,
            expert_profile=expert_profile,
            workspace_id=workspace_id,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, limit: int, offset: int) -> list[ChatSession]:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间。")
        if offset < 0:
            raise ValueError("offset 不能小于 0。")

        result = await self.db.scalars(
            select(ChatSession)
            .order_by(
                ChatSession.updated_at.desc(),
                ChatSession.created_at.desc(),
                ChatSession.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def get_session(self, session_id: UUID) -> ChatSession | None:
        result = await self.db.scalars(select(ChatSession).where(ChatSession.id == session_id))
        return result.one_or_none()

    async def list_messages(
        self,
        session_id: UUID,
        limit: int = 100,
    ) -> list[Message]:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间。")

        result = await self.db.scalars(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        return list(result.all())

    async def create_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        artifact_type: str | None = None,
        source_citations: list[dict[str, Any]] | None = None,
    ) -> Message:
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            artifact_type=artifact_type,
            source_citations=source_citations,
        )
        self.db.add(message)
        await self.db.execute(
            update(ChatSession).where(ChatSession.id == session_id).values(updated_at=func.now())
        )
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def create_model_call(
        self,
        *,
        session_id: UUID,
        invocation_id: UUID,
        provider: str,
        model: str,
        model_alias: str,
        attempt_number: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
        success: bool,
        retryable: bool,
        error_code: str | None,
        error_message: str | None,
        prompt_name: str,
        prompt_version: str,
        artifact_type: str,
        artifact_valid: bool | None,
        artifact_error_code: str | None,
        expert_profile: str,
        expert_template_selections: list[dict[str, object]],
        workspace_id: str | None = None,
        workspace_version: str | None = None,
        workspace_source_hash: str | None = None,
        workspace_context: list[dict[str, object]] | None = None,
        project_fact_status: str | None = None,
    ) -> ModelCall:
        model_call = ModelCall(
            session_id=session_id,
            invocation_id=invocation_id,
            provider=provider,
            model=model,
            model_alias=model_alias,
            attempt_number=attempt_number,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            retryable=retryable,
            error_code=error_code,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            artifact_type=artifact_type,
            artifact_valid=artifact_valid,
            artifact_error_code=artifact_error_code,
            expert_profile=expert_profile,
            expert_template_selections=expert_template_selections,
            workspace_id=workspace_id,
            workspace_version=workspace_version,
            workspace_source_hash=workspace_source_hash,
            workspace_context=workspace_context,
            project_fact_status=project_fact_status,
            error_message=error_message,
        )
        self.db.add(model_call)
        await self.db.commit()
        await self.db.refresh(model_call)
        return model_call

    async def list_recent_messages(
        self,
        session_id: UUID,
        limit: int = 20,
    ) -> list[Message]:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间。")

        result = await self.db.scalars(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(result.all()))
