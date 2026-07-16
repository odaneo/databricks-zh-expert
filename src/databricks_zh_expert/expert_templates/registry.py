import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self
from urllib.parse import urlparse

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml import YAMLError

from databricks_zh_expert.expert_templates.constants import EXPERT_TEMPLATE_ROOT
from databricks_zh_expert.expert_templates.types import (
    ExpertProfile,
    ExpertTemplateCategory,
    ExpertTemplateKind,
    ExpertTemplateSource,
)
from databricks_zh_expert.prompts.registry import PROMPT_SPECS, PromptName

_TEMPLATE_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9._]*[a-z0-9])?$"
_PROFILE_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
_SEMVER_PATTERN = r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
_JINJA_MARKERS = ("{{", "{%", "{#")
_DELIVERY_SECTION_MARKERS = ("决策", "步骤", "检查", "交付")
_EXPERT_ENABLED_PROMPTS = (
    PromptName.DATABRICKS_QA,
    PromptName.SQL_GENERATION,
    PromptName.PYSPARK_GENERATION,
    PromptName.WORKFLOW_DESIGN,
    PromptName.PROPOSAL_GENERATION,
    PromptName.SELF_CHECK,
)
_AVAILABLE_PROMPTS = frozenset(spec.name for spec in PROMPT_SPECS if spec.available)

TemplateId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_TEMPLATE_ID_PATTERN),
]
ProfileId = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=_PROFILE_ID_PATTERN),
]
Tag = Annotated[str, Field(min_length=1, max_length=50)]


class ExpertTemplateRegistryError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class _ProfileModel(_StrictModel):
    id: ProfileId
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    cloud: Literal["neutral", "aws"]
    layers: tuple[ProfileId, ...] = Field(min_length=1)
    is_mock: bool
    is_default: bool = Field(alias="default")
    prompt_defaults: dict[PromptName, tuple[TemplateId, ...]]

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        if len(self.layers) != len(set(self.layers)):
            raise ValueError("Profile layers 不能重复。")
        for template_ids in self.prompt_defaults.values():
            if not template_ids:
                raise ValueError("Prompt 默认模板不能为空。")
            if len(template_ids) != len(set(template_ids)):
                raise ValueError("Prompt 默认模板不能重复。")
        return self


class _ProfilesFileModel(_StrictModel):
    version: Literal[1]
    profiles: tuple[_ProfileModel, ...] = Field(min_length=1)


class _TemplateModel(_StrictModel):
    id: TemplateId
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    version: str = Field(pattern=_SEMVER_PATTERN)
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: ProfileId
    profile: ProfileId | None
    cloud: Literal["neutral", "aws"]
    prompt_names: tuple[PromptName, ...] = Field(min_length=1)
    tags: tuple[Tag, ...] = Field(min_length=1, max_length=20)
    extends: TemplateId | None
    is_mock: bool
    official_refs: tuple[str, ...]

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

    @field_validator("official_refs")
    @classmethod
    def validate_official_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for reference in value:
            parsed = urlparse(reference)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("维护参考必须使用 HTTPS URL。")
        return value


class _ParsedTemplate:
    def __init__(
        self,
        *,
        model: _TemplateModel,
        source_path: str,
        normalized_source: str,
        content: str,
    ) -> None:
        self.model = model
        self.source_path = source_path
        self.normalized_source = normalized_source
        self.content = content


class ExpertTemplateRegistry:
    def __init__(
        self,
        *,
        profiles: tuple[ExpertProfile, ...],
        templates: tuple[ExpertTemplateSource, ...],
        default_profile_id: str,
        source_hash: str,
    ) -> None:
        self._profiles = profiles
        self._templates = templates
        self._default_profile_id = default_profile_id
        self._source_hash = source_hash
        self._profiles_by_id = MappingProxyType({profile.id: profile for profile in profiles})
        self._templates_by_id = MappingProxyType(
            {template.template_id: template for template in templates}
        )

    @property
    def profiles(self) -> tuple[ExpertProfile, ...]:
        return self._profiles

    @property
    def templates(self) -> tuple[ExpertTemplateSource, ...]:
        return self._templates

    @property
    def default_profile_id(self) -> str:
        return self._default_profile_id

    @property
    def source_hash(self) -> str:
        return self._source_hash

    @classmethod
    def create_default(cls) -> "ExpertTemplateRegistry":
        return cls.load(EXPERT_TEMPLATE_ROOT)

    @classmethod
    def load(cls, root: Path) -> "ExpertTemplateRegistry":
        if not root.is_dir():
            raise ExpertTemplateRegistryError("专家模板根目录不存在。")

        profiles_source = _read_source(root / "profiles.yml", root)
        profile_models = _parse_profiles(profiles_source)
        parsed_templates = _load_templates(root)
        _validate_registry(profile_models, parsed_templates)

        profiles = tuple(_to_profile(profile) for profile in profile_models)
        templates = tuple(
            sorted(
                (_to_template(template) for template in parsed_templates),
                key=lambda item: item.template_id,
            )
        )
        default_profile_id = next(profile.id for profile in profiles if profile.is_default)
        source_hash = _source_hash(profiles_source, parsed_templates)
        return cls(
            profiles=profiles,
            templates=templates,
            default_profile_id=default_profile_id,
            source_hash=source_hash,
        )

    def get_profile(self, profile_id: str) -> ExpertProfile:
        try:
            return self._profiles_by_id[profile_id]
        except KeyError:
            raise ExpertTemplateRegistryError("专家 Profile 未注册。") from None

    def get_template(self, template_id: str) -> ExpertTemplateSource:
        try:
            return self._templates_by_id[template_id]
        except KeyError:
            raise ExpertTemplateRegistryError("专家模板未注册。") from None


def _normalize_source(content: str) -> str:
    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read_source(path: Path, root: Path) -> str:
    label = _relative_path(path, root)
    try:
        return _normalize_source(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        raise ExpertTemplateRegistryError(f"无法读取专家模板源文件：{label}。") from None


def _safe_yaml_load(content: str, *, label: str) -> object:
    try:
        return yaml.safe_load(content)
    except YAMLError:
        raise ExpertTemplateRegistryError(f"{label}不是合法 YAML。") from None


def _parse_profiles(source: str) -> tuple[_ProfileModel, ...]:
    payload = _safe_yaml_load(source, label="Profile 清单")
    try:
        model = _ProfilesFileModel.model_validate(payload)
    except ValidationError as error:
        raise ExpertTemplateRegistryError(
            _validation_message(error, label="Profile 清单")
        ) from None
    return model.profiles


def _load_templates(root: Path) -> tuple[_ParsedTemplate, ...]:
    paths = sorted(
        (path for path in root.rglob("*.md") if path.is_file()),
        key=lambda path: _relative_path(path, root),
    )
    if not paths:
        raise ExpertTemplateRegistryError("专家模板目录中没有 Markdown 资产。")
    return tuple(_parse_template(path, root) for path in paths)


def _parse_template(path: Path, root: Path) -> _ParsedTemplate:
    source_path = _relative_path(path, root)
    normalized_source = _read_source(path, root)
    front_matter, content = _split_front_matter(normalized_source, source_path)
    payload = _safe_yaml_load(front_matter, label=f"模板 {source_path} 的 Front Matter")
    try:
        model = _TemplateModel.model_validate(payload)
    except ValidationError as error:
        message = _validation_message(error, label=f"模板 {source_path}")
        raise ExpertTemplateRegistryError(message) from None

    if any(prompt not in _AVAILABLE_PROMPTS for prompt in model.prompt_names):
        raise ExpertTemplateRegistryError(f"模板 {source_path} 引用了不可用的 Prompt。")
    _validate_markdown(model, content, source_path)
    return _ParsedTemplate(
        model=model,
        source_path=source_path,
        normalized_source=normalized_source,
        content=content,
    )


def _split_front_matter(source: str, source_path: str) -> tuple[str, str]:
    lines = source.split("\n")
    if not lines or lines[0] != "---":
        raise ExpertTemplateRegistryError(f"模板 {source_path} 缺少 YAML Front Matter。")
    try:
        end_index = lines.index("---", 1)
    except ValueError:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的 Front Matter 未闭合。") from None

    front_matter = "\n".join(lines[1:end_index]).strip()
    content = "\n".join(lines[end_index + 1 :]).strip()
    if not front_matter:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的 Front Matter 不能为空。")
    if not content:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的 Markdown 正文不能为空。")
    if len(content) > 100_000:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的 Markdown 正文超过长度上限。")
    return front_matter, content + "\n"


def _validation_message(error: ValidationError, *, label: str) -> str:
    issues = error.errors(include_url=False, include_input=False)
    if any(issue["type"] == "extra_forbidden" for issue in issues):
        return f"{label}包含未知字段。"
    for issue in issues:
        location = tuple(str(part) for part in issue["loc"])
        if issue["type"] == "enum" and (
            "prompt_names" in location or "prompt_defaults" in location
        ):
            return f"{label}的 Prompt 未注册。"
        if location and location[-1] == "version" and label.startswith("模板 "):
            return f"{label}的版本必须使用 MAJOR.MINOR.PATCH。"
    fields = ".".join(str(part) for part in issues[0]["loc"]) if issues else "root"
    return f"{label}字段无效：{fields}。"


def _validate_markdown(model: _TemplateModel, content: str, source_path: str) -> None:
    if _contains_nested_front_matter(content):
        raise ExpertTemplateRegistryError(f"模板 {source_path} 禁止嵌套 Front Matter。")
    if any(marker in content for marker in _JINJA_MARKERS):
        raise ExpertTemplateRegistryError(f"模板 {source_path} 禁止 Jinja 表达式。")
    _validate_fence_closure(content, source_path)

    tokens = MarkdownIt("commonmark").parse(content)
    if _contains_html(tokens):
        raise ExpertTemplateRegistryError(f"模板 {source_path} 禁止原始 HTML。")

    headings = _headings(tokens)
    h1_titles = tuple(title for level, title in headings if level == 1)
    if len(h1_titles) != 1:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 只能包含一个一级标题。")
    if h1_titles[0] != model.name:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的一级标题必须等于模板名称。")

    section_titles = tuple(title for level, title in headings if level >= 2)
    if model.kind is ExpertTemplateKind.CODE_PATTERN:
        _validate_code_pattern(model, tokens, source_path)
        return
    if "适用场景" not in section_titles:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 必须包含“适用场景”章节。")
    if not any(marker in title for title in section_titles for marker in _DELIVERY_SECTION_MARKERS):
        raise ExpertTemplateRegistryError(
            f"模板 {source_path} 必须包含决策、步骤、检查或交付章节。"
        )


def _contains_nested_front_matter(content: str) -> bool:
    lines = content.split("\n")
    delimiters = [index for index, line in enumerate(lines) if line.strip() == "---"]
    for start_index, end_index in zip(delimiters, delimiters[1:], strict=False):
        candidate = "\n".join(lines[start_index + 1 : end_index]).strip()
        if not candidate:
            continue
        try:
            payload = yaml.safe_load(candidate)
        except YAMLError:
            continue
        if isinstance(payload, dict):
            return True
    return False


def _contains_html(tokens: list[Token]) -> bool:
    for token in tokens:
        if token.type in {"html_block", "html_inline"}:
            return True
        if token.children and _contains_html(token.children):
            return True
    return False


def _headings(tokens: list[Token]) -> tuple[tuple[int, str], ...]:
    headings: list[tuple[int, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or index + 1 >= len(tokens):
            continue
        inline = tokens[index + 1]
        if inline.type != "inline" or not token.tag.startswith("h"):
            continue
        headings.append((int(token.tag[1:]), inline.content.strip()))
    return tuple(headings)


def _validate_fence_closure(content: str, source_path: str) -> None:
    opening: tuple[str, int] | None = None
    for line in content.split("\n"):
        if opening is None:
            match = re.match(r"^ {0,3}(`{3,}|~{3,})(?:[^`]*)$", line)
            if match:
                marker = match.group(1)
                opening = (marker[0], len(marker))
            continue

        marker_character, minimum_length = opening
        if re.match(
            rf"^ {{0,3}}{re.escape(marker_character)}{{{minimum_length},}}[ \t]*$",
            line,
        ):
            opening = None
    if opening is not None:
        raise ExpertTemplateRegistryError(f"模板 {source_path} 的代码围栏必须闭合。")


def _validate_code_pattern(
    model: _TemplateModel,
    tokens: list[Token],
    source_path: str,
) -> None:
    languages = {
        token.info.strip().split(maxsplit=1)[0].casefold()
        for token in tokens
        if token.type == "fence" and token.info.strip()
    }
    if model.category is ExpertTemplateCategory.SQL:
        expected_languages = frozenset({"sql"})
        expected_label = "sql"
    elif model.category in {
        ExpertTemplateCategory.PYSPARK,
        ExpertTemplateCategory.DATA_QUALITY,
    }:
        expected_languages = frozenset({"python"})
        expected_label = "python"
    else:
        expected_languages = frozenset({"sql", "python"})
        expected_label = "sql 或 python"
    if languages.isdisjoint(expected_languages):
        raise ExpertTemplateRegistryError(
            f"模板 {source_path} 必须包含 {expected_label} 代码围栏。"
        )


def _validate_registry(
    profiles: tuple[_ProfileModel, ...],
    templates: tuple[_ParsedTemplate, ...],
) -> None:
    profiles_by_id = _validate_profiles(profiles)
    templates_by_id = _validate_template_ownership(templates, profiles_by_id)
    _validate_inheritance(templates_by_id)
    _validate_prompt_defaults(profiles, templates_by_id)


def _validate_profiles(profiles: tuple[_ProfileModel, ...]) -> Mapping[str, _ProfileModel]:
    profiles_by_id = {profile.id: profile for profile in profiles}
    if len(profiles_by_id) != len(profiles):
        raise ExpertTemplateRegistryError("Profile ID 不能重复。")
    generic = profiles_by_id.get("generic")
    if generic is None:
        raise ExpertTemplateRegistryError("Profile 清单必须包含 generic。")
    defaults = tuple(profile for profile in profiles if profile.is_default)
    if len(defaults) != 1 or defaults[0].id != "generic":
        raise ExpertTemplateRegistryError("generic 必须是唯一默认 Profile。")
    if generic.layers != ("core",) or generic.cloud != "neutral" or generic.is_mock:
        raise ExpertTemplateRegistryError(
            "generic Profile 必须使用 neutral core 且不能标记为 Mock。"
        )

    required_prompts = frozenset(_EXPERT_ENABLED_PROMPTS)
    for profile in profiles:
        if profile.layers[0] != "core":
            raise ExpertTemplateRegistryError("Profile layers 必须以 core 开头。")
        allowed_layers = {"core", profile.id}
        if not set(profile.layers) <= allowed_layers:
            raise ExpertTemplateRegistryError("Profile 只能声明 core 和自身覆盖层。")
        if profile.id != "generic" and profile.id not in profile.layers:
            raise ExpertTemplateRegistryError("非 generic Profile 必须声明自身覆盖层。")
        if frozenset(profile.prompt_defaults) != required_prompts:
            raise ExpertTemplateRegistryError("Profile 必须为全部专家 Prompt 配置默认模板。")
    return MappingProxyType(profiles_by_id)


def _validate_template_ownership(
    templates: tuple[_ParsedTemplate, ...],
    profiles_by_id: Mapping[str, _ProfileModel],
) -> Mapping[str, _ParsedTemplate]:
    templates_by_id = {template.model.id: template for template in templates}
    if len(templates_by_id) != len(templates):
        raise ExpertTemplateRegistryError("专家模板 ID 不能重复。")

    for template in templates:
        model = template.model
        if model.layer == "core":
            if model.profile is not None or model.is_mock:
                raise ExpertTemplateRegistryError("core 模板不能绑定 Profile 或标记为 Mock。")
            if not template.source_path.startswith("core/"):
                raise ExpertTemplateRegistryError("core 模板必须位于 core 目录。")
            continue

        profile = profiles_by_id.get(model.layer)
        if profile is None:
            raise ExpertTemplateRegistryError("覆盖层模板引用了未注册的 Profile。")
        if model.profile != model.layer:
            raise ExpertTemplateRegistryError("覆盖层模板的 profile 必须等于 layer。")
        if model.is_mock != profile.is_mock:
            raise ExpertTemplateRegistryError("覆盖层模板的 Mock 标识必须与 Profile 一致。")
        if model.cloud != profile.cloud:
            raise ExpertTemplateRegistryError("覆盖层模板的 cloud 必须与 Profile 一致。")
        expected_prefix = f"overlays/{model.layer}/"
        if not template.source_path.startswith(expected_prefix):
            raise ExpertTemplateRegistryError("覆盖层模板目录必须与 Profile 一致。")
    return MappingProxyType(templates_by_id)


def _validate_inheritance(templates_by_id: Mapping[str, _ParsedTemplate]) -> None:
    for template in templates_by_id.values():
        parent_id = template.model.extends
        if parent_id is None:
            continue
        parent = templates_by_id.get(parent_id)
        if parent is None:
            raise ExpertTemplateRegistryError("模板 extends 引用了不存在的 core 模板。")
        if template.model.layer != "core" and parent.model.layer != "core":
            raise ExpertTemplateRegistryError("覆盖层只能扩展 core 模板。")
        if template.model.layer == "core" and parent.model.layer != "core":
            raise ExpertTemplateRegistryError("core 模板只能扩展 core 模板。")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(template_id: str) -> None:
        if template_id in visiting:
            raise ExpertTemplateRegistryError("模板继承存在循环。")
        if template_id in visited:
            return
        visiting.add(template_id)
        parent_id = templates_by_id[template_id].model.extends
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(template_id)
        visited.add(template_id)

    for template_id in templates_by_id:
        visit(template_id)


def _validate_prompt_defaults(
    profiles: tuple[_ProfileModel, ...],
    templates_by_id: Mapping[str, _ParsedTemplate],
) -> None:
    for profile in profiles:
        for prompt_name, template_ids in profile.prompt_defaults.items():
            for template_id in template_ids:
                template = templates_by_id.get(template_id)
                if template is None:
                    raise ExpertTemplateRegistryError("Profile 默认模板未注册。")
                model = template.model
                if prompt_name not in model.prompt_names:
                    raise ExpertTemplateRegistryError("Profile 默认模板未声明对应 Prompt。")
                if model.layer not in profile.layers:
                    raise ExpertTemplateRegistryError("Profile 默认模板不属于允许的层。")
                if model.cloud not in {"neutral", profile.cloud}:
                    raise ExpertTemplateRegistryError("Profile 默认模板与 cloud 不兼容。")


def _to_profile(model: _ProfileModel) -> ExpertProfile:
    defaults = MappingProxyType(
        {
            prompt_name: tuple(template_ids)
            for prompt_name, template_ids in model.prompt_defaults.items()
        }
    )
    return ExpertProfile(
        id=model.id,
        display_name=model.display_name,
        description=model.description,
        cloud=model.cloud,
        layers=tuple(model.layers),
        prompt_defaults=defaults,
        is_mock=model.is_mock,
        is_default=model.is_default,
    )


def _to_template(parsed: _ParsedTemplate) -> ExpertTemplateSource:
    model = parsed.model
    metadata = {
        "category": model.category.value,
        "cloud": model.cloud,
        "extends": model.extends,
        "id": model.id,
        "is_mock": model.is_mock,
        "kind": model.kind.value,
        "layer": model.layer,
        "name": model.name,
        "official_refs": model.official_refs,
        "profile": model.profile,
        "prompt_names": tuple(prompt.value for prompt in model.prompt_names),
        "summary": model.summary,
        "tags": model.tags,
        "version": model.version,
    }
    canonical_metadata = json.dumps(
        metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    content_hash = hashlib.sha256(f"{canonical_metadata}\n{parsed.content}".encode()).hexdigest()
    return ExpertTemplateSource(
        template_id=model.id,
        name=model.name,
        summary=model.summary,
        version=model.version,
        kind=model.kind,
        category=model.category,
        layer=model.layer,
        profile_id=model.profile,
        cloud=model.cloud,
        prompt_names=tuple(model.prompt_names),
        tags=tuple(model.tags),
        extends_template_id=model.extends,
        is_mock=model.is_mock,
        official_refs=tuple(model.official_refs),
        source_path=parsed.source_path,
        content=parsed.content,
        content_hash=content_hash,
    )


def _source_hash(
    profiles_source: str,
    templates: tuple[_ParsedTemplate, ...],
) -> str:
    digest = hashlib.sha256()
    sources = [("profiles.yml", profiles_source)]
    sources.extend((template.source_path, template.normalized_source) for template in templates)
    for source_path, content in sorted(sources):
        digest.update(source_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
