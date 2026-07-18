import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.llm.client import JsonObject
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArtifactValidationTrace:
    valid: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalCandidateTrace:
    chunk_id: UUID
    rank: int
    vector_rank: int | None
    vector_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    fused_score: float
    url: str
    selected: bool


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    embedding_model: str
    latency_ms: int
    candidates: tuple[RetrievalCandidateTrace, ...]
    selected_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpertTemplateCandidateTrace:
    template_id: str
    version: str
    rank: int
    vector_rank: int | None
    vector_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    fused_score: float
    selected: bool


@dataclass(frozen=True, slots=True)
class ExpertTemplateSelectionTrace:
    template_id: str
    version: str
    content_hash: str
    layer: str
    profile: str | None
    rank: int
    reason: str
    extends: str | None


@dataclass(frozen=True, slots=True)
class ExpertTemplateTrace:
    status: str
    embedding_model: str
    latency_ms: int
    context_token_count: int
    candidates: tuple[ExpertTemplateCandidateTrace, ...]
    selected: tuple[ExpertTemplateSelectionTrace, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceCandidateTrace:
    unit_id: str
    source_id: str
    kind: str
    source_path: str
    content_hash: str
    rank: int
    score: float
    selected: bool


@dataclass(frozen=True, slots=True)
class WorkspaceSelectionTrace:
    unit_id: str
    source_id: str
    kind: str
    source_path: str
    content_hash: str
    rank: int
    reason: str


@dataclass(frozen=True, slots=True)
class WorkspaceTrace:
    context_token_count: int
    candidates: tuple[WorkspaceCandidateTrace, ...]
    selected: tuple[WorkspaceSelectionTrace, ...]


@dataclass(frozen=True, slots=True)
class ModelCallTrace:
    model_call_id: UUID
    invocation_id: UUID
    session_id: UUID
    recorded_at: datetime
    requested_model: ModelAlias
    model_alias: ModelAlias
    provider: str
    attempt_number: int
    latency_ms: int
    success: bool
    retryable: bool
    prompt_name: PromptName
    prompt_version: str
    artifact_type: ArtifactType
    artifact_validation: ArtifactValidationTrace | None
    request: JsonObject
    response: JsonObject | None
    error: JsonObject | None
    retrieval: RetrievalTrace | None = None
    expert_profile: str = "generic"
    expert_templates: ExpertTemplateTrace | None = None
    workspace_id: str | None = None
    workspace_version: str | None = None
    workspace_source_hash: str | None = None
    project_fact_status: str | None = None
    workspace: WorkspaceTrace | None = None


class ModelTraceSink(Protocol):
    async def write(self, trace: ModelCallTrace) -> None: ...


class NullModelTraceSink:
    async def write(self, trace: ModelCallTrace) -> None:
        del trace


class JsonlModelTraceSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def write(self, trace: ModelCallTrace) -> None:
        try:
            line = self._serialize(trace)
            async with self._lock:
                await asyncio.to_thread(self._append_line, line)
        except Exception:
            logger.warning(
                "模型调用 Trace 写入失败：%s",
                self.path,
                exc_info=True,
            )

    def _append_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"{line}\n")

    @staticmethod
    def _serialize(trace: ModelCallTrace) -> str:
        payload = {
            "schema_version": "1.7",
            "protocol": "openai.chat.completions",
            "trace": {
                "model_call_id": str(trace.model_call_id),
                "invocation_id": str(trace.invocation_id),
                "session_id": str(trace.session_id),
                "recorded_at": trace.recorded_at.isoformat(),
                "requested_model": trace.requested_model,
                "model_alias": trace.model_alias,
                "provider": trace.provider,
                "attempt_number": trace.attempt_number,
                "latency_ms": trace.latency_ms,
                "success": trace.success,
                "retryable": trace.retryable,
                "prompt_name": trace.prompt_name,
                "prompt_version": trace.prompt_version,
                "artifact_type": trace.artifact_type,
                "artifact_validation": (
                    {
                        "valid": trace.artifact_validation.valid,
                        "violations": list(trace.artifact_validation.violations),
                    }
                    if trace.artifact_validation is not None
                    else None
                ),
                "expert_profile": trace.expert_profile,
                "workspace_id": trace.workspace_id,
                "workspace_version": trace.workspace_version,
                "workspace_source_hash": trace.workspace_source_hash,
                "project_fact_status": trace.project_fact_status,
            },
            "retrieval": (
                {
                    "embedding_model": trace.retrieval.embedding_model,
                    "latency_ms": trace.retrieval.latency_ms,
                    "candidates": [
                        {
                            "chunk_id": str(candidate.chunk_id),
                            "rank": candidate.rank,
                            "vector_rank": candidate.vector_rank,
                            "vector_score": candidate.vector_score,
                            "lexical_rank": candidate.lexical_rank,
                            "lexical_score": candidate.lexical_score,
                            "fused_score": candidate.fused_score,
                            "url": candidate.url,
                            "selected": candidate.selected,
                        }
                        for candidate in trace.retrieval.candidates
                    ],
                    "selected_urls": list(trace.retrieval.selected_urls),
                }
                if trace.retrieval is not None
                else None
            ),
            "expert_templates": (
                {
                    "status": trace.expert_templates.status,
                    "embedding_model": trace.expert_templates.embedding_model,
                    "latency_ms": trace.expert_templates.latency_ms,
                    "context_token_count": trace.expert_templates.context_token_count,
                    "candidates": [
                        {
                            "template_id": candidate.template_id,
                            "version": candidate.version,
                            "rank": candidate.rank,
                            "vector_rank": candidate.vector_rank,
                            "vector_score": candidate.vector_score,
                            "lexical_rank": candidate.lexical_rank,
                            "lexical_score": candidate.lexical_score,
                            "fused_score": candidate.fused_score,
                            "selected": candidate.selected,
                        }
                        for candidate in trace.expert_templates.candidates
                    ],
                    "selected": [
                        {
                            "template_id": selection.template_id,
                            "version": selection.version,
                            "content_hash": selection.content_hash,
                            "layer": selection.layer,
                            "profile": selection.profile,
                            "rank": selection.rank,
                            "reason": selection.reason,
                            "extends": selection.extends,
                        }
                        for selection in trace.expert_templates.selected
                    ],
                }
                if trace.expert_templates is not None
                else None
            ),
            "context": {
                "workspace": (
                    {
                        "context_token_count": trace.workspace.context_token_count,
                        "candidates": [
                            {
                                "unit_id": candidate.unit_id,
                                "source_id": candidate.source_id,
                                "kind": candidate.kind,
                                "source_path": candidate.source_path,
                                "content_hash": candidate.content_hash,
                                "rank": candidate.rank,
                                "score": candidate.score,
                                "selected": candidate.selected,
                            }
                            for candidate in trace.workspace.candidates
                        ],
                        "selected": [
                            {
                                "unit_id": selection.unit_id,
                                "source_id": selection.source_id,
                                "kind": selection.kind,
                                "source_path": selection.source_path,
                                "content_hash": selection.content_hash,
                                "rank": selection.rank,
                                "reason": selection.reason,
                            }
                            for selection in trace.workspace.selected
                        ],
                    }
                    if trace.workspace is not None
                    else None
                )
            },
            "request": trace.request,
            "response": trace.response,
            "error": trace.error,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
