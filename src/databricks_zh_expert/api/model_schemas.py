from pydantic import BaseModel

from databricks_zh_expert.llm.model_registry import ModelAlias, ModelProvider


class ModelInfoResponse(BaseModel):
    alias: ModelAlias
    display_name: str
    provider: ModelProvider
    configured: bool


class ModelListResponse(BaseModel):
    default_model: ModelAlias
    fallback_models: list[ModelAlias]
    models: list[ModelInfoResponse]
