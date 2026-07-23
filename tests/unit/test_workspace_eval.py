import json
from dataclasses import replace
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


def test_fixed_workspace_evaluation_set_has_twelve_realistic_northwind_cases() -> None:
    dataset = load_workspace_evaluation_set(WORKSPACE_EVALUATION_PATH)

    assert dataset.version == 2
    assert dataset.workspace_id == "northwind_psql"
    assert dataset.workspace_version == "2.0.0"
    assert dataset.workspace_source_hash == (
        "3dfa0751cf9ef2aa26d8b7d7728d4b60e4bcc394420544ba2df55d4a6cf6b3fb"
    )
    assert len(dataset.cases) == 12
    assert len({case.id for case in dataset.cases}) == 12
    assert sum(len(case.expected_unit_ids) for case in dataset.cases) == 45
    missing_field = next(case for case in dataset.cases if case.id == "missing_orders_store_id")
    assert missing_field.forbidden_context_terms == ("store_id",)


def test_fixed_workspace_evaluation_reaches_recall_gate_without_context_leaks() -> None:
    evaluator = WorkspaceEvaluator(
        registry=WorkspaceRegistry.create_default(),
        context_builder=WorkspaceContextBuilder(),
    )

    result = evaluator.evaluate_file(WORKSPACE_EVALUATION_PATH)

    assert result.query_count == 12
    assert result.expected_unit_count == 45
    assert result.matched_unit_count == 45
    assert result.recall_at_5 == 1.0
    assert result.context_leak_count == 0
    assert result.passed is True
    assert result.failures == ()


def test_default_recall_gate_requires_every_expected_unit() -> None:
    dataset = load_workspace_evaluation_set(WORKSPACE_EVALUATION_PATH)
    first_case = dataset.cases[0]
    degraded = replace(
        dataset,
        cases=(
            replace(
                first_case,
                expected_unit_ids=("source_ddl.northwind.northwind-schema:99",),
            ),
            *dataset.cases[1:],
        ),
    )
    evaluator = WorkspaceEvaluator(
        registry=WorkspaceRegistry.create_default(),
        context_builder=WorkspaceContextBuilder(),
    )

    result = evaluator.evaluate(degraded)

    assert result.recall_at_5 == 0.9762
    assert result.passed is False


def test_evaluator_calculates_unit_recall_and_forbidden_context_terms() -> None:
    dataset = WorkspaceEvaluationDataset(
        version=1,
        workspace_id="northwind_psql",
        cases=(
            _case(
                "partial_customer",
                "根据 customers 生成 DDL",
                "source_ddl.northwind.northwind-schema:4",
                "source_ddl.northwind.northwind-schema:99",
                forbidden_context_terms=("CREATE TABLE",),
            ),
            _case(
                "sales_hit",
                "根据 orders 生成 DDL",
                "source_ddl.northwind.northwind-schema:8",
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


def test_evaluator_rejects_workspace_hash_drift() -> None:
    dataset = load_workspace_evaluation_set(WORKSPACE_EVALUATION_PATH)
    drifted = replace(dataset, workspace_source_hash="0" * 64)
    evaluator = WorkspaceEvaluator(
        registry=WorkspaceRegistry.create_default(),
        context_builder=WorkspaceContextBuilder(),
    )

    try:
        evaluator.evaluate(drifted)
    except ValueError as error:
        assert "Workspace Source Hash" in str(error)
    else:
        raise AssertionError("Workspace Hash 漂移必须阻止评估。")


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
