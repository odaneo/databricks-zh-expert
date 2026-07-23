import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from databricks_zh_expert.core.config import get_settings
from databricks_zh_expert.core.runtime import configure_event_loop_policy
from databricks_zh_expert.evaluation.dataset import (
    END_TO_END_EVALUATION_PATH,
    EvaluationDatasetError,
    load_evaluation_dataset,
)
from databricks_zh_expert.evaluation.report import (
    EvaluationReportError,
    write_comparison_report,
    write_longitudinal_comparison_report,
    write_run_report,
)
from databricks_zh_expert.evaluation.runner import EVALUATION_OUTPUT_ROOT, EvaluationRunner
from databricks_zh_expert.evaluation.types import EvaluationRunResult
from databricks_zh_expert.llm.model_registry import ModelAlias


class EvaluationCliRuntime(Protocol):
    async def validate(self) -> dict[str, object]: ...

    async def run_evaluation(
        self,
        *,
        run_id: str,
        model: ModelAlias,
        case_id: str | None,
    ) -> tuple[EvaluationRunResult, Path]: ...

    def compare(self, *, run_id: str) -> Path: ...

    def compare_longitudinal(
        self,
        *,
        baseline_run_id: str,
        current_run_id: str,
    ) -> Path: ...


class DefaultEvaluationCliRuntime:
    def __init__(self, runner: EvaluationRunner, *, output_root: Path) -> None:
        self._runner = runner
        self._output_root = output_root

    async def validate(self) -> dict[str, object]:
        return await self._runner.validate()

    async def run_evaluation(
        self,
        *,
        run_id: str,
        model: ModelAlias,
        case_id: str | None,
    ) -> tuple[EvaluationRunResult, Path]:
        result = await self._runner.run(run_id=run_id, model=model, case_id=case_id)
        paths = write_run_report(result, output_root=self._output_root)
        return result, paths.result_path

    def compare(self, *, run_id: str) -> Path:
        return write_comparison_report(run_id, output_root=self._output_root)

    def compare_longitudinal(
        self,
        *,
        baseline_run_id: str,
        current_run_id: str,
    ) -> Path:
        return write_longitudinal_comparison_report(
            baseline_run_id,
            current_run_id,
            output_root=self._output_root,
        )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="databricks-zh-expert-evals")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="预检固定数据集、Workspace、模型和索引")

    run_parser = commands.add_parser("run", help="通过正式 Chat API 运行端到端评估")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument(
        "--model",
        required=True,
        choices=(ModelAlias.DEEPSEEK_V4_FLASH.value, ModelAlias.DEEPSEEK_V4_PRO.value),
    )
    run_parser.add_argument("--case", dest="case_id")

    compare_parser = commands.add_parser("compare", help="生成两个固定模型的对比报告")
    compare_parser.add_argument("--run-id", required=True)
    longitudinal_parser = commands.add_parser(
        "longitudinal",
        help="比较两个已完成 Run 的双模型结果",
    )
    longitudinal_parser.add_argument("--baseline-run-id", required=True)
    longitudinal_parser.add_argument("--current-run-id", required=True)
    return parser


async def run(argv: Sequence[str], runtime: EvaluationCliRuntime) -> int:
    arguments = create_parser().parse_args(list(argv))
    try:
        if arguments.command == "validate":
            result = await runtime.validate()
            print(json.dumps(result, ensure_ascii=False, default=str))
            return 0 if result.get("passed") is True else 1
        if arguments.command == "run":
            result, result_path = await runtime.run_evaluation(
                run_id=arguments.run_id,
                model=ModelAlias(arguments.model),
                case_id=arguments.case_id,
            )
            print(
                json.dumps(
                    {
                        "passed": result.automated_passed,
                        "run_id": result.run_id,
                        "model": result.model.value,
                        "result_path": result_path.as_posix(),
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if result.automated_passed else 1
        if arguments.command == "compare":
            path = runtime.compare(run_id=arguments.run_id)
            print(json.dumps({"comparison_path": path.as_posix()}, ensure_ascii=False))
            return 0
        if arguments.command == "longitudinal":
            path = runtime.compare_longitudinal(
                baseline_run_id=arguments.baseline_run_id,
                current_run_id=arguments.current_run_id,
            )
            print(json.dumps({"longitudinal_path": path.as_posix()}, ensure_ascii=False))
            return 0
        raise RuntimeError("不支持的端到端评估命令。")
    except (EvaluationDatasetError, EvaluationReportError, ValueError) as error:
        print(f"端到端评估失败：{error}", file=sys.stderr)
        return 2


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


def main() -> None:
    _configure_utf8_stdio()
    configure_event_loop_policy()
    try:
        dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
        runner = EvaluationRunner(dataset=dataset, settings=get_settings())
        runtime = DefaultEvaluationCliRuntime(runner, output_root=EVALUATION_OUTPUT_ROOT)
        exit_code = asyncio.run(run(tuple(sys.argv[1:]), runtime))
    except (EvaluationDatasetError, ValueError) as error:
        print(f"端到端评估初始化失败：{error}", file=sys.stderr)
        exit_code = 2
    raise SystemExit(exit_code)
