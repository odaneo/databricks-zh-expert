from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.evaluation.dataset import (
    END_TO_END_EVALUATION_PATH,
    EvaluationDatasetError,
    load_evaluation_dataset,
)
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName


def _payload() -> dict[str, object]:
    return yaml.safe_load(END_TO_END_EVALUATION_PATH.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "evaluation.yml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_fixed_dataset_has_sixteen_cases_and_two_deepseek_models() -> None:
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)

    assert dataset.schema_version == 2
    assert dataset.dataset_id == "stage10_northwind_end_to_end"
    assert dataset.version == "2.0.0"
    assert dataset.workspace_id == "northwind_psql"
    assert dataset.workspace_version == "2.0.0"
    assert dataset.workspace_source_hash == (
        "3dfa0751cf9ef2aa26d8b7d7728d4b60e4bcc394420544ba2df55d4a6cf6b3fb"
    )
    assert dataset.expert_profile == "generic"
    assert dataset.models == (
        ModelAlias.DEEPSEEK_V4_FLASH,
        ModelAlias.DEEPSEEK_V4_PRO,
    )
    assert len(dataset.cases) == 16
    assert len({case.id for case in dataset.cases}) == 16
    assert sum(case.group.value == "northwind" for case in dataset.cases) == 12
    assert sum(case.group.value == "generic" for case in dataset.cases) == 4
    assert {case.id for case in dataset.cases if case.manual_review.required} == {
        "nw_sql_daily_sales",
        "nw_pyspark_order_cleaning",
        "nw_workflow_daily_sales",
    }
    assert len(dataset.source_hash) == 64


def test_fixed_dataset_prompt_and_artifact_contracts_match_registry() -> None:
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
    by_id = {case.id: case for case in dataset.cases}

    assert by_id["nw_sql_daily_sales"].prompt is PromptName.SQL_GENERATION
    assert by_id["nw_sql_daily_sales"].expected.artifact_type is ArtifactType.SQL
    assert by_id["nw_mapping_order_sales"].expected.artifact_type is ArtifactType.CSV
    assert by_id["nw_workflow_daily_sales"].expected.project_fact_status == "proposal"
    assert by_id["generic_unity_catalog"].expected.require_official_citations is True
    assert by_id["generic_self_check"].expected.require_workspace_context is False
    assert by_id["nw_notebook_sales_quality"].soft_checks.suggested_terms == (
        "隔离",
        "质量结果",
        "_dms_change_seq",
    )
    assert by_id["nw_workflow_daily_sales"].soft_checks.suggested_terms[0] == "Task ID"
    assert by_id["nw_workflow_customer_product"].soft_checks.suggested_terms[-1] == "质量门禁"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"unknown": True}), "未知字段"),
        (
            lambda payload: payload["cases"].__setitem__(
                1,
                deepcopy(payload["cases"][0]),
            ),
            "case id 不能重复",
        ),
        (
            lambda payload: payload["cases"][0].update({"prompt": "document_summary"}),
            "Prompt 与 Artifact 类型不一致",
        ),
        (
            lambda payload: payload.update({"models": ["gpt5.5", "deepseek-v4-pro"]}),
            "只允许固定的两个 DeepSeek 模型",
        ),
        (
            lambda payload: payload["cases"][0]["expected"].update({"required_patterns": ["("]}),
            "正则表达式无效",
        ),
        (
            lambda payload: payload.pop("workspace_source_hash"),
            "必须固定 Workspace 版本和 Source Hash",
        ),
    ],
)
def test_loader_rejects_invalid_dataset(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    payload = _payload()
    mutate(payload)

    with pytest.raises(EvaluationDatasetError, match=message):
        load_evaluation_dataset(_write_payload(tmp_path, payload))
