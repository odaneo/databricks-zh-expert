from pathlib import Path
from textwrap import dedent

import pytest

from databricks_zh_expert.rag.manifest import KnowledgeManifestError, load_manifest
from databricks_zh_expert.rag.types import CatalogKind, SourceKind


def _write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sources.yml"
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return path


def _valid_manifest() -> str:
    return """
    version: 2
    ingestion:
      chunk_size_tokens: 600
      chunk_overlap_tokens: 80
    catalogs:
      - id: databricks-docs
        kind: databricks_llms_index
        index_url: https://docs.databricks.com/llms.txt
        cloud: aws
        locale: en
      - id: databricks-api
        kind: databricks_api_llms_index
        index_url: https://docs.databricks.com/api/llms.txt
        cloud: aws
        locale: en
    """


def test_load_manifest_returns_catalog_only_domain_types(tmp_path: Path) -> None:
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest()))

    assert manifest.version == 2
    assert manifest.chunk_size_tokens == 600
    assert manifest.chunk_overlap_tokens == 80
    assert tuple(catalog.kind for catalog in manifest.catalogs) == (
        CatalogKind.DATABRICKS_DOCS,
        CatalogKind.DATABRICKS_API,
    )
    assert manifest.catalogs[0].index_url == "https://docs.databricks.com/llms.txt"
    assert not hasattr(manifest.catalogs[0], "documents")
    assert not hasattr(manifest.catalogs[1], "modules")
    assert SourceKind.GENERAL_HTML == "general_html"
    assert SourceKind.API_MARKDOWN == "api_markdown"


@pytest.mark.parametrize(
    ("old", "new", "expected_fragment"),
    [
        ("version: 2", "version: 1", "version"),
        ("chunk_overlap_tokens: 80", "chunk_overlap_tokens: 600", "overlap"),
        ("catalogs:", "unexpected: true\n    catalogs:", "unexpected"),
        ("kind: databricks_llms_index", "kind: unknown", "kind"),
        (
            "https://docs.databricks.com/llms.txt",
            "http://docs.databricks.com/llms.txt",
            "HTTPS",
        ),
        (
            "https://docs.databricks.com/llms.txt",
            "https://example.com/llms.txt",
            "docs.databricks.com",
        ),
        (
            "https://docs.databricks.com/llms.txt",
            "https://docs.databricks.com/other.txt",
            "llms.txt",
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


@pytest.mark.parametrize(
    "legacy_config",
    [
        """
        include_urls:
          - source_key: docs-delta-lake
            url: https://docs.databricks.com/delta/
            category: delta_lake
        """,
        """
        include_modules:
          - name: Jobs
            include_operations:
              - source_key: api-jobs-create
                title: Create
                category: api
        """,
    ],
)
def test_manifest_rejects_legacy_source_allowlists(
    tmp_path: Path,
    legacy_config: str,
) -> None:
    marker = "        locale: en"
    content = _valid_manifest().replace(
        marker,
        marker + "\n" + dedent(legacy_config).rstrip().replace("\n", "\n        "),
        1,
    )

    with pytest.raises(KnowledgeManifestError) as error:
        load_manifest(_write_manifest(tmp_path, content))

    assert "extra" in str(error.value).lower()


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


def test_repository_manifest_declares_only_complete_official_catalogs() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest = load_manifest(repository_root / "knowledge" / "databricks" / "sources.yml")

    assert manifest.version == 2
    assert tuple((catalog.id, catalog.index_url) for catalog in manifest.catalogs) == (
        ("databricks-docs", "https://docs.databricks.com/llms.txt"),
        ("databricks-api", "https://docs.databricks.com/api/llms.txt"),
    )
