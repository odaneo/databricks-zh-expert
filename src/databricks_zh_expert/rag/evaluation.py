from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml import YAMLError

from databricks_zh_expert.rag.context import (
    KnowledgeContextNotFoundError,
    RankedKnowledgeChunk,
    RetrievalBundle,
)

EVALUATION_TOP_K = 5
EVALUATION_MINIMUM_RECALL = 0.8
EVALUATION_DATASET_PATH = Path("tests/evals/databricks_rag.yml")
_EVALUATION_ALLOWED_HOSTS = frozenset(
    {
        "docs.databricks.com",
        "www.databricks.com",
    }
)

EvaluationCategory = Literal[
    "jobs",
    "medallion",
    "auto_loader",
    "streaming",
    "unity_catalog",
    "sql_performance",
    "cost",
    "api",
]
REQUIRED_EVALUATION_CATEGORIES = frozenset(
    {
        "jobs",
        "medallion",
        "auto_loader",
        "streaming",
        "unity_catalog",
        "sql_performance",
        "cost",
        "api",
    }
)
StableKey = Annotated[
    str,
    Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    ),
]


class KnowledgeEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluationCase:
    id: str
    category: EvaluationCategory
    question: str
    expected_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluationDataset:
    version: int
    cases: tuple[KnowledgeEvaluationCase, ...]


@dataclass(frozen=True, slots=True)
class RetrievedSource:
    source_key: str
    url: str


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    id: str
    category: EvaluationCategory
    question: str
    expected_urls: tuple[str, ...]
    actual_sources: tuple[RetrievedSource, ...]
    first_relevant_rank: int | None
    hit: bool


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluationResult:
    case_count: int
    top_k: int
    minimum_recall: float
    recall_at_5: float
    mrr: float
    passed: bool
    results: tuple[EvaluationCaseResult, ...]
    failures: tuple[EvaluationCaseResult, ...]


class RetrievalRunner(Protocol):
    async def retrieve(self, query: str) -> RetrievalBundle: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _EvaluationCaseModel(_StrictModel):
    id: StableKey
    category: EvaluationCategory
    question: str = Field(min_length=5, max_length=500)
    expected_urls: tuple[str, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_unique_urls(self) -> Self:
        identities = tuple(_evaluation_url(url) for url in self.expected_urls)
        if len(identities) != len(set(identities)):
            raise ValueError("评估题不能包含重复 expected_urls。")
        return self

    @field_validator("expected_urls")
    @classmethod
    def validate_expected_urls(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_evaluation_url(value) for value in values)


class _EvaluationDatasetModel(_StrictModel):
    version: Literal[1]
    cases: tuple[_EvaluationCaseModel, ...] = Field(min_length=20)

    @model_validator(mode="after")
    def validate_dataset_coverage(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("评估集 case id 不能重复。")
        categories = {case.category for case in self.cases}
        missing = REQUIRED_EVALUATION_CATEGORIES - categories
        if missing:
            raise ValueError(f"评估集缺少类别：{', '.join(sorted(missing))}。")
        return self


def load_evaluation_set(path: Path) -> KnowledgeEvaluationDataset:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise KnowledgeEvaluationError(f"无法读取知识检索评估集：{path}") from error
    except YAMLError as error:
        raise KnowledgeEvaluationError(f"知识检索评估集不是合法 YAML：{path}") from error

    try:
        model = _EvaluationDatasetModel.model_validate(payload)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise KnowledgeEvaluationError(f"知识检索评估集无效：{details}") from None

    return KnowledgeEvaluationDataset(
        version=model.version,
        cases=tuple(
            KnowledgeEvaluationCase(
                id=case.id,
                category=case.category,
                question=case.question,
                expected_urls=case.expected_urls,
            )
            for case in model.cases
        ),
    )


def _validate_evaluation_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise ValueError("Databricks 评估 URL 必须使用 HTTPS。")
    if parsed.hostname not in _EVALUATION_ALLOWED_HOSTS:
        raise ValueError("Databricks 评估 URL 必须属于允许的 Databricks 官方域名。")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise ValueError("Databricks 评估 URL 不能包含凭据或自定义端口。")
    if parsed.query or parsed.fragment:
        raise ValueError("Databricks 评估 URL 不能包含 query 或 fragment。")
    return value


class KnowledgeEvaluator:
    def __init__(
        self,
        retriever: RetrievalRunner,
        *,
        top_k: int = EVALUATION_TOP_K,
        minimum_recall: float = EVALUATION_MINIMUM_RECALL,
    ) -> None:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("评估 top-k 必须是正整数。")
        if (
            isinstance(minimum_recall, bool)
            or not isinstance(minimum_recall, int | float)
            or not 0 <= minimum_recall <= 1
        ):
            raise ValueError("评估最低 Recall 必须在 0 到 1 之间。")
        self._retriever = retriever
        self._top_k = top_k
        self._minimum_recall = float(minimum_recall)

    async def evaluate_file(self, path: Path) -> KnowledgeEvaluationResult:
        return await self.evaluate(load_evaluation_set(path))

    async def evaluate(
        self,
        dataset: KnowledgeEvaluationDataset,
    ) -> KnowledgeEvaluationResult:
        if not dataset.cases:
            raise KnowledgeEvaluationError("知识检索评估集不能为空。")

        results = []
        for case in dataset.cases:
            try:
                bundle = await self._retriever.retrieve(case.question)
                actual_sources = _top_sources(
                    bundle.ranked_candidates,
                    limit=self._top_k,
                )
            except KnowledgeContextNotFoundError:
                actual_sources = ()

            first_relevant_rank = next(
                (
                    rank
                    for rank, source in enumerate(actual_sources, start=1)
                    if _evaluation_url(source.url)
                    in {_evaluation_url(url) for url in case.expected_urls}
                ),
                None,
            )
            results.append(
                EvaluationCaseResult(
                    id=case.id,
                    category=case.category,
                    question=case.question,
                    expected_urls=case.expected_urls,
                    actual_sources=actual_sources,
                    first_relevant_rank=first_relevant_rank,
                    hit=first_relevant_rank is not None,
                )
            )

        frozen_results = tuple(results)
        case_count = len(frozen_results)
        recall_at_5 = round(
            sum(result.hit for result in frozen_results) / case_count,
            4,
        )
        mrr = round(
            sum(
                1 / result.first_relevant_rank if result.first_relevant_rank is not None else 0
                for result in frozen_results
            )
            / case_count,
            4,
        )
        failures = tuple(result for result in frozen_results if not result.hit)
        return KnowledgeEvaluationResult(
            case_count=case_count,
            top_k=self._top_k,
            minimum_recall=self._minimum_recall,
            recall_at_5=recall_at_5,
            mrr=mrr,
            passed=recall_at_5 >= self._minimum_recall,
            results=frozen_results,
            failures=failures,
        )


def _top_sources(
    candidates: Sequence[RankedKnowledgeChunk],
    *,
    limit: int,
) -> tuple[RetrievedSource, ...]:
    sources = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.source_key in seen:
            continue
        seen.add(candidate.source_key)
        sources.append(
            RetrievedSource(
                source_key=candidate.source_key,
                url=candidate.canonical_url,
            )
        )
        if len(sources) >= limit:
            break
    return tuple(sources)


def _format_validation_error(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)


def _evaluation_url(value: str) -> str:
    evaluation_url = _validate_evaluation_url(value)
    parsed = urlsplit(evaluation_url)
    path = parsed.path
    if parsed.hostname == "docs.databricks.com":
        if path == "/aws/en":
            path = "/"
        elif path.startswith("/aws/en/"):
            path = path.removeprefix("/aws/en")
    path = path.rstrip("/") or "/"
    return urlunsplit(("https", parsed.hostname or "", path, "", ""))
