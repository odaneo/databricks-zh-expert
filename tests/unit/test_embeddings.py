import logging
from dataclasses import dataclass
from math import inf, nan
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from databricks_zh_expert.main import create_app
from databricks_zh_expert.rag.embeddings import (
    EmbeddingInputError,
    EmbeddingNotConfiguredError,
    EmbeddingRequestError,
    OpenAIEmbeddingClient,
)


@dataclass(slots=True)
class _FakeEmbedding:
    index: int
    embedding: list[float]


class _FakeEmbeddingsResource:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeOpenAI:
    def __init__(self, resource: _FakeEmbeddingsResource) -> None:
        self.embeddings = resource


def _vector(value: float = 0.0, *, dimensions: int = 1536) -> list[float]:
    return [value] * dimensions


def _response(
    *items: _FakeEmbedding,
    model: str = "text-embedding-3-small",
    prompt_tokens: int = 12,
) -> object:
    return SimpleNamespace(
        data=list(items),
        model=model,
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
    )


def _client(resource: _FakeEmbeddingsResource) -> OpenAIEmbeddingClient:
    return OpenAIEmbeddingClient(
        api_key=SecretStr("openai-secret"),
        client=_FakeOpenAI(resource),
    )


@pytest.mark.asyncio
async def test_embed_documents_sends_fixed_request_and_restores_input_order() -> None:
    resource = _FakeEmbeddingsResource(
        _response(
            _FakeEmbedding(index=1, embedding=_vector(0.2)),
            _FakeEmbedding(index=0, embedding=_vector(0.1)),
        )
    )

    results = await _client(resource).embed_documents(("first document", "second document"))

    assert resource.requests == [
        {
            "input": ["first document", "second document"],
            "model": "text-embedding-3-small",
            "dimensions": 1536,
            "encoding_format": "float",
        }
    ]
    assert tuple(result.index for result in results) == (0, 1)
    assert results[0].embedding[0] == 0.1
    assert results[1].embedding[0] == 0.2
    assert all(len(result.embedding) == 1536 for result in results)


@pytest.mark.asyncio
async def test_embed_query_uses_one_item_batch() -> None:
    resource = _FakeEmbeddingsResource(_response(_FakeEmbedding(index=0, embedding=_vector(0.3))))

    result = await _client(resource).embed_query("如何设计 Lakeflow Jobs？")

    assert resource.requests[0]["input"] == ["如何设计 Lakeflow Jobs？"]
    assert result.index == 0
    assert result.embedding[0] == 0.3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _response(_FakeEmbedding(index=0, embedding=_vector())),
        _response(
            _FakeEmbedding(index=0, embedding=_vector()),
            _FakeEmbedding(index=0, embedding=_vector()),
        ),
        _response(
            _FakeEmbedding(index=0, embedding=_vector()),
            _FakeEmbedding(index=2, embedding=_vector()),
        ),
        _response(
            _FakeEmbedding(index=0, embedding=_vector(dimensions=1535)),
            _FakeEmbedding(index=1, embedding=_vector()),
        ),
        _response(
            _FakeEmbedding(index=0, embedding=_vector(nan)),
            _FakeEmbedding(index=1, embedding=_vector()),
        ),
        _response(
            _FakeEmbedding(index=0, embedding=_vector(inf)),
            _FakeEmbedding(index=1, embedding=_vector()),
        ),
        _response(
            _FakeEmbedding(index=0, embedding=_vector()),
            _FakeEmbedding(index=1, embedding=_vector()),
            model="text-embedding-3-large",
        ),
    ],
)
async def test_embed_documents_rejects_invalid_response(response: object) -> None:
    resource = _FakeEmbeddingsResource(response)

    with pytest.raises(EmbeddingRequestError) as error:
        await _client(resource).embed_documents(("first", "second"))

    assert error.value.code == "embedding_request_failed"


@pytest.mark.asyncio
async def test_openai_error_is_safe_and_does_not_leak_key_or_provider_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    resource = _FakeEmbeddingsResource(
        error=RuntimeError("Authorization: Bearer openai-secret; sensitive provider body")
    )

    with caplog.at_level(logging.WARNING), pytest.raises(EmbeddingRequestError) as error:
        await _client(resource).embed_query("sensitive query text")

    rendered = f"{error.value}\n{caplog.text}"
    assert error.value.code == "embedding_request_failed"
    assert "openai-secret" not in rendered
    assert "sensitive provider body" not in rendered
    assert "sensitive query text" not in rendered


@pytest.mark.asyncio
async def test_success_log_contains_metadata_but_not_text_or_vector(
    caplog: pytest.LogCaptureFixture,
) -> None:
    resource = _FakeEmbeddingsResource(
        _response(_FakeEmbedding(index=0, embedding=_vector(0.123456789)), prompt_tokens=7)
    )

    with caplog.at_level(logging.INFO):
        await _client(resource).embed_documents(("private document body",))

    assert "text-embedding-3-small" in caplog.text
    assert "count=1" in caplog.text
    assert "prompt_tokens=7" in caplog.text
    assert "private document body" not in caplog.text
    assert "0.123456789" not in caplog.text


@pytest.mark.asyncio
async def test_missing_openai_key_only_disables_embedding(
    settings_factory,
) -> None:
    settings = settings_factory(
        default_model="deepseek-v4-flash",
        fallback_models=("deepseek-v4-flash",),
        openai_api_key=None,
    )

    app = create_app(settings=settings)
    client = OpenAIEmbeddingClient(api_key=settings.openai_api_key)

    assert app.state.settings.default_model == "deepseek-v4-flash"
    with pytest.raises(EmbeddingNotConfiguredError) as error:
        await client.embed_query("query")
    assert error.value.code == "embedding_not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize("texts", [(), ("",), ("   ",)])
async def test_embed_documents_rejects_empty_input_without_api_call(
    texts: tuple[str, ...],
) -> None:
    resource = _FakeEmbeddingsResource(_response(_FakeEmbedding(index=0, embedding=_vector())))

    with pytest.raises(EmbeddingInputError):
        await _client(resource).embed_documents(texts)

    assert resource.requests == []
