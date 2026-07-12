from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from yaml import YAMLError

from databricks_zh_expert.rag.types import (
    ApiModuleSpec,
    ApiOperationSpec,
    CatalogKind,
    GeneralDocumentSpec,
    KnowledgeCategory,
    KnowledgeManifest,
    SourceCatalog,
)

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


def _validate_official_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise ValueError("Databricks URL 必须使用 HTTPS。")
    if parsed.hostname != "docs.databricks.com":
        raise ValueError("Databricks URL 必须属于 docs.databricks.com。")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise ValueError("Databricks URL 不能包含凭据或自定义端口。")
    if parsed.query or parsed.fragment:
        raise ValueError("Databricks URL 不能包含 query 或 fragment。")
    return value


class _IngestionModel(_StrictModel):
    chunk_size_tokens: int = Field(gt=0, le=8192)
    chunk_overlap_tokens: int = Field(ge=0, le=4096)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk overlap 必须小于 chunk size。")
        return self


class _GeneralDocumentModel(_StrictModel):
    source_key: StableKey
    url: str
    category: KnowledgeCategory

    _official_url = field_validator("url")(_validate_official_url)


class _ApiOperationModel(_StrictModel):
    source_key: StableKey
    title: str = Field(min_length=1, max_length=200)
    category: KnowledgeCategory


class _ApiModuleModel(_StrictModel):
    name: str = Field(min_length=1, max_length=100)
    include_operations: tuple[_ApiOperationModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_operation_titles(self) -> Self:
        titles = [operation.title.casefold() for operation in self.include_operations]
        if len(titles) != len(set(titles)):
            raise ValueError("API module 不能包含重复 operation title。")
        return self


class _CatalogModel(_StrictModel):
    id: StableKey
    kind: CatalogKind
    index_url: str
    cloud: Literal["aws"]
    locale: Literal["en"]
    include_urls: tuple[_GeneralDocumentModel, ...] = ()
    include_modules: tuple[_ApiModuleModel, ...] = ()

    _official_index_url = field_validator("index_url")(_validate_official_url)

    @model_validator(mode="after")
    def validate_catalog_shape(self) -> Self:
        if self.kind is CatalogKind.DATABRICKS_DOCS:
            if self.index_url != "https://docs.databricks.com/llms.txt":
                raise ValueError("通用文档目录必须使用官方 llms.txt。")
            if not self.include_urls:
                raise ValueError("通用文档 catalog 必须包含 include_urls。")
            if self.include_modules:
                raise ValueError("通用文档 catalog 不能包含 API module。")
            urls = [document.url for document in self.include_urls]
            if len(urls) != len(set(urls)):
                raise ValueError("通用文档 catalog 不能包含重复 URL。")
            return self

        if self.index_url != "https://docs.databricks.com/api/llms.txt":
            raise ValueError("API 文档目录必须使用官方 api/llms.txt。")
        if not self.include_modules:
            raise ValueError("API catalog 必须包含具体 module 和 operation。")
        if self.include_urls:
            raise ValueError("API catalog 不能包含通用文档 URL。")
        module_names = [module.name.casefold() for module in self.include_modules]
        if len(module_names) != len(set(module_names)):
            raise ValueError("API catalog 不能包含重复 module。")
        return self


class _ManifestModel(_StrictModel):
    version: Literal[1]
    ingestion: _IngestionModel
    catalogs: tuple[_CatalogModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> Self:
        catalog_ids = [catalog.id for catalog in self.catalogs]
        if len(catalog_ids) != len(set(catalog_ids)):
            raise ValueError("catalog id 不能重复。")

        source_keys = [
            document.source_key for catalog in self.catalogs for document in catalog.include_urls
        ]
        source_keys.extend(
            operation.source_key
            for catalog in self.catalogs
            for module in catalog.include_modules
            for operation in module.include_operations
        )
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("source_key 不能重复。")
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
        documents = tuple(
            GeneralDocumentSpec(
                source_key=document.source_key,
                url=document.url,
                category=document.category,
            )
            for document in catalog.include_urls
        )
        modules = tuple(
            ApiModuleSpec(
                name=module.name,
                operations=tuple(
                    ApiOperationSpec(
                        source_key=operation.source_key,
                        title=operation.title,
                        category=operation.category,
                    )
                    for operation in module.include_operations
                ),
            )
            for module in catalog.include_modules
        )
        catalogs.append(
            SourceCatalog(
                id=catalog.id,
                kind=catalog.kind,
                index_url=catalog.index_url,
                cloud=catalog.cloud,
                locale=catalog.locale,
                documents=documents,
                modules=modules,
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
