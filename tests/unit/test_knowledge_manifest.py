from pathlib import Path
from textwrap import dedent

import pytest

from databricks_zh_expert.rag.manifest import KnowledgeManifestError, load_manifest
from databricks_zh_expert.rag.types import (
    CatalogKind,
    KnowledgeCategory,
    SourceKind,
)


def _write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sources.yml"
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return path


def _valid_manifest() -> str:
    return """
    version: 1
    ingestion:
      chunk_size_tokens: 600
      chunk_overlap_tokens: 80
    catalogs:
      - id: databricks-docs
        kind: databricks_llms_index
        index_url: https://docs.databricks.com/llms.txt
        cloud: aws
        locale: en
        include_urls:
          - source_key: docs-delta-lake
            url: https://docs.databricks.com/delta/
            category: delta_lake
      - id: databricks-api
        kind: databricks_api_llms_index
        index_url: https://docs.databricks.com/api/llms.txt
        cloud: aws
        locale: en
        include_modules:
          - name: Jobs
            include_operations:
              - source_key: api-jobs-create
                title: Create a new job
                category: api
    """


def test_load_manifest_returns_immutable_domain_types(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest()))

    assert manifest.version == 1
    assert manifest.chunk_size_tokens == 600
    assert manifest.chunk_overlap_tokens == 80
    assert tuple(catalog.kind for catalog in manifest.catalogs) == (
        CatalogKind.DATABRICKS_DOCS,
        CatalogKind.DATABRICKS_API,
    )
    assert manifest.catalogs[0].documents[0].source_key == "docs-delta-lake"
    assert manifest.catalogs[0].documents[0].category is KnowledgeCategory.DELTA_LAKE
    assert manifest.catalogs[1].modules[0].operations[0].title == "Create a new job"
    assert SourceKind.GENERAL_HTML == "general_html"
    assert SourceKind.API_MARKDOWN == "api_markdown"


@pytest.mark.parametrize(
    ("old", "new", "expected_fragment"),
    [
        ("version: 1", "version: 2", "version"),
        ("chunk_overlap_tokens: 80", "chunk_overlap_tokens: 600", "overlap"),
        ("catalogs:", "unexpected: true\n    catalogs:", "unexpected"),
        ("kind: databricks_llms_index", "kind: unknown", "kind"),
        (
            "https://docs.databricks.com/delta/",
            "http://docs.databricks.com/delta/",
            "HTTPS",
        ),
        (
            "https://docs.databricks.com/delta/",
            "https://example.com/delta/",
            "docs.databricks.com",
        ),
    ],
)
def test_manifest_rejects_invalid_structure(
    tmp_path: Path,
    old: str,
    new: str,
    expected_fragment: str,
) -> None:
    content = _valid_manifest().replace(old, new, 1)

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert expected_fragment.lower() in str(error.value).lower()


def test_manifest_requires_catalogs(tmp_path: Path) -> None:
    content = _valid_manifest().replace(
        "catalogs:\n      - id: databricks-docs",
        "catalogs: []\n    removed_catalog:\n      - id: databricks-docs",
        1,
    )

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert "catalog" in str(error.value).lower()


def test_manifest_rejects_duplicate_catalog_ids(tmp_path: Path) -> None:
    content = _valid_manifest().replace("id: databricks-api", "id: databricks-docs", 1)

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert "catalog id" in str(error.value).lower()


def test_manifest_rejects_duplicate_source_keys_across_catalogs(tmp_path: Path) -> None:
    content = _valid_manifest().replace("api-jobs-create", "docs-delta-lake", 1)

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert "source_key" in str(error.value)


def test_api_catalog_requires_concrete_operations(tmp_path: Path) -> None:
    content = _valid_manifest().replace(
        "include_modules:\n          - name: Jobs\n            include_operations:\n"
        "              - source_key: api-jobs-create\n"
        "                title: Create a new job\n"
        "                category: api",
        "include_modules:\n          - name: Jobs\n            include_operations: []",
        1,
    )

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert "operation" in str(error.value).lower()


def test_repository_manifest_stays_within_demo_scope() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest = load_manifest(repository_root / "knowledge" / "databricks" / "sources.yml")

    docs_catalog = next(
        catalog for catalog in manifest.catalogs if catalog.kind is CatalogKind.DATABRICKS_DOCS
    )
    api_catalog = next(
        catalog for catalog in manifest.catalogs if catalog.kind is CatalogKind.DATABRICKS_API
    )
    api_operation_count = sum(len(module.operations) for module in api_catalog.modules)

    assert 25 <= len(docs_catalog.documents) <= 35
    assert 5 <= api_operation_count <= 15
