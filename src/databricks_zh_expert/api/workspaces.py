from typing import Annotated

from fastapi import APIRouter, Depends

from databricks_zh_expert.api.dependencies import get_workspace_registry
from databricks_zh_expert.api.workspace_schemas import WorkspaceResponse
from databricks_zh_expert.core.errors import WorkspaceNotFoundAppError
from databricks_zh_expert.workspace.registry import (
    WorkspaceRegistry,
    WorkspaceRegistryError,
)

router = APIRouter(prefix="/api/workspaces", tags=["项目工作区"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    registry: Annotated[WorkspaceRegistry, Depends(get_workspace_registry)],
) -> list[WorkspaceResponse]:
    return [WorkspaceResponse.from_definition(workspace) for workspace in registry.workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    registry: Annotated[WorkspaceRegistry, Depends(get_workspace_registry)],
) -> WorkspaceResponse:
    try:
        workspace = registry.get(workspace_id)
    except WorkspaceRegistryError:
        raise WorkspaceNotFoundAppError(status_code=404) from None
    return WorkspaceResponse.from_definition(workspace)
