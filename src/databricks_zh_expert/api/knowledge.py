from typing import Annotated

from fastapi import APIRouter, Depends

from databricks_zh_expert.api.dependencies import get_knowledge_repository
from databricks_zh_expert.api.knowledge_schemas import KnowledgeIndexStatusResponse
from databricks_zh_expert.rag.repository import KnowledgeRepository

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


@router.get("/index/status", response_model=KnowledgeIndexStatusResponse)
async def get_index_status(
    repository: Annotated[KnowledgeRepository, Depends(get_knowledge_repository)],
) -> KnowledgeIndexStatusResponse:
    status = await repository.get_index_status()
    return KnowledgeIndexStatusResponse.model_validate(status)
