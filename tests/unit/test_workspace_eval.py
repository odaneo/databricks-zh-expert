import json
from pathlib import Path

from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.workspace.cli import WorkspaceCliRuntime, run
from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.evaluation import (
    WORKSPACE_EVALUATION_PATH,
    WorkspaceEvaluationCase,
    WorkspaceEvaluationDataset,
    WorkspaceEvaluationResult,
    WorkspaceEvaluator,
    load_workspace_evaluation_set,
)
from databricks_zh_expert.workspace.registry import WorkspaceRegistry


class FakeEvaluationRunner:
    def __init__(self, result: WorkspaceEvaluationResult) -> None:
        self.result = result
        self.paths: list[Path] = []

    def evaluate_file(self, path: Path) -> WorkspaceEvaluationResult:
        self.paths.append(path)
        return self.result


def _case(
    case_id: str,
    query: str,
    *expected_unit_ids: str,
    forbidden_context_terms: tuple[str, ...] = (),
) -> WorkspaceEvaluationCase:
    return WorkspaceEvaluationCase(
        id=case_id,
        prompt=PromptName.DDL_GENERATION,
        query=query,
        expected_unit_ids=expected_unit_ids,
        forbidden_context_terms=forbidden_context_terms,
    )


def test_fixed_workspace_evaluation_set_has_eight_cases_and_ten_expected_units() -> None:
    dataset = load_workspace_evaluation_set(WORKSPACE_EVALUATION_PATH)

    assert dataset.workspace_id == "retail_sales_demo"
    assert len(dataset.cases) == 8
    assert len({case.id for case in dataset.cases}) == 8
    assert sum(len(case.expected_unit_ids) for case in dataset.cases) == 10
    missing_field = next(case for case in dataset.cases if case.id == "missing_source_field")
    assert missing_field.forbidden_context_terms == ("source_system_priority",)


def test_fixed_workspace_evaluation_reaches_recall_gate_without_context_leaks() -> None:
    evaluator = WorkspaceEvaluator(
        registry=WorkspaceRegistry.create_default(),
        context_builder=WorkspaceContextBuilder(),
    )

    result = evaluator.evaluate_file(WORKSPACE_EVALUATION_PATH)

    assert result.query_count == 8
    assert result.expected_unit_count == 10
    assert result.matched_unit_count == 10
    assert result.recall_at_5 == 1.0
    assert result.context_leak_count == 0
    assert result.passed is True
    assert result.failures == ()


def test_evaluator_calculates_unit_recall_and_forbidden_context_terms() -> None:
    dataset = WorkspaceEvaluationDataset(
        version=1,
        workspace_id="retail_sales_demo",
        cases=(
            _case(
                "partial_customer",
                "根据 public.customer 生成 DDL",
                "source_ddl.rds_postgresql.rds-postgresql:1",
                "source_ddl.rds_postgresql.rds-postgresql:99",
                forbidden_context_terms=("CREATE TABLE",),
            ),
            _case(
                "sales_hit",
                "根据 source.pos_sales_line 生成 DDL",
                "source_ddl.pos_parquet.pos-parquet:1",
            ),
        ),
    )
    evaluator = WorkspaceEvaluator(
        registry=WorkspaceRegistry.create_default(),
        context_builder=WorkspaceContextBuilder(),
    )

    result = evaluator.evaluate(dataset)

    assert result.expected_unit_count == 3
    assert result.matched_unit_count == 2
    assert result.recall_at_5 == 0.6667
    assert result.context_leak_count == 1
    assert result.passed is False
    assert {failure.id for failure in result.failures} == {"partial_customer"}


def test_workspace_cli_evaluate_uses_fixed_path_and_quality_exit_code(
    capsys,
) -> None:
    result = WorkspaceEvaluationResult(
        query_count=5,
        expected_unit_count=6,
        matched_unit_count=6,
        recall_at_5=1.0,
        context_leak_count=0,
        passed=True,
        results=(),
        failures=(),
    )
    runner = FakeEvaluationRunner(result)

    exit_code = run(("evaluate",), WorkspaceCliRuntime(evaluator=runner))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["recall_at_5"] == 1.0
    assert runner.paths == [WORKSPACE_EVALUATION_PATH]
