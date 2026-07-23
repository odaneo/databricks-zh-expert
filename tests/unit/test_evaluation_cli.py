from datetime import UTC, datetime
from pathlib import Path

import pytest

from databricks_zh_expert.evaluation.cli import EvaluationCliRuntime, run
from databricks_zh_expert.evaluation.types import EvaluationRunResult, EvaluationRunSummary
from databricks_zh_expert.llm.model_registry import ModelAlias


class FakeRuntime:
    def __init__(self, result: EvaluationRunResult | None = None) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    async def validate(self) -> dict[str, object]:
        self.calls.append(("validate",))
        return {"passed": True, "dataset_hash": "a" * 64}

    async def run_evaluation(
        self,
        *,
        run_id: str,
        model: ModelAlias,
        case_id: str | None,
    ) -> tuple[EvaluationRunResult, Path]:
        self.calls.append(("run", run_id, model, case_id))
        assert self.result is not None
        return self.result, Path("result.json")

    def compare(self, *, run_id: str) -> Path:
        self.calls.append(("compare", run_id))
        return Path("comparison.md")

    def compare_longitudinal(
        self,
        *,
        baseline_run_id: str,
        current_run_id: str,
    ) -> Path:
        self.calls.append(("longitudinal", baseline_run_id, current_run_id))
        return Path("longitudinal.md")


@pytest.mark.asyncio
async def test_cli_validate_does_not_run_models(capsys) -> None:
    runtime = FakeRuntime()

    exit_code = await run(("validate",), runtime)

    assert exit_code == 0
    assert runtime.calls == [("validate",)]
    assert '"passed": true' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_run_passes_model_case_and_uses_gate_exit_code(
    capsys,
    evaluation_run_result: EvaluationRunResult,
) -> None:
    runtime = FakeRuntime(evaluation_run_result)

    exit_code = await run(
        (
            "run",
            "--run-id",
            "stage9-debug",
            "--model",
            "deepseek-v4-flash",
            "--case",
            "nw_sql_daily_sales",
        ),
        runtime,
    )

    assert exit_code == 0
    assert runtime.calls == [
        (
            "run",
            "stage9-debug",
            ModelAlias.DEEPSEEK_V4_FLASH,
            "nw_sql_daily_sales",
        )
    ]
    assert "result.json" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_compare_reads_completed_results_only(capsys) -> None:
    runtime = FakeRuntime()

    exit_code = await run(("compare", "--run-id", "stage9-baseline"), runtime)

    assert exit_code == 0
    assert runtime.calls == [("compare", "stage9-baseline")]
    assert "comparison.md" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_longitudinal_compares_two_completed_runs(capsys) -> None:
    runtime = FakeRuntime()

    exit_code = await run(
        (
            "longitudinal",
            "--baseline-run-id",
            "stage9-baseline",
            "--current-run-id",
            "stage10-baseline",
        ),
        runtime,
    )

    assert exit_code == 0
    assert runtime.calls == [("longitudinal", "stage9-baseline", "stage10-baseline")]
    assert "longitudinal.md" in capsys.readouterr().out


def test_runtime_protocol_accepts_fake_runtime() -> None:
    runtime: EvaluationCliRuntime = FakeRuntime()

    assert runtime is not None


@pytest.fixture
def evaluation_run_result() -> EvaluationRunResult:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    return EvaluationRunResult(
        run_id="stage9-debug",
        dataset_id="stage9_northwind_end_to_end",
        dataset_version="1.0.0",
        dataset_hash="a" * 64,
        model=ModelAlias.DEEPSEEK_V4_FLASH,
        workspace_id="northwind_psql",
        workspace_version="1.0.0",
        workspace_source_hash="b" * 64,
        started_at=now,
        completed_at=now,
        automated_passed=True,
        summary=EvaluationRunSummary(
            case_count=0,
            passed_count=0,
            failed_count=0,
            fallback_count=0,
            hard_pass_rate=0,
            average_soft_score=0,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
        ),
        cases=(),
    )
