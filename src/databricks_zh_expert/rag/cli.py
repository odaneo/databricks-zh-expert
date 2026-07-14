import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx

from databricks_zh_expert.core.config import get_settings
from databricks_zh_expert.core.runtime import selector_event_loop_factory
from databricks_zh_expert.db.session import Database
from databricks_zh_expert.rag.constants import (
    KNOWLEDGE_FETCH_TIMEOUT_SECONDS,
    KNOWLEDGE_MANIFEST_PATH,
)
from databricks_zh_expert.rag.embeddings import OpenAIEmbeddingClient
from databricks_zh_expert.rag.fetcher import KnowledgeFetcher
from databricks_zh_expert.rag.ingestion import KnowledgeIngestionService
from databricks_zh_expert.rag.manifest import KnowledgeManifestError
from databricks_zh_expert.rag.repository import KnowledgeIndexStatus, KnowledgeRepository


class IndexStatusRepository(Protocol):
    async def get_index_status(self) -> KnowledgeIndexStatus: ...


CloseCallback = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class KnowledgeCliRuntime:
    service: KnowledgeIngestionService
    repository: IndexStatusRepository
    close_callback: CloseCallback | None = None
    manifest_path: Path = KNOWLEDGE_MANIFEST_PATH

    async def close(self) -> None:
        if self.close_callback is not None:
            await self.close_callback()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="databricks-zh-expert-kb")
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync", help="同步预置 Databricks 知识库")
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--force", action="store_true")
    commands.add_parser("status", help="查看知识索引状态")
    return parser


async def run_async(
    argv: Sequence[str],
    runtime: KnowledgeCliRuntime,
) -> int:
    arguments = create_parser().parse_args(list(argv))
    if arguments.command == "sync":
        try:
            result = await runtime.service.sync(
                runtime.manifest_path,
                dry_run=arguments.dry_run,
                force=arguments.force,
            )
        except KnowledgeManifestError:
            print("知识来源清单无效。", file=sys.stderr)
            return 2
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
        return 0 if result.failed_count == 0 else 1

    status = await runtime.repository.get_index_status()
    print(json.dumps(asdict(status), ensure_ascii=False, default=str))
    return 0


def _build_runtime() -> KnowledgeCliRuntime:
    settings = get_settings()
    database = Database(settings.database_url)
    http_client = httpx.AsyncClient(timeout=KNOWLEDGE_FETCH_TIMEOUT_SECONDS)
    repository = KnowledgeRepository(database.session_factory)
    embedding_client = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.model_request_timeout_seconds,
    )
    service = KnowledgeIngestionService(
        repository=repository,
        fetcher=KnowledgeFetcher(http_client),
        embedding_client=embedding_client,
    )

    async def close() -> None:
        await http_client.aclose()
        await database.dispose()

    return KnowledgeCliRuntime(
        service=service,
        repository=repository,
        close_callback=close,
        manifest_path=KNOWLEDGE_MANIFEST_PATH,
    )


async def _run_owned(argv: Sequence[str]) -> int:
    runtime = _build_runtime()
    try:
        return await run_async(argv, runtime)
    finally:
        await runtime.close()


def main() -> None:
    try:
        with asyncio.Runner(loop_factory=selector_event_loop_factory) as runner:
            exit_code = runner.run(_run_owned(tuple(sys.argv[1:])))
    except Exception as error:
        print(
            f"知识库命令失败：{type(error).__name__}",
            file=sys.stderr,
        )
        exit_code = 1
    raise SystemExit(exit_code)
