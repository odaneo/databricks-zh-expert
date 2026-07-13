import logging
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Any, Protocol, cast

from openai import AsyncOpenAI
from pydantic import SecretStr

from databricks_zh_expert.rag.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    code: str


class EmbeddingInputError(ValueError):
    code = "embedding_request_failed"


class EmbeddingNotConfiguredError(EmbeddingError):
    code = "embedding_not_configured"


class EmbeddingRequestError(EmbeddingError):
    code = "embedding_request_failed"


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    index: int
    embedding: tuple[float, ...]


class EmbeddingClient(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingResult, ...]: ...

    async def embed_query(self, text: str) -> EmbeddingResult: ...


class _EmbeddingsResource(Protocol):
    async def create(self, **kwargs: Any) -> object: ...


class _OpenAIClient(Protocol):
    @property
    def embeddings(self) -> _EmbeddingsResource: ...


class OpenAIEmbeddingClient:
    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        timeout_seconds: float = 60.0,
        client: _OpenAIClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Embedding 请求超时必须大于 0。")
        if client is not None:
            self._client = client
        elif api_key is not None:
            self._client = cast(
                _OpenAIClient,
                AsyncOpenAI(
                    api_key=api_key.get_secret_value(),
                    timeout=timeout_seconds,
                    max_retries=0,
                ),
            )
        else:
            self._client = None

    async def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingResult, ...]:
        inputs = self._validate_inputs(texts)
        if self._client is None:
            raise EmbeddingNotConfiguredError("未配置 OpenAI API Key，知识向量能力不可用。")

        started_at = perf_counter()
        try:
            response = await self._client.embeddings.create(
                input=inputs,
                model=EMBEDDING_MODEL,
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )
            results = self._validate_response(response, len(inputs))
        except EmbeddingRequestError as error:
            self._log_failure(len(inputs), started_at, type(error).__name__)
            raise
        except Exception as error:
            self._log_failure(len(inputs), started_at, type(error).__name__)
            raise EmbeddingRequestError("OpenAI Embedding 请求失败。") from None

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int):
            prompt_tokens = None
        latency_ms = round((perf_counter() - started_at) * 1000)
        logger.info(
            "Embedding 请求完成：model=%s count=%d prompt_tokens=%s latency_ms=%d",
            EMBEDDING_MODEL,
            len(inputs),
            prompt_tokens,
            latency_ms,
        )
        return results

    async def embed_query(self, text: str) -> EmbeddingResult:
        results = await self.embed_documents((text,))
        return results[0]

    @staticmethod
    def _validate_inputs(texts: Sequence[str]) -> list[str]:
        inputs = list(texts)
        if not inputs:
            raise EmbeddingInputError("Embedding 输入不能为空。")
        if len(inputs) > 2048:
            raise EmbeddingInputError("单次 Embedding 请求最多包含 2048 项。")
        if any(not isinstance(text, str) or not text.strip() for text in inputs):
            raise EmbeddingInputError("Embedding 输入不能包含空文本。")
        return inputs

    @staticmethod
    def _validate_response(response: object, expected_count: int) -> tuple[EmbeddingResult, ...]:
        response_model = getattr(response, "model", None)
        if isinstance(response_model, str) and response_model != EMBEDDING_MODEL:
            raise EmbeddingRequestError("OpenAI Embedding 响应模型不匹配。")

        data = getattr(response, "data", None)
        if not isinstance(data, (list, tuple)) or len(data) != expected_count:
            raise EmbeddingRequestError("OpenAI Embedding 响应数量不匹配。")

        by_index: dict[int, EmbeddingResult] = {}
        for item in data:
            index = getattr(item, "index", None)
            vector = getattr(item, "embedding", None)
            if isinstance(index, bool) or not isinstance(index, int):
                raise EmbeddingRequestError("OpenAI Embedding 响应 index 无效。")
            if index < 0 or index >= expected_count or index in by_index:
                raise EmbeddingRequestError("OpenAI Embedding 响应 index 无效。")
            if not isinstance(vector, (list, tuple)) or len(vector) != EMBEDDING_DIMENSIONS:
                raise EmbeddingRequestError("OpenAI Embedding 响应维度不匹配。")

            normalized: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EmbeddingRequestError("OpenAI Embedding 响应包含无效数值。")
                numeric_value = float(value)
                if not isfinite(numeric_value):
                    raise EmbeddingRequestError("OpenAI Embedding 响应包含无效数值。")
                normalized.append(numeric_value)
            by_index[index] = EmbeddingResult(index=index, embedding=tuple(normalized))

        if set(by_index) != set(range(expected_count)):
            raise EmbeddingRequestError("OpenAI Embedding 响应 index 不连续。")
        return tuple(by_index[index] for index in range(expected_count))

    @staticmethod
    def _log_failure(count: int, started_at: float, error_type: str) -> None:
        latency_ms = round((perf_counter() - started_at) * 1000)
        logger.warning(
            "Embedding 请求失败：model=%s count=%d latency_ms=%d error_type=%s",
            EMBEDDING_MODEL,
            count,
            latency_ms,
            error_type,
        )
