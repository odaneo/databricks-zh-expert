import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from databricks_zh_expert.evaluation.types import EvaluationCaseResult, EvaluationRunResult
from databricks_zh_expert.llm.model_registry import ModelAlias


class EvaluationReportError(ValueError):
    pass


_RUN_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


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
    results = _load_run_results(run_id, output_root=output_root)
    path = output_root / run_id / "comparison.md"
    _write_text_atomic(path, _render_comparison(results))
    return path


def write_longitudinal_comparison_report(
    baseline_run_id: str,
    current_run_id: str,
    *,
    output_root: Path,
) -> Path:
    baseline = _load_run_results(baseline_run_id, output_root=output_root)
    current = _load_run_results(current_run_id, output_root=output_root)
    if baseline[0].workspace_id != current[0].workspace_id:
        raise EvaluationReportError("纵向比较的 Workspace ID 不一致。")
    path = output_root / current_run_id / f"longitudinal-vs-{baseline_run_id}.md"
    _write_text_atomic(path, _render_longitudinal_comparison(baseline, current))
    return path


def _load_run_results(
    run_id: str,
    *,
    output_root: Path,
) -> tuple[EvaluationRunResult, EvaluationRunResult]:
    _validate_report_run_id(run_id)
    results = (
        _load_result(output_root / run_id / ModelAlias.DEEPSEEK_V4_FLASH.value / "result.json"),
        _load_result(output_root / run_id / ModelAlias.DEEPSEEK_V4_PRO.value / "result.json"),
    )
    _validate_comparable(run_id, results)
    return results


def _validate_report_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise EvaluationReportError(
            "Run ID 只能包含字母、数字、点、下划线和连字符，长度不能超过 100。"
        )


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
        "# 端到端评估报告",
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
        "# 模型横向对比报告",
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


def _render_longitudinal_comparison(
    baseline: tuple[EvaluationRunResult, EvaluationRunResult],
    current: tuple[EvaluationRunResult, EvaluationRunResult],
) -> str:
    baseline_first = baseline[0]
    current_first = current[0]
    lines = [
        "# 端到端评估纵向对比报告",
        "",
        "## 基线信息",
        "",
        "| 项目 | 基线 | 当前 |",
        "| --- | --- | --- |",
        f"| Run ID | `{baseline_first.run_id}` | `{current_first.run_id}` |",
        (
            f"| 数据集 | `{baseline_first.dataset_id}` `{baseline_first.dataset_version}` | "
            f"`{current_first.dataset_id}` `{current_first.dataset_version}` |"
        ),
        (f"| 数据集 Hash | `{baseline_first.dataset_hash}` | `{current_first.dataset_hash}` |"),
        (
            f"| Workspace | `{baseline_first.workspace_id}` "
            f"`{baseline_first.workspace_version}` | `{current_first.workspace_id}` "
            f"`{current_first.workspace_version}` |"
        ),
        (
            f"| Workspace Source Hash | `{baseline_first.workspace_source_hash}` | "
            f"`{current_first.workspace_source_hash}` |"
        ),
        "",
        "## 模型指标变化",
        "",
        "| 模型 | Hard 基线 | Hard 当前 | Hard 变化 | Soft 基线 | Soft 当前 | "
        "Soft 变化 | 失败变化 | Fallback 变化 | Token 变化 | 延迟变化 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for baseline_result, current_result in zip(baseline, current, strict=True):
        if baseline_result.model is not current_result.model:
            raise EvaluationReportError("纵向比较的模型顺序不一致。")
        baseline_summary = baseline_result.summary
        current_summary = current_result.summary
        baseline_tokens = baseline_summary.prompt_tokens + baseline_summary.completion_tokens
        current_tokens = current_summary.prompt_tokens + current_summary.completion_tokens
        hard_pass_delta = current_summary.hard_pass_rate - baseline_summary.hard_pass_rate
        soft_score_delta = current_summary.average_soft_score - baseline_summary.average_soft_score
        failed_delta = current_summary.failed_count - baseline_summary.failed_count
        fallback_delta = current_summary.fallback_count - baseline_summary.fallback_count
        latency_delta = current_summary.latency_ms - baseline_summary.latency_ms
        lines.append(
            f"| `{baseline_result.model.value}` | "
            f"{_percent(baseline_summary.hard_pass_rate)} | "
            f"{_percent(current_summary.hard_pass_rate)} | "
            f"{_signed_percent(hard_pass_delta)} | "
            f"{_percent(baseline_summary.average_soft_score)} | "
            f"{_percent(current_summary.average_soft_score)} | "
            f"{_signed_percent(soft_score_delta)} | "
            f"{_signed_integer(failed_delta)} | "
            f"{_signed_integer(fallback_delta)} | "
            f"{_signed_integer(current_tokens - baseline_tokens)} | "
            f"{_signed_integer(latency_delta)} |"
        )

    baseline_case_ids = tuple(case.case_id for case in baseline_first.cases)
    current_case_ids = tuple(case.case_id for case in current_first.cases)
    baseline_case_set = set(baseline_case_ids)
    current_case_set = set(current_case_ids)
    common_case_ids = tuple(case_id for case_id in current_case_ids if case_id in baseline_case_set)
    added_case_ids = tuple(
        case_id for case_id in current_case_ids if case_id not in baseline_case_set
    )
    removed_case_ids = tuple(
        case_id for case_id in baseline_case_ids if case_id not in current_case_set
    )

    lines.extend(
        (
            "",
            "## Case 变化",
            "",
            f"- 共同 Case：{len(common_case_ids)}",
            f"- 新增 Case：{_render_case_ids(added_case_ids)}",
            f"- 移除 Case：{_render_case_ids(removed_case_ids)}",
            "",
            "| 模型 | Case | 基线 | 当前 |",
            "| --- | --- | --- | --- |",
        )
    )
    for baseline_result, current_result in zip(baseline, current, strict=True):
        baseline_by_id = {case.case_id: case for case in baseline_result.cases}
        current_by_id = {case.case_id: case for case in current_result.cases}
        for case_id in common_case_ids:
            lines.append(
                f"| `{current_result.model.value}` | `{case_id}` | "
                f"{_case_outcome(baseline_by_id[case_id])} | "
                f"{_case_outcome(current_by_id[case_id])} |"
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


def _signed_percent(value: float) -> str:
    return f"{value:+.2%}"


def _signed_integer(value: int) -> str:
    return f"{value:+d}"


def _render_case_ids(case_ids: tuple[str, ...]) -> str:
    return "、".join(f"`{case_id}`" for case_id in case_ids) or "无"
