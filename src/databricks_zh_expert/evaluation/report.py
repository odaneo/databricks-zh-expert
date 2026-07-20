from dataclasses import dataclass
from pathlib import Path

from databricks_zh_expert.evaluation.types import EvaluationCaseResult, EvaluationRunResult
from databricks_zh_expert.llm.model_registry import ModelAlias


class EvaluationReportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RunReportPaths:
    result_path: Path
    report_path: Path


def write_run_report(
    result: EvaluationRunResult,
    *,
    output_root: Path,
) -> RunReportPaths:
    model_directory = output_root / result.run_id / result.model.value
    model_directory.mkdir(parents=True, exist_ok=True)
    result_path = model_directory / "result.json"
    report_path = model_directory / "report.md"
    _write_text_atomic(result_path, result.model_dump_json(indent=2) + "\n")
    _write_text_atomic(report_path, _render_run_report(result))
    return RunReportPaths(result_path=result_path, report_path=report_path)


def write_comparison_report(run_id: str, *, output_root: Path) -> Path:
    results = (
        _load_result(output_root / run_id / ModelAlias.DEEPSEEK_V4_FLASH.value / "result.json"),
        _load_result(output_root / run_id / ModelAlias.DEEPSEEK_V4_PRO.value / "result.json"),
    )
    _validate_comparable(run_id, results)
    path = output_root / run_id / "comparison.md"
    _write_text_atomic(path, _render_comparison(results))
    return path


def _load_result(path: Path) -> EvaluationRunResult:
    try:
        return EvaluationRunResult.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvaluationReportError(f"评估结果不存在：{path.as_posix()}。") from error
    except ValueError as error:
        raise EvaluationReportError(f"评估结果格式无效：{path.as_posix()}。") from error


def _validate_comparable(
    run_id: str,
    results: tuple[EvaluationRunResult, EvaluationRunResult],
) -> None:
    first, second = results
    if first.run_id != run_id or second.run_id != run_id:
        raise EvaluationReportError("评估结果的 Run ID 不一致。")
    if (
        first.dataset_id,
        first.dataset_version,
        first.dataset_hash,
        first.workspace_id,
        first.workspace_version,
        first.workspace_source_hash,
    ) != (
        second.dataset_id,
        second.dataset_version,
        second.dataset_hash,
        second.workspace_id,
        second.workspace_version,
        second.workspace_source_hash,
    ):
        raise EvaluationReportError("两个模型的评估基线不一致。")
    if tuple(case.case_id for case in first.cases) != tuple(case.case_id for case in second.cases):
        raise EvaluationReportError("两个模型的评估 Case 不一致。")


def _render_run_report(result: EvaluationRunResult) -> str:
    status = "通过" if result.automated_passed else "未通过"
    lines = [
        "# 阶段 9 端到端评估报告",
        "",
        "## 运行信息",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- 模型：`{result.model.value}`",
        f"- 数据集：`{result.dataset_id}` `{result.dataset_version}`",
        f"- 数据集 Hash：`{result.dataset_hash}`",
        f"- Workspace：`{result.workspace_id}` `{result.workspace_version}`",
        f"- Workspace Source Hash：`{result.workspace_source_hash}`",
        f"- 自动门禁：**{status}**",
        "",
        "## 汇总",
        "",
        "| Case | 通过 | 失败 | Fallback | Hard Pass | Soft 平均 | "
        "Prompt Token | Completion Token | 延迟 ms |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {result.summary.case_count} | {result.summary.passed_count} | "
            f"{result.summary.failed_count} | {result.summary.fallback_count} | "
            f"{_percent(result.summary.hard_pass_rate)} | "
            f"{_percent(result.summary.average_soft_score)} | "
            f"{result.summary.prompt_tokens} | {result.summary.completion_tokens} | "
            f"{result.summary.latency_ms} |"
        ),
        "",
        "## Case 结果",
        "",
        "| Case | Prompt | 自动门禁 | Hard | Soft | 引用 | Session |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | `{case.prompt.value}` | "
            f"{'通过' if case.automated_passed else '未通过'} | "
            f"{'通过' if case.hard_passed else '未通过'} | {_percent(case.soft_score)} | "
            f"{len(case.citation_urls)} | `{case.session_id or 'n/a'}` |"
        )

    failed_cases = tuple(case for case in result.cases if not case.automated_passed)
    lines.extend(("", "## 失败定位", ""))
    if not failed_cases:
        lines.append("无自动门禁失败 Case。")
    for case in failed_cases:
        lines.extend((f"### `{case.case_id}`", ""))
        if case.error_code or case.error_message:
            lines.append(f"- API/模型错误：`{case.error_code}` {case.error_message or ''}")
        for rule in (*case.hard_rules, *case.soft_rules):
            if not rule.passed:
                lines.append(f"- `{rule.rule_id}`：期望 {rule.expected}；实际 {rule.actual}")

    manual_cases = tuple(case for case in result.cases if case.manual_review.required)
    lines.extend(("", "## 人工抽查", ""))
    if not manual_cases:
        lines.append("本次筛选运行不包含人工抽查 Case。")
    for case in manual_cases:
        lines.extend(
            (
                f"### `{case.case_id}`",
                "",
                f"- 状态：`{case.manual_review.status.value}`",
                f"- Session：`{case.session_id or 'n/a'}`",
                f"- ModelCall：{', '.join(f'`{item}`' for item in case.model_call_ids) or '无'}",
            )
        )
        lines.extend(f"- [ ] {question}" for question in case.manual_review.questions)
        lines.extend(("", "#### 模型输出", "", case.assistant_content or "（无输出）", ""))
    return "\n".join(lines).rstrip() + "\n"


def _render_comparison(
    results: tuple[EvaluationRunResult, EvaluationRunResult],
) -> str:
    first = results[0]
    lines = [
        "# 阶段 9 模型对比报告",
        "",
        f"- Run ID：`{first.run_id}`",
        f"- 数据集：`{first.dataset_id}` `{first.dataset_version}`",
        f"- 数据集 Hash：`{first.dataset_hash}`",
        f"- Workspace Source Hash：`{first.workspace_source_hash}`",
        "",
        "## 模型汇总",
        "",
        "| 模型 | 自动门禁 | Hard Pass | Soft 平均 | 失败 | Fallback | Token | 延迟 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        token_count = result.summary.prompt_tokens + result.summary.completion_tokens
        lines.append(
            f"| `{result.model.value}` | {'通过' if result.automated_passed else '未通过'} | "
            f"{_percent(result.summary.hard_pass_rate)} | "
            f"{_percent(result.summary.average_soft_score)} | "
            f"{result.summary.failed_count} | {result.summary.fallback_count} | "
            f"{token_count} | {result.summary.latency_ms} |"
        )

    lines.extend(("", "## Case 对比", "", "| Case | Flash | Pro |", "| --- | --- | --- |"))
    first_by_id = {case.case_id: case for case in results[0].cases}
    second_by_id = {case.case_id: case for case in results[1].cases}
    for case_id in first_by_id:
        lines.append(
            f"| `{case_id}` | "
            f"{_case_outcome(first_by_id[case_id])} | "
            f"{_case_outcome(second_by_id[case_id])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _case_outcome(case: EvaluationCaseResult) -> str:
    failed_hard_rules = tuple(rule.rule_id for rule in case.hard_rules if not rule.passed)
    if failed_hard_rules:
        return "Hard：" + "、".join(f"`{rule_id}`" for rule_id in failed_hard_rules)
    failed_soft_rules = tuple(rule.expected for rule in case.soft_rules if not rule.passed)
    if case.soft_score < case.soft_minimum:
        return "Soft：" + "、".join(f"`{term}`" for term in failed_soft_rules)
    return "通过"


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _percent(value: float) -> str:
    return f"{value:.2%}"
