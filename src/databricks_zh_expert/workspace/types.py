from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class WorkspaceSourceKind(StrEnum):
    REQUIREMENT = "requirement"
    SOURCE_DDL = "source_ddl"
    RULE = "rule"


class WorkspaceContextPurpose(StrEnum):
    DDL = "ddl_generation"
    MAPPING = "mapping_generation"
    SQL = "sql_generation"
    PYSPARK = "pyspark_generation"
    NOTEBOOK = "notebook_generation"
    WORKFLOW = "workflow_design"


@dataclass(frozen=True, slots=True)
class WorkspaceSource:
    source_id: str
    kind: WorkspaceSourceKind
    dialect: str | None
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
    source_hash: str
    sources: tuple[WorkspaceSource, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceContextUnit:
    unit_id: str
    source_id: str
    kind: WorkspaceSourceKind
    dialect: str | None
    source_path: str
    title: str
    content: str
    content_hash: str
    order: int


@dataclass(frozen=True, slots=True)
class WorkspaceContextCandidate:
    rank: int
    unit_id: str
    source_id: str
    kind: WorkspaceSourceKind
    source_path: str
    content_hash: str
    score: float
    selected: bool


@dataclass(frozen=True, slots=True)
class WorkspaceContextSelection:
    unit_id: str
    source_id: str
    kind: WorkspaceSourceKind
    source_path: str
    content_hash: str
    rank: int
    reason: Literal["lexical", "fallback"]


@dataclass(frozen=True, slots=True)
class WorkspaceContextBundle:
    workspace_id: str
    workspace_version: str
    workspace_source_hash: str
    query: str
    purpose: WorkspaceContextPurpose
    ranked_candidates: tuple[WorkspaceContextCandidate, ...]
    selected_units: tuple[WorkspaceContextSelection, ...]
    context: str
    context_token_count: int
