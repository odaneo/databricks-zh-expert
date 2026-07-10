from dataclasses import dataclass
from time import perf_counter
from typing import cast
from uuid import UUID

from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.db.models import Message, ModelCall
from databricks_zh_expert.llm.client import ModelClient, ModelMessage, ModelRole


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    user_message: Message
    assistant_message: Message
    model_call: ModelCall


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        model_client: ModelClient,
    ) -> None:
        self.repository = repository
        self.model_client = model_client

    async def send_message(
        self,
        session_id: UUID,
        content: str,
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

        started_at = perf_counter()
        try:
            model_result = await self.model_client.complete(model_messages)
        except Exception as error:
            latency_ms = self._elapsed_milliseconds(started_at)
            await self.repository.create_model_call(
                session_id=session_id,
                provider=self.model_client.provider,
                model=self.model_client.model,
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=latency_ms,
                success=False,
                error_message=self._safe_error_summary(error),
            )
            if isinstance(error, AppError) and error.code == "model_not_configured":
                raise
            raise AppError(
                code="model_request_failed",
                message="模型调用失败，请稍后重试。",
                status_code=502,
            ) from error

        latency_ms = self._elapsed_milliseconds(started_at)
        assistant_message = await self.repository.create_message(
            session_id=session_id,
            role="assistant",
            content=model_result.content,
            artifact_type="markdown",
        )
        model_call = await self.repository.create_model_call(
            session_id=session_id,
            provider=model_result.provider,
            model=model_result.model,
            prompt_tokens=model_result.prompt_tokens,
            completion_tokens=model_result.completion_tokens,
            latency_ms=latency_ms,
            success=True,
            error_message=None,
        )
        return SendMessageResult(
            user_message=user_message,
            assistant_message=assistant_message,
            model_call=model_call,
        )

    @staticmethod
    def _elapsed_milliseconds(started_at: float) -> int:
        return max(0, round((perf_counter() - started_at) * 1000))

    @staticmethod
    def _safe_error_summary(error: Exception) -> str:
        if isinstance(error, AppError):
            return f"{type(error).__name__}: {error.code}"[:500]
        return f"{type(error).__name__}: 模型调用异常。"[:500]
