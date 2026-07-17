import logging
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from databricks_zh_expert.artifacts.markdown import MarkdownArtifactParser
from databricks_zh_expert.artifacts.types import (
    ArtifactValidationError,
    MarkdownArtifact,
)
from databricks_zh_expert.chat.context import ChatContextBundle
from databricks_zh_expert.chat.repository import ChatRepository
from databricks_zh_expert.core.errors import AppError
from databricks_zh_expert.db.models import Message, ModelCall
from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateRetrievalBundle,
)
from databricks_zh_expert.llm.client import ModelMessage, ModelRole
from databricks_zh_expert.llm.gateway import (
    ModelAttempt,
    ModelGateway,
    ModelGatewayFailure,
)
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.observability.model_trace import (
    ArtifactValidationTrace,
    ExpertTemplateCandidateTrace,
    ExpertTemplateSelectionTrace,
    ExpertTemplateTrace,
    ModelCallTrace,
    ModelTraceSink,
    RetrievalCandidateTrace,
    RetrievalTrace,
)
from databricks_zh_expert.prompts.registry import (
    PromptName,
    PromptRegistry,
    PromptSpec,
    PromptUnavailableError,
    RenderedPrompt,
)
from databricks_zh_expert.rag.constants import EMBEDDING_MODEL
from databricks_zh_expert.rag.context import RetrievalBundle

logger = logging.getLogger(__name__)


class ChatContextBuilder(Protocol):
    async def build(
        self,
        query: str,
        *,
        prompt_spec: PromptSpec,
        expert_profile: str,
    ) -> ChatContextBundle: ...


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
    prompt_name: PromptName
    prompt_version: str
    artifact: MarkdownArtifact


def build_trace(
    model_call: ModelCall,
    session_id: UUID,
    attempt: ModelAttempt,
    rendered_prompt: RenderedPrompt,
    artifact_validation: ArtifactValidationTrace | None,
    retrieval: RetrievalTrace | None,
    expert_profile: str,
    expert_templates: ExpertTemplateTrace | None,
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
        prompt_name=rendered_prompt.name,
        prompt_version=rendered_prompt.version,
        artifact_type=rendered_prompt.artifact_type,
        artifact_validation=artifact_validation,
        request=attempt.request,
        response=attempt.response,
        error=attempt.error,
        retrieval=retrieval,
        expert_profile=expert_profile,
        expert_templates=expert_templates,
    )


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        model_gateway: ModelGateway,
        trace_sink: ModelTraceSink,
        prompt_registry: PromptRegistry,
        artifact_parser: MarkdownArtifactParser,
        *,
        context_service: ChatContextBuilder,
    ) -> None:
        self.repository = repository
        self.model_gateway = model_gateway
        self.trace_sink = trace_sink
        self.prompt_registry = prompt_registry
        self.artifact_parser = artifact_parser
        self.context_service = context_service

    async def send_message(
        self,
        session_id: UUID,
        content: str,
        requested_model: ModelAlias | None = None,
        requested_prompt: PromptName | None = None,
    ) -> SendMessageResult:
        session = await self.repository.get_session(session_id)
        if session is None:
            raise AppError(
                code="session_not_found",
                message="会话不存在。",
                status_code=404,
            )

        try:
            rendered_prompt = self.prompt_registry.render(requested_prompt)
        except PromptUnavailableError as error:
            raise AppError(
                code="prompt_not_available",
                message=str(error),
                status_code=409,
            ) from None
        prompt_spec = self.prompt_registry.get(rendered_prompt.name)

        user_message = await self.repository.create_message(
            session_id=session_id,
            role="user",
            content=content,
        )
        recent_messages = await self.repository.list_recent_messages(
            session_id,
            limit=20,
        )
        context_bundle = await self.context_service.build(
            content,
            prompt_spec=prompt_spec,
            expert_profile=session.expert_profile,
        )
        retrieval_trace = (
            _retrieval_trace(
                context_bundle.official,
                latency_ms=context_bundle.official_latency_ms,
            )
            if context_bundle.official is not None
            else None
        )
        expert_template_trace = (
            _expert_template_trace(
                context_bundle.expert,
                latency_ms=context_bundle.expert_latency_ms,
            )
            if context_bundle.expert is not None
            else None
        )
        expert_template_selections = _expert_template_selection_payloads(context_bundle.expert)

        historical_messages = [
            message
            for message in recent_messages
            if message.id != user_message.id and message.role in {"user", "assistant"}
        ]
        model_messages = [
            ModelMessage(role="system", content=rendered_prompt.system_message),
            *[
                ModelMessage(
                    role=cast(ModelRole, message.role),
                    content=message.content,
                )
                for message in historical_messages
            ],
        ]
        if context_bundle.expert is not None:
            model_messages.append(
                ModelMessage(
                    role="user",
                    content=context_bundle.expert.context,
                )
            )
        if context_bundle.official is not None:
            model_messages.append(
                ModelMessage(
                    role="user",
                    content=context_bundle.official.context,
                )
            )
        model_messages.append(ModelMessage(role="user", content=content))

        try:
            async for attempt in self.model_gateway.run(model_messages, requested_model):
                artifact: MarkdownArtifact | None = None
                artifact_error: ArtifactValidationError | None = None
                artifact_validation: ArtifactValidationTrace | None = None
                if attempt.success and attempt.content is not None:
                    try:
                        artifact = self.artifact_parser.parse(
                            prompt_spec,
                            attempt.content,
                        )
                        artifact_validation = ArtifactValidationTrace(
                            valid=True,
                            violations=(),
                        )
                    except ArtifactValidationError as error:
                        artifact_error = error
                        artifact_validation = ArtifactValidationTrace(
                            valid=False,
                            violations=error.violations,
                        )

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
                    prompt_name=rendered_prompt.name.value,
                    prompt_version=rendered_prompt.version,
                    artifact_type=rendered_prompt.artifact_type.value,
                    artifact_valid=(
                        artifact_validation.valid if artifact_validation is not None else None
                    ),
                    artifact_error_code=(
                        "artifact_invalid" if artifact_error is not None else None
                    ),
                    expert_profile=session.expert_profile,
                    expert_template_selections=expert_template_selections,
                )
                await self.trace_sink.write(
                    build_trace(
                        model_call,
                        session_id,
                        attempt,
                        rendered_prompt,
                        artifact_validation,
                        retrieval_trace,
                        session.expert_profile,
                        expert_template_trace,
                    )
                )

                if attempt.success:
                    if attempt.content is None:
                        raise RuntimeError("成功的模型尝试缺少输出内容。")
                    if artifact_error is not None:
                        logger.warning(
                            "模型输出 Artifact 校验失败：prompt=%s invocation_id=%s violations=%s",
                            rendered_prompt.name.value,
                            attempt.invocation_id,
                            ",".join(artifact_error.violations),
                        )
                        raise AppError(
                            code="artifact_invalid",
                            message="模型输出未满足交付物格式要求，请重试。",
                            status_code=502,
                        )
                    if artifact is None:
                        raise RuntimeError("成功的模型尝试缺少 Artifact。")
                    assistant_message = await self.repository.create_message(
                        session_id,
                        "assistant",
                        artifact.content,
                        artifact_type=artifact.artifact_type,
                        source_citations=(
                            _citation_payloads(context_bundle.official)
                            if context_bundle.official is not None
                            else None
                        ),
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
                        prompt_name=rendered_prompt.name,
                        prompt_version=rendered_prompt.version,
                        artifact=artifact,
                    )
        except ModelGatewayFailure as error:
            raise AppError(
                code=error.code,
                message=error.message,
                status_code=error.status_code,
            ) from None

        raise RuntimeError("模型网关未返回成功尝试。")


def _citation_payloads(bundle: RetrievalBundle) -> list[dict[str, object]]:
    return [
        {
            "citation_id": citation.citation_id,
            "rank": citation.rank,
            "title": citation.title,
            "url": citation.url,
            "heading": citation.heading,
            "chunk_id": str(citation.chunk_id),
            "chunk_hash": citation.chunk_hash,
        }
        for citation in bundle.citations
    ]


def _retrieval_trace(bundle: RetrievalBundle, *, latency_ms: int) -> RetrievalTrace:
    selected_ids = {chunk.chunk_id for chunk in bundle.selected_chunks}
    candidates = tuple(
        RetrievalCandidateTrace(
            chunk_id=chunk.chunk_id,
            rank=rank,
            vector_rank=chunk.vector_rank,
            vector_score=chunk.vector_similarity,
            lexical_rank=chunk.lexical_rank,
            lexical_score=chunk.lexical_score,
            fused_score=chunk.fused_score,
            url=chunk.source_ref,
            selected=chunk.chunk_id in selected_ids,
        )
        for rank, chunk in enumerate(bundle.ranked_candidates, start=1)
    )
    return RetrievalTrace(
        embedding_model=EMBEDDING_MODEL,
        latency_ms=latency_ms,
        candidates=candidates,
        selected_urls=tuple(citation.url for citation in bundle.citations),
    )


def _expert_template_selection_payloads(
    bundle: ExpertTemplateRetrievalBundle | None,
) -> list[dict[str, object]]:
    if bundle is None:
        return []
    return [
        {
            "template_id": selection.template_id,
            "version": selection.version,
            "content_hash": selection.content_hash,
            "layer": selection.layer,
            "profile": selection.profile_id,
            "rank": selection.rank,
            "reason": selection.reason,
        }
        for selection in bundle.selected_templates
    ]


def _expert_template_trace(
    bundle: ExpertTemplateRetrievalBundle,
    *,
    latency_ms: int,
) -> ExpertTemplateTrace:
    selected_ids = {selection.record_id for selection in bundle.selected_templates}
    candidates = tuple(
        ExpertTemplateCandidateTrace(
            template_id=candidate.template_id,
            version=candidate.version,
            rank=rank,
            vector_rank=candidate.vector_rank,
            vector_score=candidate.vector_similarity,
            lexical_rank=candidate.lexical_rank,
            lexical_score=candidate.lexical_score,
            fused_score=candidate.fused_score,
            selected=candidate.template_record_id in selected_ids,
        )
        for rank, candidate in enumerate(bundle.ranked_candidates, start=1)
    )
    selected = tuple(
        ExpertTemplateSelectionTrace(
            template_id=selection.template_id,
            version=selection.version,
            content_hash=selection.content_hash,
            layer=selection.layer,
            profile=selection.profile_id,
            rank=selection.rank,
            reason=selection.reason,
            extends=selection.extends,
        )
        for selection in bundle.selected_templates
    )
    return ExpertTemplateTrace(
        status="selected",
        embedding_model=EMBEDDING_MODEL,
        latency_ms=latency_ms,
        context_token_count=bundle.context_token_count,
        candidates=candidates,
        selected=selected,
    )
