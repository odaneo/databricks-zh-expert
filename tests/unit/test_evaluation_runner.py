from databricks_zh_expert.evaluation.runner import _run_gate_passed
from databricks_zh_expert.evaluation.types import EvaluationRunSummary


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
