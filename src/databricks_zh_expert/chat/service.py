from dataclasses import dataclass
from typing import cast
from uuid import UUID

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.db.models import Message, ModelCall
from databricks_zh_expert.llm.client import ModelMessage, ModelRole
from databricks_zh_expert.llm.gateway import (
    ModelAttempt,
    ModelGateway,
    ModelGatewayFailure,
)
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.observability.model_trace import (
    ModelCallTrace,
    ModelTraceSink,
)


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    user_message: Message
    assistant_message: Message
    model_call: ModelCall
    model_invocation_id: UUID
    requested_model: ModelAlias
    used_model: ModelAlias
    fallback_used: bool
    attempt_count: int


def build_trace(
    model_call: ModelCall,
    session_id: UUID,
    attempt: ModelAttempt,
) -> ModelCallTrace:
    return ModelCallTrace(
        model_call_id=model_call.id,
        invocation_id=attempt.invocation_id,
        session_id=session_id,
        recorded_at=model_call.created_at,
        requested_model=attempt.requested_model,
        model_alias=attempt.model_alias,
        provider=attempt.provider,
        attempt_number=attempt.attempt_number,
        latency_ms=attempt.latency_ms,
        success=attempt.success,
        retryable=attempt.retryable,
        request=attempt.request,
        response=attempt.response,
        error=attempt.error,
    )


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        model_gateway: ModelGateway,
        trace_sink: ModelTraceSink,
    ) -> None:
        self.repository = repository
        self.model_gateway = model_gateway
        self.trace_sink = trace_sink

    async def send_message(
        self,
        session_id: UUID,
        content: str,
        requested_model: ModelAlias | None = None,
    ) -> SendMessageResult:
        session = await self.repository.get_session(session_id)
        if session is None:
            raise AppError(
                code="session_not_found",
                message="会话不存在。",
                status_code=404,
            )

        user_message = await self.repository.create_message(
            session_id=session_id,
            role="user",
            content=content,
        )
        recent_messages = await self.repository.list_recent_messages(
            session_id,
            limit=20,
        )
        model_messages = [
            ModelMessage(
                role=cast(ModelRole, message.role),
                content=message.content,
            )
            for message in recent_messages
        ]

        try:
            async for attempt in self.model_gateway.run(model_messages, requested_model):
                error_code = (
                    str(attempt.error["code"])
                    if attempt.error is not None and attempt.error.get("code") is not None
                    else None
                )
                error_message = (
                    str(attempt.error["message"])
                    if attempt.error is not None and attempt.error.get("message") is not None
                    else None
                )
                model_call = await self.repository.create_model_call(
                    session_id=session_id,
                    invocation_id=attempt.invocation_id,
                    provider=attempt.provider,
                    model=attempt.litellm_model,
                    model_alias=attempt.model_alias,
                    attempt_number=attempt.attempt_number,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                    latency_ms=attempt.latency_ms,
                    success=attempt.success,
                    retryable=attempt.retryable,
                    error_code=error_code,
                    error_message=error_message,
                )
                await self.trace_sink.write(build_trace(model_call, session_id, attempt))

                if attempt.success:
                    if attempt.content is None:
                        raise RuntimeError("成功的模型尝试缺少输出内容。")
                    assistant_message = await self.repository.create_message(
                        session_id,
                        "assistant",
                        attempt.content,
                        artifact_type=ArtifactType.ANSWER.value,
                    )
                    return SendMessageResult(
                        user_message=user_message,
                        assistant_message=assistant_message,
                        model_call=model_call,
                        model_invocation_id=attempt.invocation_id,
                        requested_model=attempt.requested_model,
                        used_model=attempt.model_alias,
                        fallback_used=attempt.attempt_number > 1,
                        attempt_count=attempt.attempt_number,
                    )
        except ModelGatewayFailure as error:
            raise AppError(
                code=error.code,
                message=error.message,
                status_code=error.status_code,
            ) from None

        raise RuntimeError("模型网关未返回成功尝试。")
