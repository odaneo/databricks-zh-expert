from dataclasses import dataclass
from enum import StrEnum


class ArtifactType(StrEnum):
    ANSWER = "answer"
    SQL = "sql"
    CSV = "csv"
    PYSPARK = "pyspark"
    NOTEBOOK = "notebook"
    WORKFLOW_DESIGN = "workflow_design"
    DOCUMENT_SUMMARY = "document_summary"
    PROPOSAL = "proposal"
    CHECKLIST = "checklist"


@dataclass(frozen=True, slots=True)
class MarkdownArtifact:
    artifact_type: ArtifactType
    title: str
    content: str


class ArtifactValidationError(ValueError):
    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("Markdown Artifact 未通过结构校验。")
