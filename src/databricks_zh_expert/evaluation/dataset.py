import hashlib
import json
import re
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from databricks_zh_expert.evaluation.types import (
    EvaluationCase,
    EvaluationCaseGroup,
    EvaluationDataset,
)
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PROMPT_SPECS

END_TO_END_EVALUATION_PATH = Path("tests/evals/end_to_end.yml")
_EVALUATION_MODELS = (
    ModelAlias.DEEPSEEK_V4_FLASH,
    ModelAlias.DEEPSEEK_V4_PRO,
)
_MANUAL_CASE_IDS = frozenset(
    {
        "nw_sql_daily_sales",
        "nw_pyspark_order_cleaning",
        "nw_workflow_daily_sales",
    }
)


class EvaluationDatasetError(ValueError):
    pass


class _DatasetSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: int
    dataset_id: str
    version: str
    workspace_id: str
    expert_profile: str
    models: tuple[ModelAlias, ...]
    cases: tuple[EvaluationCase, ...] = Field(min_length=16, max_length=16)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        case_ids = tuple(case.id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case id 不能重复。")
        if self.models != _EVALUATION_MODELS:
            raise ValueError("端到端评估只允许固定的两个 DeepSeek 模型。")

        northwind_count = sum(case.group is EvaluationCaseGroup.NORTHWIND for case in self.cases)
        if northwind_count != 12:
            raise ValueError("端到端评估必须包含 12 道 Northwind 题和 4 道通用题。")
        manual_case_ids = frozenset(case.id for case in self.cases if case.manual_review.required)
        if manual_case_ids != _MANUAL_CASE_IDS:
            raise ValueError("人工抽查 Case 必须固定为 SQL、PySpark 和 Workflow。")

        prompt_specs = {spec.name: spec for spec in PROMPT_SPECS}
        for case in self.cases:
            spec = prompt_specs[case.prompt]
            if case.expected.artifact_type is not spec.artifact_type:
                raise ValueError(f"Prompt 与 Artifact 类型不一致：{case.id}。")
            if case.expected.project_fact_status != spec.project_fact_status:
                raise ValueError(f"project_fact_status 与 Prompt 不一致：{case.id}。")
            if case.expected.code_fence_language != spec.code_fence_language:
                raise ValueError(f"代码围栏与 Prompt 不一致：{case.id}。")
            if case.expected.required_sections != spec.required_sections:
                raise ValueError(f"Markdown 章节与 Prompt 不一致：{case.id}。")
            if case.expected.require_official_citations != spec.use_official_knowledge:
                raise ValueError(f"官方引用要求与 Prompt 不一致：{case.id}。")
            expected_workspace = case.group is EvaluationCaseGroup.NORTHWIND
            if case.expected.require_workspace_context != expected_workspace:
                raise ValueError(f"Workspace Context 要求与 Case 分组不一致：{case.id}。")
            if expected_workspace != spec.use_workspace_context:
                raise ValueError(f"Case 分组与 Prompt 的 Workspace 能力不一致：{case.id}。")
            if expected_workspace and not case.expected.workspace_unit_ids:
                raise ValueError(f"Northwind Case 必须固定预期 Workspace 单元：{case.id}。")
            if not expected_workspace and case.expected.workspace_unit_ids:
                raise ValueError(f"通用 Case 不能依赖 Workspace 单元：{case.id}。")
            for pattern in (
                *case.expected.required_patterns,
                *case.expected.forbidden_patterns,
            ):
                try:
                    re.compile(pattern)
                except re.error:
                    raise ValueError(f"正则表达式无效：{case.id}。") from None
        return self


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvaluationDatasetError("无法读取端到端评估集。") from error
    except YAMLError as error:
        raise EvaluationDatasetError("端到端评估集不是合法 YAML。") from error

    try:
        source = _DatasetSourceModel.model_validate(payload)
    except ValidationError as error:
        if any(item["type"] == "extra_forbidden" for item in error.errors()):
            raise EvaluationDatasetError("端到端评估集包含未知字段。") from None
        detail_items: list[str] = []
        for item in error.errors(include_url=False, include_input=False):
            context = item.get("ctx")
            context_error = context.get("error") if context is not None else None
            detail_items.append(str(context_error) if context_error is not None else item["msg"])
        details = "; ".join(detail_items)
        raise EvaluationDatasetError(f"端到端评估集无效：{details}") from None

    canonical = json.dumps(
        source.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return EvaluationDataset(
        **source.model_dump(),
        source_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
