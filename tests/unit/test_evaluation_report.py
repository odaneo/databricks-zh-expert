from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from databricks_zh_expert.evaluation.report import (
    write_comparison_report,
    write_longitudinal_comparison_report,
    write_run_report,
)
from databricks_zh_expert.evaluation.types import (
    EvaluationCaseGroup,
    EvaluationCaseResult,
    EvaluationManualReviewResult,
    EvaluationRuleLevel,
    EvaluationRuleResult,
    EvaluationRunResult,
    EvaluationRunSummary,
    ManualReviewStatus,
)
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName


def _run_result(model: ModelAlias, *, passed: bool = True) -> EvaluationRunResult:
    case = EvaluationCaseResult(
        case_id="nw_sql_daily_sales",
        title="Northwind 每日净销售 SQL",
        group=EvaluationCaseGroup.NORTHWIND,
        prompt=PromptName.SQL_GENERATION,
        model=model,
        session_id=uuid4(),
        prompt_version="1.1.0",
        assistant_content="```sql\nSELECT 1;\n```",
        citation_urls=("https://docs.databricks.com/aws/en/sql/",),
        model_call_ids=(uuid4(),),
        fallback_used=False,
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=500,
        hard_rules=(
            EvaluationRuleResult(
                rule_id="http_created",
                level=EvaluationRuleLevel.HARD,
                passed=passed,
                expected="201",
                actual="201" if passed else "500",
            ),
        ),
        soft_rules=(),
        hard_passed=passed,
        soft_score=1.0,
        soft_minimum=0.9,
        automated_passed=passed,
        manual_review=EvaluationManualReviewResult(
            required=True,
            status=ManualReviewStatus.PENDING,
            questions=("SQL 是否可继续评审？",),
        ),
        error_code=None,
        error_message=None,
    )
    return EvaluationRunResult(
        run_id="stage9-report",
        dataset_id="stage9_northwind_end_to_end",
        dataset_version="1.0.0",
        dataset_hash="a" * 64,
        model=model,
        workspace_id="northwind_psql",
        workspace_version="1.0.0",
        workspace_source_hash="b" * 64,
        started_at=datetime(2026, 7, 20, tzinfo=UTC),
        completed_at=datetime(2026, 7, 20, 0, 1, tzinfo=UTC),
        automated_passed=passed,
        summary=EvaluationRunSummary(
            case_count=1,
            passed_count=int(passed),
            failed_count=int(not passed),
            fallback_count=0,
            hard_pass_rate=float(passed),
            average_soft_score=1.0,
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=500,
        ),
        cases=(case,),
    )


def test_write_run_report_persists_json_summary_and_manual_output(tmp_path: Path) -> None:
    result = _run_result(ModelAlias.DEEPSEEK_V4_FLASH)

    paths = write_run_report(result, output_root=tmp_path)

    assert paths.result_path == (tmp_path / "stage9-report" / "deepseek-v4-flash" / "result.json")
    assert paths.report_path.is_file()
    loaded = EvaluationRunResult.model_validate_json(paths.result_path.read_text(encoding="utf-8"))
    assert loaded == result
    report = paths.report_path.read_text(encoding="utf-8")
    assert "# 端到端评估报告" in report
    assert "nw_sql_daily_sales" in report
    assert "SQL 是否可继续评审？" in report
    assert "SELECT 1" in report
    assert "sk-" not in report


def test_write_comparison_report_compares_two_fixed_models(tmp_path: Path) -> None:
    write_run_report(_run_result(ModelAlias.DEEPSEEK_V4_FLASH), output_root=tmp_path)
    write_run_report(
        _run_result(ModelAlias.DEEPSEEK_V4_PRO, passed=False),
        output_root=tmp_path,
    )

    path = write_comparison_report("stage9-report", output_root=tmp_path)

    content = path.read_text(encoding="utf-8")
    assert path == tmp_path / "stage9-report" / "comparison.md"
    assert "deepseek-v4-flash" in content
    assert "deepseek-v4-pro" in content
    assert "nw_sql_daily_sales" in content
    assert "100.00%" in content
    assert "0.00%" in content
    assert "Hard：`http_created`" in content


def test_write_longitudinal_report_compares_different_frozen_baselines(
    tmp_path: Path,
) -> None:
    baseline_flash = _run_result(ModelAlias.DEEPSEEK_V4_FLASH)
    baseline_pro = _run_result(ModelAlias.DEEPSEEK_V4_PRO, passed=False)
    current_flash = baseline_flash.model_copy(
        update={
            "run_id": "stage10-report",
            "dataset_id": "stage10_northwind_end_to_end",
            "dataset_version": "2.0.0",
            "dataset_hash": "c" * 64,
            "workspace_version": "2.0.0",
            "workspace_source_hash": "d" * 64,
        }
    )
    current_pro = baseline_pro.model_copy(
        update={
            "run_id": "stage10-report",
            "dataset_id": "stage10_northwind_end_to_end",
            "dataset_version": "2.0.0",
            "dataset_hash": "c" * 64,
            "workspace_version": "2.0.0",
            "workspace_source_hash": "d" * 64,
        }
    )
    for result in (baseline_flash, baseline_pro, current_flash, current_pro):
        write_run_report(result, output_root=tmp_path)

    path = write_longitudinal_comparison_report(
        "stage9-report",
        "stage10-report",
        output_root=tmp_path,
    )

    content = path.read_text(encoding="utf-8")
    assert path == tmp_path / "stage10-report" / "longitudinal-vs-stage9-report.md"
    assert "# 端到端评估纵向对比报告" in content
    assert "stage9-report" in content
    assert "stage10-report" in content
    assert "stage9_northwind_end_to_end" in content
    assert "stage10_northwind_end_to_end" in content
    assert "bbbbbbbb" in content
    assert "dddddddd" in content
    assert "deepseek-v4-flash" in content
    assert "deepseek-v4-pro" in content
