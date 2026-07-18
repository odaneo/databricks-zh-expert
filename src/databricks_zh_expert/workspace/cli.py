import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from databricks_zh_expert.workspace.context import WorkspaceContextBuilder
from databricks_zh_expert.workspace.evaluation import (
    WORKSPACE_EVALUATION_PATH,
    WorkspaceEvaluationError,
    WorkspaceEvaluationRunner,
    WorkspaceEvaluator,
)
from databricks_zh_expert.workspace.registry import WorkspaceRegistry, WorkspaceRegistryError


@dataclass(slots=True)
class WorkspaceCliRuntime:
    evaluator: WorkspaceEvaluationRunner


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="databricks-zh-expert-workspaces")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("evaluate", help="评估 Workspace Context 质量")
    return parser


def run(argv: Sequence[str], runtime: WorkspaceCliRuntime) -> int:
    arguments = create_parser().parse_args(list(argv))
    if arguments.command != "evaluate":
        raise RuntimeError("不支持的 Workspace 命令。")
    try:
        result = runtime.evaluator.evaluate_file(WORKSPACE_EVALUATION_PATH)
    except WorkspaceEvaluationError:
        print("Workspace Context 评估集无效。", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    return 0 if result.passed else 1


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
    try:
        registry = WorkspaceRegistry.create_default()
        runtime = WorkspaceCliRuntime(
            evaluator=WorkspaceEvaluator(
                registry=registry,
                context_builder=WorkspaceContextBuilder(),
            )
        )
        exit_code = run(tuple(sys.argv[1:]), runtime)
    except WorkspaceRegistryError:
        print("项目工作区契约无效。", file=sys.stderr)
        exit_code = 2
    except Exception as error:
        print(f"Workspace 命令失败：{type(error).__name__}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
