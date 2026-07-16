import json
from collections.abc import Sequence

import pytest

from databricks_zh_expert.expert_templates import cli
from databricks_zh_expert.expert_templates.cli import (
    ExpertTemplateCliRuntime,
    run_async,
)
from databricks_zh_expert.expert_templates.registry import (
    ExpertTemplateRegistry,
    ExpertTemplateRegistryError,
)
from databricks_zh_expert.expert_templates.sync import ExpertTemplateSyncError
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateIndexStatus,
    ExpertTemplateSyncResult,
)


class FakeSyncService:
    def __init__(
        self,
        result: ExpertTemplateSyncResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[ExpertTemplateRegistry, bool]] = []

    async def sync(
        self,
        registry: ExpertTemplateRegistry,
        *,
        dry_run: bool = False,
    ) -> ExpertTemplateSyncResult:
        self.calls.append((registry, dry_run))
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("测试未配置同步结果。")
        return self.result


class FakeStatusRepository:
    def __init__(self, status: ExpertTemplateIndexStatus) -> None:
        self.status = status
        self.source_hashes: list[str] = []

    async def get_index_status(
        self,
        current_source_hash: str,
    ) -> ExpertTemplateIndexStatus:
        self.source_hashes.append(current_source_hash)
        return self.status


@pytest.fixture(scope="module")
def registry() -> ExpertTemplateRegistry:
    return ExpertTemplateRegistry.create_default()


def _result(*, dry_run: bool) -> ExpertTemplateSyncResult:
    return ExpertTemplateSyncResult(
        run_id=None,
        source_hash="a" * 64,
        dry_run=dry_run,
        status="dry_run" if dry_run else "succeeded",
        discovered_count=37,
        inserted_count=37,
        activated_count=37,
        inactivated_count=0,
        skipped_count=0,
        failed_count=0,
        chunk_count=42,
        error_summary=(),
    )


def _status(*, queryable: bool = True) -> ExpertTemplateIndexStatus:
    return ExpertTemplateIndexStatus(
        latest_run_status="succeeded",
        source_hash_matches=True,
        active_template_count=37,
        chunk_count=42,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        queryable=queryable,
    )


@pytest.mark.asyncio
async def test_sync_dry_run_outputs_json_and_returns_zero(
    registry: ExpertTemplateRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeSyncService(_result(dry_run=True))
    repository = FakeStatusRepository(_status())
    runtime = ExpertTemplateCliRuntime(
        service=service,
        repository=repository,
        registry=registry,
    )

    exit_code = await run_async(("sync", "--dry-run"), runtime)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dry_run"] is True
    assert output["inserted_count"] == 37
    assert service.calls == [(registry, True)]


@pytest.mark.asyncio
async def test_sync_failure_returns_one_without_leaking_original_error(
    registry: ExpertTemplateRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeSyncService(
        error=ExpertTemplateSyncError("sk-secret-value C:\\private\\templates")
    )
    runtime = ExpertTemplateCliRuntime(
        service=service,
        repository=FakeStatusRepository(_status()),
        registry=registry,
    )

    exit_code = await run_async(("sync",), runtime)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "专家模板同步失败" in captured.err
    assert "sk-secret-value" not in captured.err
    assert "private" not in captured.err


@pytest.mark.asyncio
async def test_status_uses_current_registry_hash(
    registry: ExpertTemplateRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = FakeStatusRepository(_status(queryable=False))
    runtime = ExpertTemplateCliRuntime(
        service=FakeSyncService(_result(dry_run=False)),
        repository=repository,
        registry=registry,
    )

    exit_code = await run_async(("status",), runtime)

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["queryable"] is False
    assert repository.source_hashes == [registry.source_hash]


@pytest.mark.asyncio
async def test_invalid_source_contract_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_runtime() -> ExpertTemplateCliRuntime:
        raise ExpertTemplateRegistryError("C:\\secret\\profiles.yml invalid")

    monkeypatch.setattr(cli, "_build_runtime", invalid_runtime)

    exit_code = await cli._run_owned(("status",))

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "专家模板源契约无效" in captured.err
    assert "secret" not in captured.err


@pytest.mark.parametrize(
    "argv",
    [(), ("unknown",), ("status", "--dry-run")],
)
def test_parser_rejects_invalid_commands(argv: Sequence[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.create_parser().parse_args(list(argv))

    assert caught.value.code == 2
