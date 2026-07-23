from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName


class EvaluationCaseGroup(StrEnum):
    NORTHWIND = "northwind"
    GENERIC = "generic"


class EvaluationRuleLevel(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class ManualReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_REQUIRED = "not_required"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvaluationExpected(_StrictFrozenModel):
    artifact_type: ArtifactType
    project_fact_status: Literal["proposal"] | None
    require_official_citations: bool
    require_workspace_context: bool
    workspace_unit_ids: tuple[str, ...] = Field(max_length=8)
    required_terms: tuple[str, ...]
    required_any_term_groups: tuple[tuple[str, ...], ...]
    forbidden_terms: tuple[str, ...]
    required_patterns: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]
    code_required_terms: tuple[str, ...]
    code_forbidden_terms: tuple[str, ...]
    required_sections: tuple[str, ...]
    code_fence_language: Literal["sql", "csv", "python"] | None


class EvaluationSoftChecks(_StrictFrozenModel):
    suggested_terms: tuple[str, ...]
    minimum_score: float = Field(ge=0, le=1)


class EvaluationManualReviewSpec(_StrictFrozenModel):
    required: bool
    questions: tuple[str, ...]

    @model_validator(mode="after")
    def validate_questions(self) -> "EvaluationManualReviewSpec":
        if self.required and not self.questions:
            raise ValueError("需要人工检查的 Case 必须提供检查问题。")
        if not self.required and self.questions:
            raise ValueError("不需要人工检查的 Case 不能提供检查问题。")
        return self


class EvaluationCase(_StrictFrozenModel):
    id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=200)
    group: EvaluationCaseGroup
    prompt: PromptName
    content: str = Field(min_length=10, max_length=20_000)
    expected: EvaluationExpected
    soft_checks: EvaluationSoftChecks
    manual_review: EvaluationManualReviewSpec


class EvaluationDataset(_StrictFrozenModel):
    schema_version: Literal[1, 2]
    dataset_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    workspace_id: str = Field(min_length=1, max_length=100)
    expert_profile: str = Field(min_length=1, max_length=100)
    models: tuple[ModelAlias, ...]
    cases: tuple[EvaluationCase, ...]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_version: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$",
    )
    workspace_source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_workspace_baseline(self) -> "EvaluationDataset":
        if self.schema_version == 2 and (
            self.workspace_version is None or self.workspace_source_hash is None
        ):
            raise ValueError("端到端评估 v2 必须固定 Workspace 版本和 Source Hash。")
        return self


class EvaluationEvidence(_StrictFrozenModel):
    http_status: int = Field(ge=100, le=599)
    requested_model: ModelAlias
    used_model: ModelAlias | None
    fallback_used: bool
    attempt_count: int = Field(ge=0)
    prompt_name: PromptName | None
    prompt_version: str | None
    artifact_type: ArtifactType | None
    project_fact_status: Literal["proposal"] | None
    assistant_content: str
    citation_urls: tuple[str, ...]
    model_call_ids: tuple[UUID, ...]
    trace_model_call_ids: tuple[UUID, ...]
    model_call_success: bool
    artifact_valid: bool | None
    workspace_id: str | None
    workspace_version: str | None
    workspace_source_hash: str | None
    workspace_unit_ids: tuple[str, ...]
    workspace_source_paths: tuple[str, ...]
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    error_code: str | None
    error_message: str | None
    session_id: UUID | None = None


class EvaluationRuleResult(_StrictFrozenModel):
    rule_id: str
    level: EvaluationRuleLevel
    passed: bool
    expected: str
    actual: str


class EvaluationManualReviewResult(_StrictFrozenModel):
    required: bool
    status: ManualReviewStatus
    questions: tuple[str, ...]


class EvaluationCaseResult(_StrictFrozenModel):
    case_id: str
    title: str
    group: EvaluationCaseGroup
    prompt: PromptName
    model: ModelAlias
    session_id: UUID | None
    prompt_version: str | None
    assistant_content: str
    citation_urls: tuple[str, ...]
    model_call_ids: tuple[UUID, ...]
    fallback_used: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    hard_rules: tuple[EvaluationRuleResult, ...]
    soft_rules: tuple[EvaluationRuleResult, ...]
    hard_passed: bool
    soft_score: float
    soft_minimum: float
    automated_passed: bool
    manual_review: EvaluationManualReviewResult
    error_code: str | None
    error_message: str | None


class EvaluationRunSummary(_StrictFrozenModel):
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    hard_pass_rate: float = Field(ge=0, le=1)
    average_soft_score: float = Field(ge=0, le=1)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class EvaluationRunResult(_StrictFrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    model: ModelAlias
    workspace_id: str
    workspace_version: str
    workspace_source_hash: str
    started_at: datetime
    completed_at: datetime
    automated_passed: bool
    summary: EvaluationRunSummary
    cases: tuple[EvaluationCaseResult, ...]
