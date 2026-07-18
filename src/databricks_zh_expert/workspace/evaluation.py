from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.registry import WorkspaceRegistry, WorkspaceRegistryError
from databricks_zh_expert.workspace.types import WorkspaceContextPurpose

WORKSPACE_EVALUATION_PATH = Path("tests/evals/workspace_context.yml")
WORKSPACE_EVALUATION_TOP_K = 5
WORKSPACE_MINIMUM_RECALL = 0.90

StableId = Annotated[
    str,
    Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
]
UnitId = Annotated[
    str,
    Field(min_length=3, max_length=200, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]
ForbiddenTerm = Annotated[str, Field(min_length=1, max_length=100)]

_WORKSPACE_PROMPTS = frozenset(PromptName(item.value) for item in WorkspaceContextPurpose)


class WorkspaceEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluationCase:
    id: str
    prompt: PromptName
    query: str
    expected_unit_ids: tuple[str, ...]
    forbidden_context_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluationDataset:
    version: int
    workspace_id: str
    cases: tuple[WorkspaceEvaluationCase, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluationCaseResult:
    id: str
    prompt: PromptName
    query: str
    expected_unit_ids: tuple[str, ...]
    actual_unit_ids: tuple[str, ...]
    matched_unit_ids: tuple[str, ...]
    missing_unit_ids: tuple[str, ...]
    forbidden_context_terms_found: tuple[str, ...]
    hit: bool


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluationResult:
    query_count: int
    expected_unit_count: int
    matched_unit_count: int
    recall_at_5: float
    context_leak_count: int
    passed: bool
    results: tuple[WorkspaceEvaluationCaseResult, ...]
    failures: tuple[WorkspaceEvaluationCaseResult, ...]


class WorkspaceEvaluationRunner(Protocol):
    def evaluate_file(self, path: Path) -> WorkspaceEvaluationResult: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _EvaluationCaseModel(_StrictModel):
    id: StableId
    prompt: PromptName
    query: str = Field(min_length=5, max_length=1_000)
    expected_unit_ids: tuple[UnitId, ...] = Field(min_length=1, max_length=5)
    forbidden_context_terms: tuple[ForbiddenTerm, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.prompt not in _WORKSPACE_PROMPTS:
            raise ValueError("Workspace 评估题必须使用五类提案 Prompt。")
        if len(self.expected_unit_ids) != len(set(self.expected_unit_ids)):
            raise ValueError("评估题不能包含重复 expected_unit_ids。")
        normalized_terms = tuple(term.casefold() for term in self.forbidden_context_terms)
        if len(normalized_terms) != len(set(normalized_terms)):
            raise ValueError("评估题不能包含重复 forbidden_context_terms。")
        return self


class _EvaluationDatasetModel(_StrictModel):
    version: int = Field(ge=1, le=1)
    workspace_id: StableId
    cases: tuple[_EvaluationCaseModel, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        case_ids = tuple(case.id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Workspace 评估集 case id 不能重复。")
        return self


def load_workspace_evaluation_set(path: Path) -> WorkspaceEvaluationDataset:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise WorkspaceEvaluationError("无法读取 Workspace 评估集。") from error
    except YAMLError as error:
        raise WorkspaceEvaluationError("Workspace 评估集不是合法 YAML。") from error

    try:
        model = _EvaluationDatasetModel.model_validate(payload)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise WorkspaceEvaluationError(f"Workspace 评估集无效：{details}") from None

    return WorkspaceEvaluationDataset(
        version=model.version,
        workspace_id=model.workspace_id,
        cases=tuple(
            WorkspaceEvaluationCase(
                id=case.id,
                prompt=case.prompt,
                query=case.query,
                expected_unit_ids=case.expected_unit_ids,
                forbidden_context_terms=case.forbidden_context_terms,
            )
            for case in model.cases
        ),
    )


class WorkspaceEvaluator:
    def __init__(
        self,
        *,
        registry: WorkspaceRegistry,
        context_builder: WorkspaceContextBuilder,
        top_k: int = WORKSPACE_EVALUATION_TOP_K,
        minimum_recall: float = WORKSPACE_MINIMUM_RECALL,
    ) -> None:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("Workspace 评估 top-k 必须是正整数。")
        if (
            isinstance(minimum_recall, bool)
            or not isinstance(minimum_recall, int | float)
            or not 0 <= minimum_recall <= 1
        ):
            raise ValueError("Workspace 评估最低 Recall 必须在 0 到 1 之间。")
        self._registry = registry
        self._context_builder = context_builder
        self._top_k = top_k
        self._minimum_recall = float(minimum_recall)

    def evaluate_file(self, path: Path) -> WorkspaceEvaluationResult:
        return self.evaluate(load_workspace_evaluation_set(path))

    def evaluate(self, dataset: WorkspaceEvaluationDataset) -> WorkspaceEvaluationResult:
        if not dataset.cases:
            raise WorkspaceEvaluationError("Workspace 评估集不能为空。")
        try:
            workspace = self._registry.get(dataset.workspace_id)
        except WorkspaceRegistryError:
            raise WorkspaceEvaluationError("Workspace 评估集引用了未注册工作区。") from None

        results = []
        for case in dataset.cases:
            bundle = self._context_builder.build_for_prompt(
                case.query,
                workspace=workspace,
                prompt_name=case.prompt.value,
            )
            if bundle is None:
                raise WorkspaceEvaluationError("Workspace 评估题使用了非提案 Prompt。")
            actual_unit_ids = tuple(
                selection.unit_id for selection in bundle.selected_units[: self._top_k]
            )
            actual_id_set = frozenset(actual_unit_ids)
            matched_unit_ids = tuple(
                unit_id for unit_id in case.expected_unit_ids if unit_id in actual_id_set
            )
            missing_unit_ids = tuple(
                unit_id for unit_id in case.expected_unit_ids if unit_id not in actual_id_set
            )
            normalized_context = bundle.context.casefold()
            forbidden_terms_found = tuple(
                term
                for term in case.forbidden_context_terms
                if term.casefold() in normalized_context
            )
            results.append(
                WorkspaceEvaluationCaseResult(
                    id=case.id,
                    prompt=case.prompt,
                    query=case.query,
                    expected_unit_ids=case.expected_unit_ids,
                    actual_unit_ids=actual_unit_ids,
                    matched_unit_ids=matched_unit_ids,
                    missing_unit_ids=missing_unit_ids,
                    forbidden_context_terms_found=forbidden_terms_found,
                    hit=not missing_unit_ids and not forbidden_terms_found,
                )
            )

        frozen_results = tuple(results)
        expected_unit_count = sum(len(result.expected_unit_ids) for result in frozen_results)
        matched_unit_count = sum(len(result.matched_unit_ids) for result in frozen_results)
        context_leak_count = sum(bool(result.forbidden_context_terms_found) for result in results)
        recall_at_5 = round(matched_unit_count / expected_unit_count, 4)
        failures = tuple(result for result in frozen_results if not result.hit)
        return WorkspaceEvaluationResult(
            query_count=len(frozen_results),
            expected_unit_count=expected_unit_count,
            matched_unit_count=matched_unit_count,
            recall_at_5=recall_at_5,
            context_leak_count=context_leak_count,
            passed=recall_at_5 >= self._minimum_recall and context_leak_count == 0,
            results=frozen_results,
            failures=failures,
        )


def _format_validation_error(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)
