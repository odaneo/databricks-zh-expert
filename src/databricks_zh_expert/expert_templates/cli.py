import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from databricks_zh_expert.core.config import get_settings
from databricks_zh_expert.core.runtime import selector_event_loop_factory
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.expert_templates.registry import (
    ExpertTemplateRegistry,
    ExpertTemplateRegistryError,
)
from databricks_zh_expert.expert_templates.repository import ExpertTemplateRepository
from databricks_zh_expert.expert_templates.sync import (
    ExpertTemplateSyncError,
    ExpertTemplateSyncService,
)
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateIndexStatus,
    ExpertTemplateSyncResult,
)
from databricks_zh_expert.rag.embeddings import OpenAIEmbeddingClient


class ExpertTemplateSyncRunner(Protocol):
    async def sync(
        self,
        registry: ExpertTemplateRegistry,
        *,
        dry_run: bool = False,
    ) -> ExpertTemplateSyncResult: ...


class ExpertTemplateStatusRepository(Protocol):
    async def get_index_status(
        self,
        current_source_hash: str,
    ) -> ExpertTemplateIndexStatus: ...


CloseCallback = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class ExpertTemplateCliRuntime:
    service: ExpertTemplateSyncRunner
    repository: ExpertTemplateStatusRepository
    registry: ExpertTemplateRegistry
    close_callback: CloseCallback | None = None

    async def close(self) -> None:
        if self.close_callback is not None:
            await self.close_callback()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="databricks-zh-expert-templates")
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync", help="同步预置专家模板")
    sync_parser.add_argument("--dry-run", action="store_true")
    commands.add_parser("status", help="查看专家模板索引状态")
    return parser


async def run_async(
    argv: Sequence[str],
    runtime: ExpertTemplateCliRuntime,
) -> int:
    arguments = create_parser().parse_args(list(argv))
    if arguments.command == "sync":
        try:
            result = await runtime.service.sync(
                runtime.registry,
                dry_run=arguments.dry_run,
            )
        except ExpertTemplateSyncError:
            print("专家模板同步失败。", file=sys.stderr)
            return 1
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
        return 0 if result.failed_count == 0 else 1

    status = await runtime.repository.get_index_status(runtime.registry.source_hash)
    print(json.dumps(asdict(status), ensure_ascii=False, default=str))
    return 0


def _build_runtime() -> ExpertTemplateCliRuntime:
    registry = ExpertTemplateRegistry.create_default()
    settings = get_settings()
    database = Database(settings.database_url)
    repository = ExpertTemplateRepository(
        database.session_factory,
        registry=registry,
    )
    embedding_client = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.model_request_timeout_seconds,
    )
    service = ExpertTemplateSyncService(
        repository=repository,
        embedding_client=embedding_client,
    )

    async def close() -> None:
        await database.dispose()

    return ExpertTemplateCliRuntime(
        service=service,
        repository=repository,
        registry=registry,
        close_callback=close,
    )


async def _run_owned(argv: Sequence[str]) -> int:
    try:
        runtime = _build_runtime()
    except ExpertTemplateRegistryError:
        print("专家模板源契约无效。", file=sys.stderr)
        return 2
    try:
        return await run_async(argv, runtime)
    finally:
        await runtime.close()


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
        with asyncio.Runner(loop_factory=selector_event_loop_factory) as runner:
            exit_code = runner.run(_run_owned(tuple(sys.argv[1:])))
    except Exception as error:
        print(
            f"专家模板命令失败：{type(error).__name__}",
            file=sys.stderr,
        )
        exit_code = 1
    raise SystemExit(exit_code)
