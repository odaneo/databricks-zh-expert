"""AWS 零售销售 Mock 项目的集中运行参数样例。"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

ALLOWED_CATALOGS = frozenset({"retail_dev", "retail_test", "retail_prod"})


@dataclass(frozen=True, slots=True)
class RuntimeParameters:
    catalog: str
    source_path: str
    checkpoint_path: str
    processing_date: date | None


def read_runtime_parameters(argv: Sequence[str] | None = None) -> RuntimeParameters:
    parser = argparse.ArgumentParser(description="读取零售销售 Mock 摄取参数。")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--checkpoint-path", required=True)
    parser.add_argument("--processing-date", default="")
    args = parser.parse_args(argv)

    if args.catalog not in ALLOWED_CATALOGS:
        parser.error("catalog 必须是 retail_dev、retail_test 或 retail_prod。")
    processing_date = date.fromisoformat(args.processing_date) if args.processing_date else None
    return RuntimeParameters(
        catalog=args.catalog,
        source_path=args.source_path,
        checkpoint_path=args.checkpoint_path,
        processing_date=processing_date,
    )
