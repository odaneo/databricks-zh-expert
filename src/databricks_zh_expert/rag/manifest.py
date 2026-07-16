from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml import YAMLError

from databricks_zh_expert.rag.types import (
    CatalogKind,
    KnowledgeManifest,
    SourceCatalog,
)
from databricks_zh_expert.rag.urls import validate_official_url

StableKey = Annotated[
    str,
    Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    ),
]


class KnowledgeManifestError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _IngestionModel(_StrictModel):
    chunk_size_tokens: int = Field(gt=0, le=8192)
    chunk_overlap_tokens: int = Field(ge=0, le=4096)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk overlap 必须小于 chunk size。")
        return self


class _CatalogModel(_StrictModel):
    id: StableKey
    kind: CatalogKind
    index_url: str
    cloud: Literal["aws"]
    locale: Literal["en"]

    _official_index_url = field_validator("index_url")(validate_official_url)

    @model_validator(mode="after")
    def validate_catalog_shape(self) -> Self:
        if self.kind is CatalogKind.DATABRICKS_DOCS:
            if self.index_url != "https://docs.databricks.com/llms.txt":
                raise ValueError("通用文档目录必须使用官方 llms.txt。")
            return self

        if self.index_url != "https://docs.databricks.com/api/llms.txt":
            raise ValueError("API 文档目录必须使用官方 api/llms.txt。")
        return self


class _ManifestModel(_StrictModel):
    version: Literal[2]
    ingestion: _IngestionModel
    catalogs: tuple[_CatalogModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> Self:
        catalog_ids = [catalog.id for catalog in self.catalogs]
        if len(catalog_ids) != len(set(catalog_ids)):
            raise ValueError("catalog id 不能重复。")

        return self


def _format_validation_error(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)


def _to_domain(model: _ManifestModel) -> KnowledgeManifest:
    catalogs = []
    for catalog in model.catalogs:
        catalogs.append(
            SourceCatalog(
                id=catalog.id,
                kind=catalog.kind,
                index_url=catalog.index_url,
                cloud=catalog.cloud,
                locale=catalog.locale,
            )
        )

    return KnowledgeManifest(
        version=model.version,
        chunk_size_tokens=model.ingestion.chunk_size_tokens,
        chunk_overlap_tokens=model.ingestion.chunk_overlap_tokens,
        catalogs=tuple(catalogs),
    )


def load_manifest(path: Path) -> KnowledgeManifest:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise KnowledgeManifestError(f"无法读取知识来源清单：{path}") from error
    except YAMLError as error:
        raise KnowledgeManifestError(f"知识来源清单不是合法 YAML：{path}") from error

    try:
        model = _ManifestModel.model_validate(payload)
    except ValidationError as error:
        details = _format_validation_error(error)
        raise KnowledgeManifestError(f"知识来源清单无效：{details}") from None
    return _to_domain(model)
