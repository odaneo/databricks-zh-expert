from pydantic import BaseModel

from databricks_zh_expert.workspace.types import WorkspaceDefinition


class WorkspaceResponse(BaseModel):
    id: str
    display_name: str
    description: str
    version: str
    cloud: str
    source_count: int
    source_hash: str
    source_paths: list[str]

    @classmethod
    def from_definition(cls, workspace: WorkspaceDefinition) -> "WorkspaceResponse":
        return cls(
            id=workspace.workspace_id,
            display_name=workspace.display_name,
            description=workspace.description,
            version=workspace.version,
            cloud=workspace.cloud,
            source_count=len(workspace.sources),
            source_hash=workspace.source_hash,
            source_paths=sorted(source.source_path for source in workspace.sources),
        )
