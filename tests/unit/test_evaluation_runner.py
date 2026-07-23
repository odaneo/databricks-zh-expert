from dataclasses import replace

from databricks_zh_expert.evaluation.dataset import (
    END_TO_END_EVALUATION_PATH,
    load_evaluation_dataset,
)
from databricks_zh_expert.evaluation.runner import (
    _run_gate_passed,
    _workspace_baseline_issues,
)
from databricks_zh_expert.evaluation.types import EvaluationRunSummary
from databricks_zh_expert.workspace.registry import WorkspaceRegistry


def _summary(*, hard_pass_rate: float, average_soft_score: float) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        case_count=16,
        passed_count=16 if hard_pass_rate == 1 else 15,
        failed_count=0 if hard_pass_rate == 1 else 1,
        fallback_count=0,
        hard_pass_rate=hard_pass_rate,
        average_soft_score=average_soft_score,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
    )


def test_run_gate_requires_all_hard_rules_and_ninety_percent_soft_average() -> None:
    assert _run_gate_passed(_summary(hard_pass_rate=1.0, average_soft_score=0.9)) is True
    assert _run_gate_passed(_summary(hard_pass_rate=0.9999, average_soft_score=1.0)) is False
    assert _run_gate_passed(_summary(hard_pass_rate=1.0, average_soft_score=0.8999)) is False


def test_workspace_baseline_check_rejects_version_and_source_hash_drift() -> None:
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
    workspace = WorkspaceRegistry.create_default().get(dataset.workspace_id)

    assert _workspace_baseline_issues(dataset, workspace) == ()

    issues = _workspace_baseline_issues(
        dataset,
        replace(workspace, version="9.9.9", source_hash="0" * 64),
    )

    assert issues == (
        "Workspace 版本与固定端到端评估基线不一致。",
        "Workspace Source Hash 与固定端到端评估基线不一致。",
    )
