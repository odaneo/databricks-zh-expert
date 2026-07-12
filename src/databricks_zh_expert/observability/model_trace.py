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
            "schema_version": "1.3",
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
            },
            "request": trace.request,
            "response": trace.response,
            "error": trace.error,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
