import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml import YAMLError

from databricks_zh_expert.prompts.registry import PROMPT_SPECS, PromptName
from databricks_zh_expert.workspace.constants import (
    WORKSPACE_ALLOWED_SUFFIXES,
    WORKSPACE_ROOT,
    WORKSPACE_SOURCE_MAX_BYTES,
)
from databricks_zh_expert.workspace.types import (
    WorkspaceDefinition,
    WorkspaceSource,
    WorkspaceSourceKind,
)

_WORKSPACE_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
_SOURCE_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9._]*[a-z0-9])?$"
_SEMVER_PATTERN = r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
_MANIFEST_RELATIVE_PATH = Path(".databricks-expert/project.yml")
_FORBIDDEN_PATH_PARTS = frozenset({".git", ".venv", "node_modules"})
_FORBIDDEN_FILE_NAMES = frozenset(
    {
        ".env",
        "credentials.yml",
        "credentials.yaml",
        "secrets.yml",
        "secrets.yaml",
    }
)
_WORKSPACE_ENABLED_PROMPTS = frozenset(
    spec.name for spec in PROMPT_SPECS if spec.available and spec.code_fence_language is not None
)

WorkspaceId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_WORKSPACE_ID_PATTERN),
]
SourceId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_SOURCE_ID_PATTERN),
]
Tag = Annotated[str, Field(min_length=1, max_length=50)]


class WorkspaceRegistryError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class _SourceModel(_StrictModel):
    source_id: SourceId = Field(alias="id")
    kind: WorkspaceSourceKind
    source_path: str = Field(alias="path", min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    prompt_names: tuple[PromptName, ...] = Field(min_length=1)
    tags: tuple[Tag, ...] = Field(min_length=1, max_length=30)
    always_include: bool

    @field_validator("prompt_names")
    @classmethod
    def validate_prompt_names(cls, value: tuple[PromptName, ...]) -> tuple[PromptName, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Prompt 不能重复。")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(tag.strip().casefold().replace(" ", "_") for tag in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("标签不能重复。")
        return normalized


class _ManifestModel(_StrictModel):
    schema_version: Literal[1]
    workspace_id: WorkspaceId = Field(alias="id")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    version: str = Field(pattern=_SEMVER_PATTERN)
    cloud: Literal["aws"]
    is_mock: Literal[True]
    default_context: dict[PromptName, tuple[SourceId, ...]]
    sources: tuple[_SourceModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        for source_ids in self.default_context.values():
            if not source_ids:
                raise ValueError("默认上下文不能为空。")
            if len(source_ids) != len(set(source_ids)):
                raise ValueError("默认上下文引用不能重复。")
        return self


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
    except OSError:
        raise WorkspaceRegistryError("无法读取项目工作区目录。") from None
    if not workspace_root.is_relative_to(registry_root):
        raise WorkspaceRegistryError("项目工作区目录不能位于根目录之外。")

    manifest_path = workspace_directory / _MANIFEST_RELATIVE_PATH
    manifest_source = _read_manifest(manifest_path, workspace_root)
    manifest = _parse_manifest(manifest_source)
    _validate_manifest_contract(manifest)

    sources = tuple(
        sorted(
            (_load_source(workspace_root, source) for source in manifest.sources),
            key=lambda source: source.source_id,
        )
    )
    _validate_source_references(manifest, sources)
    default_context = MappingProxyType(
        {
            prompt_name: source_ids
            for prompt_name, source_ids in sorted(
                manifest.default_context.items(),
                key=lambda item: item[0].value,
            )
        }
    )
    return WorkspaceDefinition(
        workspace_id=manifest.workspace_id,
        display_name=manifest.display_name,
        description=manifest.description,
        version=manifest.version,
        cloud=manifest.cloud,
        is_mock=manifest.is_mock,
        source_hash=_source_hash(manifest, sources),
        default_context=default_context,
        sources=sources,
    )


def _read_manifest(path: Path, workspace_root: Path) -> str:
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        raise WorkspaceRegistryError("项目工作区清单不存在。") from None
    if not resolved_path.is_relative_to(workspace_root):
        raise WorkspaceRegistryError("项目工作区清单不能位于工作区目录之外。")
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
        if issue["type"] == "enum" and (
            "prompt_names" in location or "default_context" in location
        ):
            return "项目工作区清单的 Prompt 未注册。"
        if location and location[-1] == "id":
            if "sources" in location:
                return "项目工作区清单的 Source ID 无效。"
            return "项目工作区清单的工作区 ID 无效。"
        if location and location[-1] == "version":
            return "项目工作区版本必须使用 MAJOR.MINOR.PATCH。"
    fields = ".".join(str(part) for part in issues[0]["loc"]) if issues else "root"
    return f"项目工作区清单字段无效：{fields}。"


def _validate_manifest_contract(manifest: _ManifestModel) -> None:
    source_ids = tuple(source.source_id for source in manifest.sources)
    if len(source_ids) != len(set(source_ids)):
        raise WorkspaceRegistryError("Source ID 不能重复。")
    source_paths = tuple(source.source_path for source in manifest.sources)
    if len(source_paths) != len(set(source_paths)):
        raise WorkspaceRegistryError("Source 路径不能重复。")

    prompt_names = frozenset(manifest.default_context)
    if prompt_names != _WORKSPACE_ENABLED_PROMPTS:
        raise WorkspaceRegistryError("默认上下文必须覆盖全部已注册代码 Prompt。")
    for source in manifest.sources:
        if not set(source.prompt_names) <= _WORKSPACE_ENABLED_PROMPTS:
            raise WorkspaceRegistryError("Workspace Source 只能引用已注册代码 Prompt。")


def _load_source(workspace_root: Path, model: _SourceModel) -> WorkspaceSource:
    relative_path = _validate_source_path(model.source_path)
    candidate = workspace_root.joinpath(*relative_path.parts)
    try:
        resolved_path = candidate.resolve(strict=True)
    except OSError:
        raise WorkspaceRegistryError(f"Workspace Source 文件不存在：{model.source_id}。") from None
    if not resolved_path.is_relative_to(workspace_root):
        raise WorkspaceRegistryError("Workspace Source 不能位于工作区目录之外。")
    if not resolved_path.is_file():
        raise WorkspaceRegistryError(f"Workspace Source 不是文件：{model.source_id}。")

    try:
        if resolved_path.stat().st_size > WORKSPACE_SOURCE_MAX_BYTES:
            raise WorkspaceRegistryError(f"Workspace Source 超过最大大小：{model.source_id}。")
        source_bytes = resolved_path.read_bytes()
    except WorkspaceRegistryError:
        raise
    except OSError:
        raise WorkspaceRegistryError(f"无法读取 Workspace Source：{model.source_id}。") from None
    if len(source_bytes) > WORKSPACE_SOURCE_MAX_BYTES:
        raise WorkspaceRegistryError(f"Workspace Source 超过最大大小：{model.source_id}。")
    try:
        content = _normalize_source(source_bytes.decode("utf-8"))
    except UnicodeError:
        raise WorkspaceRegistryError(
            f"Workspace Source 必须使用 UTF-8：{model.source_id}。"
        ) from None

    return WorkspaceSource(
        source_id=model.source_id,
        kind=model.kind,
        title=model.title,
        summary=model.summary,
        prompt_names=model.prompt_names,
        tags=model.tags,
        always_include=model.always_include,
        source_path=relative_path.as_posix(),
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _validate_source_path(source_path: str) -> PurePosixPath:
    windows_path = PureWindowsPath(source_path)
    posix_path = PurePosixPath(source_path)
    if "\\" in source_path or windows_path.is_absolute() or posix_path.is_absolute():
        raise WorkspaceRegistryError("Workspace Source 必须使用工作区相对路径。")
    if ".." in posix_path.parts:
        raise WorkspaceRegistryError("Workspace Source 路径不能包含 ..。")
    if posix_path.as_posix() != source_path:
        raise WorkspaceRegistryError("Workspace Source 必须使用规范的 POSIX 相对路径。")
    if posix_path.suffix.casefold() not in WORKSPACE_ALLOWED_SUFFIXES:
        raise WorkspaceRegistryError("Workspace Source 文件类型不允许。")

    lowered_parts = tuple(part.casefold() for part in posix_path.parts)
    if any(part in _FORBIDDEN_PATH_PARTS for part in lowered_parts):
        raise WorkspaceRegistryError("Workspace Source 路径包含禁止目录。")
    file_name = lowered_parts[-1]
    if (
        file_name in _FORBIDDEN_FILE_NAMES
        or file_name.startswith(".env.")
        or "private_key" in file_name
    ):
        raise WorkspaceRegistryError("Workspace Source 不允许读取凭据或私密文件。")
    return posix_path


def _validate_source_references(
    manifest: _ManifestModel,
    sources: tuple[WorkspaceSource, ...],
) -> None:
    sources_by_id = {source.source_id: source for source in sources}
    for prompt_name, source_ids in manifest.default_context.items():
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            if source is None:
                raise WorkspaceRegistryError("默认上下文引用不存在的 Source。")
            if prompt_name not in source.prompt_names:
                raise WorkspaceRegistryError("默认上下文引用的 Source 不支持对应 Prompt。")


def _source_hash(
    manifest: _ManifestModel,
    sources: tuple[WorkspaceSource, ...],
) -> str:
    manifest_payload = cast(dict[str, Any], manifest.model_dump(mode="json", by_alias=True))
    manifest_payload["default_context"] = {
        key: value
        for key, value in sorted(cast(dict[str, Any], manifest_payload["default_context"]).items())
    }
    manifest_payload["sources"] = sorted(
        cast(list[dict[str, Any]], manifest_payload["sources"]),
        key=lambda source: cast(str, source["id"]),
    )
    payload = {
        "manifest": manifest_payload,
        "sources": [
            {
                "source_id": source.source_id,
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
