from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from databricks_zh_expert.prompts.registry import PromptName
from databricks_zh_expert.rag.embeddings import EmbeddingResult
from databricks_zh_expert.search.markdown import MarkdownChunk


class ExpertTemplateKind(StrEnum):
    BLUEPRINT = "blueprint"
    DECISION_GUIDE = "decision_guide"
    CODE_PATTERN = "code_pattern"
    CHECKLIST = "checklist"
    DELIVERABLE = "deliverable"


class ExpertTemplateCategory(StrEnum):
    INGESTION = "ingestion"
    MEDALLION = "medallion"
    PIPELINE = "pipeline"
    WORKFLOW = "workflow"
    GOVERNANCE = "governance"
    DATA_QUALITY = "data_quality"
    SQL = "sql"
    PYSPARK = "pyspark"
    PERFORMANCE = "performance"
    COST = "cost"
    DELIVERY = "delivery"


@dataclass(frozen=True, slots=True)
class ExpertProfile:
    id: str
    display_name: str
    description: str
    cloud: str
    layers: tuple[str, ...]
    prompt_defaults: Mapping[PromptName, tuple[str, ...]]
    is_default: bool


@dataclass(frozen=True, slots=True)
class ExpertTemplateSource:
    template_id: str
    name: str
    summary: str
    version: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: str
    profile_id: str | None
    cloud: str
    prompt_names: tuple[PromptName, ...]
    tags: tuple[str, ...]
    extends_template_id: str | None
    official_refs: tuple[str, ...]
    source_path: str
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class TemplateVersionState:
    record_id: UUID
    template_id: str
    version: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class PreparedTemplateVersion:
    source: ExpertTemplateSource
    chunks: tuple[MarkdownChunk, ...]
    embeddings: tuple[EmbeddingResult, ...]


@dataclass(frozen=True, slots=True)
class PreparedTemplateSnapshot:
    source_hash: str
    templates: tuple[PreparedTemplateVersion, ...]
    active_template_ids: frozenset[str]
    synced_at: datetime


@dataclass(frozen=True, slots=True)
class SyncRunCompletion:
    status: Literal["succeeded", "failed"]
    discovered_count: int
    inserted_count: int
    activated_count: int
    inactivated_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    error_summary: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class TemplateListQuery:
    profile_id: str | None = None
    kind: ExpertTemplateKind | None = None
    category: ExpertTemplateCategory | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ExpertTemplateIndexStatus:
    latest_run_status: str | None
    source_hash_matches: bool
    active_template_count: int
    chunk_count: int
    embedding_model: str | None
    embedding_dimensions: int | None
    queryable: bool


@dataclass(frozen=True, slots=True)
class ExpertTemplateSyncResult:
    run_id: UUID | None
    source_hash: str
    dry_run: bool
    status: Literal["succeeded", "failed", "dry_run"]
    discovered_count: int
    inserted_count: int
    activated_count: int
    inactivated_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    error_summary: tuple[dict[str, str], ...]
