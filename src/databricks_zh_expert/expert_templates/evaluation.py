from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from databricks_zh_expert.expert_templates.context import (
    ExpertTemplateContextNotFoundError,
    ExpertTemplateRetrievalBundle,
    ExpertTemplateSelection,
)
from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.embeddings import EmbeddingResult

EXPERT_TEMPLATE_EVALUATION_PATH = Path("tests/evals/expert_templates.yml")
EXPERT_TEMPLATE_EVALUATION_TOP_K = 3
EXPERT_TEMPLATE_MINIMUM_RECALL = 0.90

StableId = Annotated[
    str,
    Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
]
TemplateId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9](?:[a-z0-9._]*[a-z0-9])?$",
    ),
]


class ExpertTemplateEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExpertTemplateEvaluationCase:
    id: str
    profile: str
    prompt: PromptName
    query: str
    expected_template_ids: tuple[str, ...]
    forbidden_layers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpertTemplateEvaluationDataset:
    version: int
    cases: tuple[ExpertTemplateEvaluationCase, ...]


@dataclass(frozen=True, slots=True)
class ExpertTemplateEvaluationCaseResult:
    id: str
    profile: str
    prompt: PromptName
    query: str
    expected_template_ids: tuple[str, ...]
    actual_template_ids: tuple[str, ...]
    hit: bool
    profile_leak: bool
    inheritance_miss: bool


@dataclass(frozen=True, slots=True)
class ExpertTemplateEvaluationResult:
    query_count: int
    hit_count: int
    recall_at_3: float
    profile_leak_count: int
    inheritance_miss_count: int
    passed: bool
    results: tuple[ExpertTemplateEvaluationCaseResult, ...]
    failures: tuple[ExpertTemplateEvaluationCaseResult, ...]


class ExpertTemplateRetrievalRunner(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        query_embedding: Sequence[float],
        profile_id: str,
        prompt_name: PromptName,
    ) -> ExpertTemplateRetrievalBundle: ...


class QueryEmbeddingClient(Protocol):
    async def embed_query(self, text: str) -> EmbeddingResult: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _EvaluationCaseModel(_StrictModel):
    id: StableId
    profile: StableId
    prompt: PromptName
    query: str = Field(min_length=5, max_length=500)
    expected_template_ids: tuple[TemplateId, ...] = Field(min_length=1, max_length=5)
    forbidden_layers: tuple[StableId, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if len(self.expected_template_ids) != len(set(self.expected_template_ids)):
            raise ValueError("评估题不能包含重复 expected_template_ids。")
        if len(self.forbidden_layers) != len(set(self.forbidden_layers)):
            raise ValueError("评估题不能包含重复 forbidden_layers。")
        if self.profile == "generic" and self.forbidden_layers != ("retail_sales_demo",):
            raise ValueError("generic 评估题必须禁止 retail_sales_demo 层。")
        return self


class _EvaluationDatasetModel(_StrictModel):
    version: int = Field(ge=1, le=1)
    cases: tuple[_EvaluationCaseModel, ...] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        case_ids = tuple(case.id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("专家模板评估集 case id 不能重复。")
        return self


def load_expert_template_evaluation_set(
    path: Path,
) -> ExpertTemplateEvaluationDataset:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ExpertTemplateEvaluationError(f"无法读取专家模板评估集：{path}") from error
    except YAMLError as error:
        raise ExpertTemplateEvaluationError(f"专家模板评估集不是合法 YAML：{path}") from error

    try:
        model = _EvaluationDatasetModel.model_validate(payload)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise ExpertTemplateEvaluationError(f"专家模板评估集无效：{details}") from None

    return ExpertTemplateEvaluationDataset(
        version=model.version,
        cases=tuple(
            ExpertTemplateEvaluationCase(
                id=case.id,
                profile=case.profile,
                prompt=case.prompt,
                query=case.query,
                expected_template_ids=case.expected_template_ids,
                forbidden_layers=case.forbidden_layers,
            )
            for case in model.cases
        ),
    )


class ExpertTemplateEvaluator:
    def __init__(
        self,
        *,
        retriever: ExpertTemplateRetrievalRunner,
        embedding_client: QueryEmbeddingClient,
        top_k: int = EXPERT_TEMPLATE_EVALUATION_TOP_K,
        minimum_recall: float = EXPERT_TEMPLATE_MINIMUM_RECALL,
    ) -> None:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("专家模板评估 top-k 必须是正整数。")
        if (
            isinstance(minimum_recall, bool)
            or not isinstance(minimum_recall, int | float)
            or not 0 <= minimum_recall <= 1
        ):
            raise ValueError("专家模板评估最低 Recall 必须在 0 到 1 之间。")
        self._retriever = retriever
        self._embedding_client = embedding_client
        self._top_k = top_k
        self._minimum_recall = float(minimum_recall)

    async def evaluate_file(self, path: Path) -> ExpertTemplateEvaluationResult:
        return await self.evaluate(load_expert_template_evaluation_set(path))

    async def evaluate(
        self,
        dataset: ExpertTemplateEvaluationDataset,
    ) -> ExpertTemplateEvaluationResult:
        if not dataset.cases:
            raise ExpertTemplateEvaluationError("专家模板评估集不能为空。")

        results = []
        for case in dataset.cases:
            embedding = await self._embedding_client.embed_query(case.query)
            try:
                bundle = await self._retriever.retrieve(
                    case.query,
                    query_embedding=embedding.embedding,
                    profile_id=case.profile,
                    prompt_name=case.prompt,
                )
                selections = bundle.selected_templates
            except ExpertTemplateContextNotFoundError:
                selections = ()
            results.append(_evaluate_case(case, selections, top_k=self._top_k))

        frozen_results = tuple(results)
        query_count = len(frozen_results)
        hit_count = sum(result.hit for result in frozen_results)
        profile_leak_count = sum(result.profile_leak for result in frozen_results)
        inheritance_miss_count = sum(result.inheritance_miss for result in frozen_results)
        recall_at_3 = round(hit_count / query_count, 4)
        failures = tuple(
            result
            for result in frozen_results
            if not result.hit or result.profile_leak or result.inheritance_miss
        )
        return ExpertTemplateEvaluationResult(
            query_count=query_count,
            hit_count=hit_count,
            recall_at_3=recall_at_3,
            profile_leak_count=profile_leak_count,
            inheritance_miss_count=inheritance_miss_count,
            passed=(
                recall_at_3 >= self._minimum_recall
                and profile_leak_count == 0
                and inheritance_miss_count == 0
            ),
            results=frozen_results,
            failures=failures,
        )


def _evaluate_case(
    case: ExpertTemplateEvaluationCase,
    selections: Sequence[ExpertTemplateSelection],
    *,
    top_k: int,
) -> ExpertTemplateEvaluationCaseResult:
    actual_template_ids = tuple(item.template_id for item in selections[:top_k])
    hit = bool(set(actual_template_ids) & set(case.expected_template_ids))
    profile_leak = any(item.layer in case.forbidden_layers for item in selections)
    selected_ids = {item.template_id for item in selections}
    inheritance_miss = any(
        item.extends is not None and item.extends.rsplit("@", maxsplit=1)[0] not in selected_ids
        for item in selections
    )
    return ExpertTemplateEvaluationCaseResult(
        id=case.id,
        profile=case.profile,
        prompt=case.prompt,
        query=case.query,
        expected_template_ids=case.expected_template_ids,
        actual_template_ids=actual_template_ids,
        hit=hit,
        profile_leak=profile_leak,
        inheritance_miss=inheritance_miss,
    )


def _format_validation_error(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)
