import shutil
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.workspace.constants import (
    WORKSPACE_ALLOWED_SUFFIXES,
    WORKSPACE_CONTEXT_MAX_TOKENS,
    WORKSPACE_CONTEXT_TOP_K,
    WORKSPACE_ROOT,
    WORKSPACE_SOURCE_MAX_BYTES,
)
from databricks_zh_expert.workspace.registry import (
    WorkspaceRegistry,
    WorkspaceRegistryError,
)
from databricks_zh_expert.workspace.types import WorkspaceSourceKind

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "workspaces"


def _manifest_path(root: Path) -> Path:
    return root / "retail_sales_demo" / ".databricks-expert" / "project.yml"


def _load_manifest(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load(_manifest_path(root).read_text(encoding="utf-8"))
    return cast(dict[str, Any], payload)


def _write_manifest(root: Path, payload: dict[str, Any]) -> None:
    _manifest_path(root).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def build_workspace_fixture(root: Path, *, mutation: str | None = None) -> Path:
    shutil.copytree(FIXTURE_ROOT / "valid", root)
    workspace_root = root / "retail_sales_demo"
    payload = _load_manifest(root)
    sources = cast(list[dict[str, Any]], payload["sources"])

    if mutation == "unknown_manifest_field":
        payload["unexpected"] = True
    elif mutation == "invalid_workspace_id":
        payload["id"] = "Retail-Sales"
    elif mutation == "invalid_semver":
        payload["version"] = "1.0"
    elif mutation == "unknown_prompt":
        cast(list[str], sources[0]["prompt_names"]).append("not_registered")
    elif mutation == "unknown_default_source":
        cast(dict[str, list[str]], payload["default_context"])["sql_generation"] = [
            "contract.missing"
        ]
    elif mutation == "absolute_source_path":
        sources[0]["path"] = (root / "outside.md").resolve().as_posix()
    elif mutation == "parent_traversal":
        sources[0]["path"] = "../outside.md"
    elif mutation == "forbidden_extension":
        sources[0]["path"] = "docs/project-overview.exe"
    elif mutation == "duplicate_source_id":
        sources[0]["id"] = sources[1]["id"]

    _write_manifest(root, payload)

    source_path = workspace_root / "docs" / "project-overview.md"
    if mutation == "non_utf8_source":
        source_path.write_bytes(b"\xff\xfe\x00")
    elif mutation == "oversized_source":
        source_path.write_bytes(b"a" * (WORKSPACE_SOURCE_MAX_BYTES + 1))
    return root


def test_fixed_workspace_constants_and_source_kinds() -> None:
    assert WORKSPACE_ROOT == Path("examples/workspaces")
    assert WORKSPACE_SOURCE_MAX_BYTES == 256_000
    assert WORKSPACE_CONTEXT_TOP_K == 6
    assert WORKSPACE_CONTEXT_MAX_TOKENS == 4_000
    assert WORKSPACE_ALLOWED_SUFFIXES == frozenset({".md", ".yml", ".yaml", ".sql", ".py"})
    assert tuple(WorkspaceSourceKind) == (
        WorkspaceSourceKind.PROJECT,
        WorkspaceSourceKind.SCHEMA,
        WorkspaceSourceKind.MAPPING,
        WorkspaceSourceKind.RULE,
        WorkspaceSourceKind.DDL,
        WorkspaceSourceKind.CODE,
        WorkspaceSourceKind.BUNDLE,
    )


def test_registry_loads_workspace_and_explicit_sources() -> None:
    registry = WorkspaceRegistry.load(FIXTURE_ROOT / "valid")

    assert tuple(workspace.workspace_id for workspace in registry.workspaces) == (
        "retail_sales_demo",
    )
    workspace = registry.get("retail_sales_demo")
    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert workspace.is_mock is True
    assert [source.source_id for source in workspace.sources] == [
        "contract.tables",
        "project.overview",
    ]
    assert workspace.default_context[PromptName.SQL_GENERATION] == ("contract.tables",)
    assert len(workspace.source_hash) == 64
    assert all(len(source.content_hash) == 64 for source in workspace.sources)
    assert all("\\" not in source.source_path for source in workspace.sources)
    assert all("\r" not in source.content for source in workspace.sources)


def test_registry_hash_is_stable_across_newline_styles(tmp_path: Path) -> None:
    lf_root = build_workspace_fixture(tmp_path / "lf")
    crlf_root = build_workspace_fixture(tmp_path / "crlf")
    for path in crlf_root.rglob("*"):
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert (
        WorkspaceRegistry.load(lf_root).get("retail_sales_demo").source_hash
        == WorkspaceRegistry.load(crlf_root).get("retail_sales_demo").source_hash
    )


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("unknown_manifest_field", "包含未知字段"),
        ("invalid_workspace_id", "工作区 ID"),
        ("invalid_semver", "版本必须使用 MAJOR.MINOR.PATCH"),
        ("unknown_prompt", "Prompt 未注册"),
        ("unknown_default_source", "默认上下文引用不存在"),
        ("absolute_source_path", "必须使用工作区相对路径"),
        ("parent_traversal", "不能包含 .."),
        ("forbidden_extension", "文件类型不允许"),
        ("non_utf8_source", "必须使用 UTF-8"),
        ("oversized_source", "超过最大大小"),
        ("duplicate_source_id", "Source ID 不能重复"),
    ],
)
def test_registry_rejects_invalid_workspace(
    tmp_path: Path,
    mutation: str,
    expected_message: str,
) -> None:
    root = build_workspace_fixture(tmp_path / "registry", mutation=mutation)

    with pytest.raises(WorkspaceRegistryError, match=expected_message):
        WorkspaceRegistry.load(root)


def test_registry_rejects_symlink_escape_without_requiring_windows_symlink_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = build_workspace_fixture(tmp_path / "registry")
    escaped_source = (root / "retail_sales_demo" / "docs" / "project-overview.md").absolute()
    outside = (tmp_path / "outside.md").resolve()
    original_resolve = Path.resolve

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path.absolute() == escaped_source:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    with pytest.raises(WorkspaceRegistryError, match="工作区目录之外"):
        WorkspaceRegistry.load(root)


def test_registry_errors_do_not_leak_absolute_paths(tmp_path: Path) -> None:
    root = build_workspace_fixture(tmp_path / "registry", mutation="invalid_semver")

    with pytest.raises(WorkspaceRegistryError) as error:
        WorkspaceRegistry.load(root)

    assert str(root.resolve()) not in str(error.value)


def test_registry_rejects_unknown_workspace_id() -> None:
    registry = WorkspaceRegistry.load(FIXTURE_ROOT / "valid")

    with pytest.raises(WorkspaceRegistryError, match="项目工作区未注册"):
        registry.get("unknown")
