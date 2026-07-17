from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from databricks_zh_expert.prompts.registry import PromptName


class WorkspaceSourceKind(StrEnum):
    PROJECT = "project"
    SCHEMA = "schema"
    MAPPING = "mapping"
    RULE = "rule"
    DDL = "ddl"
    CODE = "code"
    BUNDLE = "bundle"


@dataclass(frozen=True, slots=True)
class WorkspaceSource:
    source_id: str
    kind: WorkspaceSourceKind
    title: str
    summary: str
    prompt_names: tuple[PromptName, ...]
    tags: tuple[str, ...]
    always_include: bool
    source_path: str
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class WorkspaceDefinition:
    workspace_id: str
    display_name: str
    description: str
    version: str
    cloud: str
    is_mock: bool
    source_hash: str
    default_context: Mapping[PromptName, tuple[str, ...]]
    sources: tuple[WorkspaceSource, ...]
