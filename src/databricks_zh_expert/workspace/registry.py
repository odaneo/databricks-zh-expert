import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Annotated, Any, Literal, cast

import sqlparse
import yaml
from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError

from databricks_zh_expert.workspace.constants import (
    WORKSPACE_PACKAGE_MAX_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SOURCE_MAX_BYTES,
)
from databricks_zh_expert.workspace.types import (
    WorkspaceDefinition,
    WorkspaceMode,
    WorkspaceSource,
    WorkspaceSourceKind,
)

_WORKSPACE_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
_SOURCE_SCHEMA_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
_SEMVER_PATTERN = r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
_MANIFEST_RELATIVE_PATH = Path(".databricks-expert/project.yml")
_PACKAGE_DIRECTORY_NAME = ".databricks-expert"
_REQUIREMENTS_PATH = "requirements.md"
_BUSINESS_RULES_PATH = "business-rules.md"
_REQUIREMENTS_H1 = "项目需求"
_BUSINESS_RULES_H1 = "已确认业务与数据规则"
_REQUIREMENTS_SECTIONS = (
    "业务目标",
    "源系统",
    "期望数据产品",
    "摄取需求",
    "数据量与 SLA 假设",
    "治理与安全",
    "技术约束",
    "待确认事项",
)
_BUSINESS_RULES_SECTIONS = (
    "源数据粒度与业务键",
    "CDC 与去重",
    "事件时间与迟到数据",
    "指标口径",
    "空值与数据质量",
    "PII 与权限",
    "待确认规则",
)
_FORBIDDEN_DML_TYPES = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE"})
_COPY_FROM_STDIN_PATTERN = re.compile(
    r"^\s*copy\b[\s\S]*\bfrom\s+stdin\b",
    re.IGNORECASE,
)
_VALUES_STATEMENT_PATTERN = re.compile(r"^\s*values\b", re.IGNORECASE)

WorkspaceId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_WORKSPACE_ID_PATTERN),
]
SourceSchemaId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_SOURCE_SCHEMA_ID_PATTERN),
]


class WorkspaceRegistryError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class _DocumentsModel(_StrictModel):
    requirements: Literal["requirements.md"]
    business_rules: Literal["business-rules.md"]


class _SourceSchemaModel(_StrictModel):
    source_schema_id: SourceSchemaId = Field(alias="id")
    dialect: Literal["postgresql", "spark_sql"]
    files: tuple[str, ...] = Field(min_length=1)


class _ManifestModel(_StrictModel):
    schema_version: Literal[1]
    workspace_mode: Literal["greenfield"]
    workspace_id: WorkspaceId = Field(alias="id")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    version: str = Field(pattern=_SEMVER_PATTERN)
    cloud: Literal["aws"]
    is_mock: bool
    documents: _DocumentsModel
    source_schemas: tuple[_SourceSchemaModel, ...] = Field(min_length=1)


class WorkspaceRegistry:
    def __init__(self, *, workspaces: tuple[WorkspaceDefinition, ...]) -> None:
        self._workspaces = workspaces
        self._workspaces_by_id = MappingProxyType(
            {workspace.workspace_id: workspace for workspace in workspaces}
        )

    @property
    def workspaces(self) -> tuple[WorkspaceDefinition, ...]:
        return self._workspaces

    @classmethod
    def create_default(cls) -> "WorkspaceRegistry":
        return cls.load(WORKSPACE_ROOT)

    @classmethod
    def load(cls, root: Path) -> "WorkspaceRegistry":
        if not root.is_dir():
            raise WorkspaceRegistryError("项目工作区根目录不存在。")

        try:
            resolved_root = root.resolve(strict=True)
            workspace_directories = tuple(
                sorted(
                    (
                        path
                        for path in root.iterdir()
                        if path.is_dir() and (path / _MANIFEST_RELATIVE_PATH).is_file()
                    ),
                    key=lambda path: path.name,
                )
            )
        except OSError:
            raise WorkspaceRegistryError("无法读取项目工作区根目录。") from None

        if not workspace_directories:
            raise WorkspaceRegistryError("项目工作区根目录中没有有效清单。")

        workspaces = tuple(
            sorted(
                (_load_workspace(path, resolved_root) for path in workspace_directories),
                key=lambda workspace: workspace.workspace_id,
            )
        )
        workspace_ids = tuple(workspace.workspace_id for workspace in workspaces)
        if len(workspace_ids) != len(set(workspace_ids)):
            raise WorkspaceRegistryError("工作区 ID 不能重复。")
        return cls(workspaces=workspaces)

    def get(self, workspace_id: str) -> WorkspaceDefinition:
        try:
            return self._workspaces_by_id[workspace_id]
        except KeyError:
            raise WorkspaceRegistryError("项目工作区未注册。") from None


def _load_workspace(workspace_directory: Path, registry_root: Path) -> WorkspaceDefinition:
    try:
        workspace_root = workspace_directory.resolve(strict=True)
        package_root = (workspace_directory / _PACKAGE_DIRECTORY_NAME).resolve(strict=True)
    except OSError:
        raise WorkspaceRegistryError("无法读取项目工作区目录。") from None
    if not workspace_root.is_relative_to(registry_root):
        raise WorkspaceRegistryError("项目工作区目录不能位于根目录之外。")
    if not package_root.is_relative_to(workspace_root) or not package_root.is_dir():
        raise WorkspaceRegistryError("项目输入包目录无效。")
    if _package_size(package_root) > WORKSPACE_PACKAGE_MAX_BYTES:
        raise WorkspaceRegistryError("项目输入包超过最大大小。")

    manifest_source = _read_manifest(package_root / "project.yml", package_root)
    manifest = _parse_manifest(manifest_source)
    _validate_manifest_contract(manifest)

    sources = _load_sources(package_root, manifest)
    return WorkspaceDefinition(
        workspace_id=manifest.workspace_id,
        workspace_mode=WorkspaceMode.GREENFIELD,
        display_name=manifest.display_name,
        description=manifest.description,
        version=manifest.version,
        cloud=manifest.cloud,
        is_mock=manifest.is_mock,
        source_hash=_source_hash(manifest, sources),
        sources=sources,
    )


def _package_size(package_root: Path) -> int:
    total = 0
    try:
        for path in package_root.rglob("*"):
            if not path.is_file():
                continue
            resolved_path = path.resolve(strict=True)
            if not resolved_path.is_relative_to(package_root):
                raise WorkspaceRegistryError("项目输入文件不能位于输入包目录之外。")
            total += resolved_path.stat().st_size
            if total > WORKSPACE_PACKAGE_MAX_BYTES:
                return total
    except WorkspaceRegistryError:
        raise
    except OSError:
        raise WorkspaceRegistryError("无法检查项目输入包大小。") from None
    return total


def _read_manifest(path: Path, package_root: Path) -> str:
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        raise WorkspaceRegistryError("项目工作区清单不存在。") from None
    if not resolved_path.is_relative_to(package_root):
        raise WorkspaceRegistryError("项目工作区清单不能位于输入包目录之外。")
    try:
        return _normalize_source(resolved_path.read_text(encoding="utf-8"))
    except UnicodeError:
        raise WorkspaceRegistryError("项目工作区清单必须使用 UTF-8。") from None
    except OSError:
        raise WorkspaceRegistryError("无法读取项目工作区清单。") from None


def _parse_manifest(source: str) -> _ManifestModel:
    try:
        payload = yaml.safe_load(source)
    except YAMLError:
        raise WorkspaceRegistryError("项目工作区清单不是合法 YAML。") from None
    try:
        return _ManifestModel.model_validate(payload)
    except ValidationError as error:
        raise WorkspaceRegistryError(_validation_message(error)) from None


def _validation_message(error: ValidationError) -> str:
    issues = error.errors(include_url=False, include_input=False)
    if any(issue["type"] == "extra_forbidden" for issue in issues):
        return "项目工作区清单包含未知字段。"
    for issue in issues:
        location = tuple(str(part) for part in issue["loc"])
        if location and location[-1] == "workspace_mode":
            return "项目工作区模式必须为 greenfield。"
        if location and location[-1] == "version":
            return "项目工作区版本必须使用 MAJOR.MINOR.PATCH。"
        if location and location[-1] == "source_schemas" and issue["type"] == "too_short":
            return "项目工作区至少登记一个源 Schema。"
        if location and location[-1] == "id":
            if "source_schemas" in location:
                return "项目工作区清单的源 Schema ID 无效。"
            return "项目工作区清单的工作区 ID 无效。"
    fields = ".".join(str(part) for part in issues[0]["loc"]) if issues else "root"
    return f"项目工作区清单字段无效：{fields}。"


def _validate_manifest_contract(manifest: _ManifestModel) -> None:
    source_schema_ids = tuple(item.source_schema_id for item in manifest.source_schemas)
    if len(source_schema_ids) != len(set(source_schema_ids)):
        raise WorkspaceRegistryError("源 Schema ID 不能重复。")

    source_files = tuple(path for item in manifest.source_schemas for path in item.files)
    if len(source_files) != len(set(source_files)):
        raise WorkspaceRegistryError("源 Schema 文件不能重复。")


def _load_sources(
    package_root: Path,
    manifest: _ManifestModel,
) -> tuple[WorkspaceSource, ...]:
    sources = [
        _load_markdown_source(
            package_root,
            manifest.documents.requirements,
            source_id="requirements",
            kind=WorkspaceSourceKind.REQUIREMENT,
            expected_h1=_REQUIREMENTS_H1,
            required_sections=_REQUIREMENTS_SECTIONS,
        ),
        _load_markdown_source(
            package_root,
            manifest.documents.business_rules,
            source_id="rules",
            kind=WorkspaceSourceKind.RULE,
            expected_h1=_BUSINESS_RULES_H1,
            required_sections=_BUSINESS_RULES_SECTIONS,
        ),
    ]
    for source_schema in manifest.source_schemas:
        for source_path in source_schema.files:
            relative_path = _validate_source_schema_path(source_path)
            source_id = (
                f"source_ddl.{source_schema.source_schema_id}.{relative_path.stem.casefold()}"
            )
            content = _read_registered_source(package_root, relative_path, source_id=source_id)
            _validate_source_sql(content, source_id=source_id)
            sources.append(
                _make_source(
                    source_id=source_id,
                    kind=WorkspaceSourceKind.SOURCE_DDL,
                    dialect=source_schema.dialect,
                    relative_path=relative_path,
                    content=content,
                )
            )

    source_ids = tuple(source.source_id for source in sources)
    if len(source_ids) != len(set(source_ids)):
        raise WorkspaceRegistryError("Registry 生成的 Source ID 不能重复。")
    return tuple(sorted(sources, key=lambda source: source.source_id))


def _load_markdown_source(
    package_root: Path,
    source_path: str,
    *,
    source_id: str,
    kind: WorkspaceSourceKind,
    expected_h1: str,
    required_sections: tuple[str, ...],
) -> WorkspaceSource:
    relative_path = _validate_markdown_path(source_path, source_id=source_id)
    content = _read_registered_source(package_root, relative_path, source_id=source_id)
    _validate_markdown_contract(
        content,
        file_name=relative_path.name,
        expected_h1=expected_h1,
        required_sections=required_sections,
    )
    return _make_source(
        source_id=source_id,
        kind=kind,
        dialect=None,
        relative_path=relative_path,
        content=content,
    )


def _validate_markdown_path(source_path: str, *, source_id: str) -> PurePosixPath:
    relative_path = _validate_relative_path(source_path)
    expected = _REQUIREMENTS_PATH if source_id == "requirements" else _BUSINESS_RULES_PATH
    if relative_path.as_posix() != expected or relative_path.suffix.casefold() != ".md":
        raise WorkspaceRegistryError(f"{expected} 必须使用固定输入包相对路径。")
    return relative_path


def _validate_source_schema_path(source_path: str) -> PurePosixPath:
    relative_path = _validate_relative_path(source_path)
    if len(relative_path.parts) < 2 or relative_path.parts[0] != "source-schema":
        raise WorkspaceRegistryError("源 Schema 文件必须位于 source-schema 目录。")
    if relative_path.suffix.casefold() != ".sql":
        raise WorkspaceRegistryError("源 Schema 文件只允许 SQL。")
    return relative_path


def _validate_relative_path(source_path: str) -> PurePosixPath:
    windows_path = PureWindowsPath(source_path)
    posix_path = PurePosixPath(source_path)
    if (
        not source_path
        or "\\" in source_path
        or windows_path.is_absolute()
        or posix_path.is_absolute()
    ):
        raise WorkspaceRegistryError("项目输入文件必须使用输入包相对路径。")
    if ".." in posix_path.parts:
        raise WorkspaceRegistryError("项目输入文件路径不能包含 ..。")
    if "." in posix_path.parts or posix_path.as_posix() != source_path:
        raise WorkspaceRegistryError("项目输入文件必须使用规范的 POSIX 相对路径。")
    return posix_path


def _read_registered_source(
    package_root: Path,
    relative_path: PurePosixPath,
    *,
    source_id: str,
) -> str:
    candidate = package_root.joinpath(*relative_path.parts)
    try:
        resolved_path = candidate.resolve(strict=True)
    except OSError:
        raise WorkspaceRegistryError(f"项目输入文件不存在：{source_id}。") from None
    if not resolved_path.is_relative_to(package_root):
        raise WorkspaceRegistryError("项目输入文件不能位于输入包目录之外。")
    if not resolved_path.is_file():
        raise WorkspaceRegistryError(f"项目输入路径不是文件：{source_id}。")

    try:
        if resolved_path.stat().st_size > WORKSPACE_SOURCE_MAX_BYTES:
            raise WorkspaceRegistryError(f"项目输入文件超过最大大小：{source_id}。")
        source_bytes = resolved_path.read_bytes()
    except WorkspaceRegistryError:
        raise
    except OSError:
        raise WorkspaceRegistryError(f"无法读取项目输入文件：{source_id}。") from None
    if len(source_bytes) > WORKSPACE_SOURCE_MAX_BYTES:
        raise WorkspaceRegistryError(f"项目输入文件超过最大大小：{source_id}。")
    try:
        return _normalize_source(source_bytes.decode("utf-8"))
    except UnicodeError:
        raise WorkspaceRegistryError(f"项目输入文件必须使用 UTF-8：{source_id}。") from None


def _validate_markdown_contract(
    content: str,
    *,
    file_name: str,
    expected_h1: str,
    required_sections: tuple[str, ...],
) -> None:
    headings: dict[int, list[str]] = {1: [], 2: []}
    tokens = MarkdownIt("commonmark").parse(content)
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open" or token.tag not in {"h1", "h2"}:
            continue
        inline = tokens[index + 1]
        if inline.type == "inline":
            headings[int(token.tag[1])].append(inline.content.strip())

    if headings[1] != [expected_h1]:
        raise WorkspaceRegistryError(f"{file_name} 的一级标题必须为：{expected_h1}。")
    for section in required_sections:
        if section not in headings[2]:
            raise WorkspaceRegistryError(f"{file_name} 缺少章节：{section}。")


def _validate_source_sql(content: str, *, source_id: str) -> None:
    statements = tuple(sqlparse.split(content, strip_semicolon=False))
    meaningful_statements: list[str] = []
    for statement_source in statements:
        without_comments = sqlparse.format(statement_source, strip_comments=True).strip()
        if not without_comments:
            continue
        meaningful_statements.append(without_comments)
        parsed = sqlparse.parse(without_comments)
        statement_type = parsed[0].get_type().upper() if parsed else "UNKNOWN"
        if (
            statement_type in _FORBIDDEN_DML_TYPES
            or _COPY_FROM_STDIN_PATTERN.match(without_comments)
            or _VALUES_STATEMENT_PATTERN.match(without_comments)
        ):
            raise WorkspaceRegistryError(f"源 Schema 不能包含数据写入语句：{source_id}。")
    if not meaningful_statements:
        raise WorkspaceRegistryError(f"源 Schema 未包含可解析 SQL：{source_id}。")


def _make_source(
    *,
    source_id: str,
    kind: WorkspaceSourceKind,
    dialect: str | None,
    relative_path: PurePosixPath,
    content: str,
) -> WorkspaceSource:
    return WorkspaceSource(
        source_id=source_id,
        kind=kind,
        dialect=dialect,
        source_path=f"{_PACKAGE_DIRECTORY_NAME}/{relative_path.as_posix()}",
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _source_hash(
    manifest: _ManifestModel,
    sources: tuple[WorkspaceSource, ...],
) -> str:
    manifest_payload = cast(dict[str, Any], manifest.model_dump(mode="json", by_alias=True))
    source_schemas = cast(list[dict[str, Any]], manifest_payload["source_schemas"])
    for source_schema in source_schemas:
        source_schema["files"] = sorted(cast(list[str], source_schema["files"]))
    manifest_payload["source_schemas"] = sorted(
        source_schemas,
        key=lambda source_schema: cast(str, source_schema["id"]),
    )
    payload = {
        "manifest": manifest_payload,
        "sources": [
            {
                "source_id": source.source_id,
                "kind": source.kind.value,
                "dialect": source.dialect,
                "source_path": source.source_path,
                "content_hash": source.content_hash,
            }
            for source in sources
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_source(content: str) -> str:
    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"
