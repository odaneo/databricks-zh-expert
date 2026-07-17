import shutil
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from databricks_zh_expert.workspace.constants import (
    WORKSPACE_ALLOWED_SUFFIXES,
    WORKSPACE_CONTEXT_MAX_TOKENS,
    WORKSPACE_CONTEXT_TOP_K,
    WORKSPACE_PACKAGE_MAX_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SOURCE_MAX_BYTES,
)
from databricks_zh_expert.workspace.registry import (
    WorkspaceRegistry,
    WorkspaceRegistryError,
)
from databricks_zh_expert.workspace.types import WorkspaceMode, WorkspaceSourceKind

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "workspaces"


def _workspace_root(root: Path) -> Path:
    return root / "retail_sales_demo"


def _package_root(root: Path) -> Path:
    return _workspace_root(root) / ".databricks-expert"


def _manifest_path(root: Path) -> Path:
    return _package_root(root) / "project.yml"


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
    payload = _load_manifest(root)
    source_schemas = cast(list[dict[str, Any]], payload["source_schemas"])
    source_files = cast(list[str], source_schemas[0]["files"])

    if mutation == "unknown_manifest_field":
        payload["unexpected"] = True
    elif mutation == "legacy_manifest":
        payload["sources"] = []
    elif mutation == "invalid_workspace_id":
        payload["id"] = "Retail-Sales"
    elif mutation == "invalid_semver":
        payload["version"] = "1.0"
    elif mutation == "invalid_workspace_mode":
        payload["workspace_mode"] = "existing"
    elif mutation == "missing_requirements":
        cast(dict[str, str], payload["documents"]).pop("requirements")
    elif mutation == "missing_source_schemas":
        payload["source_schemas"] = []
    elif mutation == "duplicate_source_id":
        source_schemas.append(dict(source_schemas[0]))
    elif mutation == "duplicate_source_file":
        source_files.append(source_files[0])
    elif mutation == "absolute_source_path":
        source_files[0] = (root / "outside.sql").resolve().as_posix()
    elif mutation == "parent_traversal":
        source_files[0] = "../outside.sql"
    elif mutation == "outside_source_directory":
        source_files[0] = "rds-postgresql.sql"
    elif mutation == "forbidden_extension":
        source_files[0] = "source-schema/rds-postgresql.py"

    _write_manifest(root, payload)

    source_path = _package_root(root) / "source-schema" / "rds-postgresql.sql"
    if mutation == "non_utf8_source":
        source_path.write_bytes(b"\xff\xfe\x00")
    elif mutation == "oversized_source":
        source_path.write_bytes(b"a" * (WORKSPACE_SOURCE_MAX_BYTES + 1))
    elif mutation == "source_contains_dml":
        source_path.write_text(
            source_path.read_text(encoding="utf-8")
            + "\nINSERT INTO public.customer VALUES ('1', 'secret@example.com', now());\n",
            encoding="utf-8",
        )
    elif mutation == "missing_requirements_section":
        requirements_path = _package_root(root) / "requirements.md"
        requirements_path.write_text(
            requirements_path.read_text(encoding="utf-8").replace(
                "## 技术约束\n\n使用 AWS 和 Databricks 正式功能。\n\n",
                "",
            ),
            encoding="utf-8",
        )
    elif mutation == "missing_rules_section":
        rules_path = _package_root(root) / "business-rules.md"
        rules_path.write_text(
            rules_path.read_text(encoding="utf-8").replace(
                "## PII 与权限\n\n邮箱属于直接识别字段。\n\n",
                "",
            ),
            encoding="utf-8",
        )
    return root


def test_fixed_workspace_constants_and_source_kinds() -> None:
    assert WORKSPACE_ROOT == Path("examples/workspaces")
    assert WORKSPACE_SOURCE_MAX_BYTES == 2 * 1024 * 1024
    assert WORKSPACE_PACKAGE_MAX_BYTES == 20 * 1024 * 1024
    assert WORKSPACE_CONTEXT_TOP_K == 8
    assert WORKSPACE_CONTEXT_MAX_TOKENS == 8_000
    assert WORKSPACE_ALLOWED_SUFFIXES == frozenset({".md", ".sql"})
    assert tuple(WorkspaceMode) == (WorkspaceMode.GREENFIELD,)
    assert tuple(WorkspaceSourceKind) == (
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.SOURCE_DDL,
        WorkspaceSourceKind.RULE,
    )


def test_registry_loads_greenfield_workspace_sources() -> None:
    registry = WorkspaceRegistry.load(FIXTURE_ROOT / "valid")

    workspace = registry.get("retail_sales_demo")
    assert workspace.workspace_mode is WorkspaceMode.GREENFIELD
    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert workspace.is_mock is True
    assert [source.source_id for source in workspace.sources] == [
        "requirements",
        "rules",
        "source_ddl.rds_postgresql.rds-postgresql",
    ]
    assert [source.kind for source in workspace.sources] == [
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.RULE,
        WorkspaceSourceKind.SOURCE_DDL,
    ]
    assert workspace.sources[-1].dialect == "postgresql"
    assert workspace.sources[-1].source_path == (
        ".databricks-expert/source-schema/rds-postgresql.sql"
    )
    assert len(workspace.source_hash) == 64
    assert all(len(source.content_hash) == 64 for source in workspace.sources)
    assert all("\\" not in source.source_path for source in workspace.sources)
    assert all("\r" not in source.content for source in workspace.sources)


def test_registry_accepts_real_project_is_mock_false(tmp_path: Path) -> None:
    root = build_workspace_fixture(tmp_path / "registry")
    payload = _load_manifest(root)
    payload["is_mock"] = False
    _write_manifest(root, payload)

    assert WorkspaceRegistry.load(root).get("retail_sales_demo").is_mock is False


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
        ("legacy_manifest", "包含未知字段"),
        ("invalid_workspace_id", "工作区 ID"),
        ("invalid_semver", "版本必须使用 MAJOR.MINOR.PATCH"),
        ("invalid_workspace_mode", "模式必须为 greenfield"),
        ("missing_requirements", "documents"),
        ("missing_source_schemas", "至少登记一个源 Schema"),
        ("duplicate_source_id", "源 Schema ID 不能重复"),
        ("duplicate_source_file", "源 Schema 文件不能重复"),
        ("absolute_source_path", "必须使用输入包相对路径"),
        ("parent_traversal", "不能包含 .."),
        ("outside_source_directory", "必须位于 source-schema 目录"),
        ("forbidden_extension", "只允许 SQL"),
        ("non_utf8_source", "必须使用 UTF-8"),
        ("oversized_source", "超过最大大小"),
        ("source_contains_dml", "不能包含数据写入语句"),
        ("missing_requirements_section", "requirements.md 缺少章节：技术约束"),
        ("missing_rules_section", "business-rules.md 缺少章节：PII 与权限"),
    ],
)
def test_registry_rejects_invalid_greenfield_workspace(
    tmp_path: Path,
    mutation: str,
    expected_message: str,
) -> None:
    root = build_workspace_fixture(tmp_path / "registry", mutation=mutation)

    with pytest.raises(WorkspaceRegistryError, match=expected_message):
        WorkspaceRegistry.load(root)


def test_registry_rejects_symlink_escape_without_windows_symlink_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = build_workspace_fixture(tmp_path / "registry")
    escaped_source = (_package_root(root) / "source-schema" / "rds-postgresql.sql").absolute()
    outside = (tmp_path / "outside.sql").resolve()
    original_resolve = Path.resolve

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path.absolute() == escaped_source:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    with pytest.raises(WorkspaceRegistryError, match="输入包目录之外"):
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
