from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from databricks_zh_expert.prompts.registry import PromptName


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
    is_mock: bool
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
    is_mock: bool
    official_refs: tuple[str, ...]
    source_path: str
    content: str
    content_hash: str
