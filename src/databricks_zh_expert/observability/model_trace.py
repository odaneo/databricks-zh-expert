import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from databricks_zh_expert.llm.client import JsonObject

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelCallTrace:
    model_call_id: UUID
    session_id: UUID
    recorded_at: datetime
    provider: str
    latency_ms: int
    success: bool
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
            "schema_version": "1.0",
            "protocol": "openai.chat.completions",
            "trace": {
                "model_call_id": str(trace.model_call_id),
                "session_id": str(trace.session_id),
                "recorded_at": trace.recorded_at.isoformat(),
                "provider": trace.provider,
                "latency_ms": trace.latency_ms,
                "success": trace.success,
            },
            "request": trace.request,
            "response": trace.response,
            "error": trace.error,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
