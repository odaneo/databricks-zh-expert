from pydantic import BaseModel, ConfigDict


class KnowledgeIndexStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    last_run_status: str | None
    active_document_count: int
    chunk_count: int
    embedding_model: str | None
    embedding_dimensions: int | None
    queryable: bool
