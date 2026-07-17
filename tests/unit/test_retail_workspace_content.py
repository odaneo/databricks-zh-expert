import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml

from databricks_zh_expert.workspace.registry import WorkspaceRegistry

WORKSPACE_ROOT = Path("examples/workspaces")
EXPECTED_SOURCE_IDS = {
    "project.overview",
    "bundle.root",
    "bundle.job",
    "contract.tables",
    "contract.mappings",
    "contract.business_rules",
    "ddl.bronze",
    "ddl.silver",
    "ddl.gold",
    "code.parameters",
    "code.pos_auto_loader",
}
EXPECTED_TABLES = {
    "bronze.pos_sales_raw",
    "bronze.customer_cdc_raw",
    "bronze.product_cdc_raw",
    "bronze.store_cdc_raw",
    "bronze.inventory_cdc_raw",
    "bronze.ecommerce_events_raw",
    "silver.dim_customer",
    "silver.dim_product",
    "silver.dim_store",
    "silver.fact_sales",
    "silver.fact_inventory",
    "silver.fact_customer_behavior",
    "gold.daily_sales",
    "gold.product_performance",
    "gold.inventory_health",
    "gold.customer_channel",
}
EXPECTED_GOLD_TABLES = {
    "gold.daily_sales",
    "gold.product_performance",
    "gold.inventory_health",
    "gold.customer_channel",
}
CREATE_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+\.[a-z_]+)",
    re.IGNORECASE,
)
CREATE_TABLE_BLOCK_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+\.[a-z_]+)\s*\(\n"
    r"(?P<columns>.*?)\n\)\nUSING\s+DELTA",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_PATTERN = re.compile(r"^\s{2}([a-z_][a-z0-9_]*)\s+", re.IGNORECASE | re.MULTILINE)
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _workspace_sources() -> dict[str, str]:
    workspace = WorkspaceRegistry.create_default().get("retail_sales_demo")
    return {source.source_id: source.content for source in workspace.sources}


def _yaml_source(sources: Mapping[str, str], source_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(sources[source_id]))


def _table_contract(sources: Mapping[str, str]) -> list[dict[str, Any]]:
    payload = _yaml_source(sources, "contract.tables")
    return cast(list[dict[str, Any]], payload["tables"])


def _column_names(table: Mapping[str, Any]) -> set[str]:
    columns = cast(list[dict[str, Any]], table["columns"])
    return {cast(str, column["name"]) for column in columns}


def _table_by_name(tables: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(table for table in tables if table["name"] == name)


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        payload = cast(dict[object, object], value)
        keys = {str(key).casefold() for key in payload}
        for child in payload.values():
            keys.update(_nested_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in cast(list[object], value):
            keys.update(_nested_keys(child))
        return keys
    return set()


def test_retail_workspace_contains_complete_table_contract() -> None:
    workspace = WorkspaceRegistry.create_default().get("retail_sales_demo")
    sources = {source.source_id: source.content for source in workspace.sources}
    tables = _table_contract(sources)

    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert workspace.is_mock is True
    assert set(sources) == EXPECTED_SOURCE_IDS
    assert {cast(str, table["name"]) for table in tables} == EXPECTED_TABLES
    assert all(table["columns"] for table in tables)
    assert all(table["keys"] for table in tables)
    assert all(set(cast(list[str], table["keys"])) <= _column_names(table) for table in tables)
    assert all("id" not in cast(list[str], table["keys"]) for table in tables)
    assert all(
        {"name", "type", "nullable", "pii"} <= set(cast(dict[str, Any], column))
        for table in tables
        for column in cast(list[dict[str, Any]], table["columns"])
    )


def test_ddl_table_names_match_yaml_contract() -> None:
    sources = _workspace_sources()
    ddl = "\n".join(sources[source_id] for source_id in ("ddl.bronze", "ddl.silver", "ddl.gold"))

    assert set(CREATE_TABLE_PATTERN.findall(ddl)) == EXPECTED_TABLES
    assert "select *" not in ddl.casefold()


def test_ddl_columns_match_yaml_contract() -> None:
    sources = _workspace_sources()
    tables = _table_contract(sources)
    ddl = "\n".join(sources[source_id] for source_id in ("ddl.bronze", "ddl.silver", "ddl.gold"))
    ddl_columns = {
        table_name: set(COLUMN_PATTERN.findall(columns))
        for table_name, columns in CREATE_TABLE_BLOCK_PATTERN.findall(ddl)
    }

    assert set(ddl_columns) == EXPECTED_TABLES
    for table in tables:
        assert ddl_columns[cast(str, table["name"])] == _column_names(table)


def test_contract_contains_required_ingestion_and_sales_fields() -> None:
    tables = _table_contract(_workspace_sources())

    pos_columns = _column_names(_table_by_name(tables, "bronze.pos_sales_raw"))
    assert {"_ingest_ts", "_source_file", "_rescued_data"} <= pos_columns

    for table_name in (
        "bronze.customer_cdc_raw",
        "bronze.product_cdc_raw",
        "bronze.store_cdc_raw",
        "bronze.inventory_cdc_raw",
    ):
        assert {"_dms_op", "_dms_commit_ts", "_ingest_ts", "_source_file"} <= _column_names(
            _table_by_name(tables, table_name)
        )

    event_columns = _column_names(_table_by_name(tables, "bronze.ecommerce_events_raw"))
    assert {"event_id", "event_ts", "_ingest_ts", "_rescued_data"} <= event_columns

    sales = _table_by_name(tables, "silver.fact_sales")
    assert sales["grain"] == "每个 order_id 与 order_line_id 一行"
    assert {
        "order_id",
        "order_line_id",
        "gross_amount",
        "discount_amount",
        "net_amount",
    } <= _column_names(sales)


def test_mappings_cover_all_sources_and_gold_products() -> None:
    sources = _workspace_sources()
    mappings = cast(
        list[dict[str, Any]],
        _yaml_source(sources, "contract.mappings")["mappings"],
    )
    source_kinds = {cast(str, mapping["source_kind"]) for mapping in mappings}
    targets = {
        target for mapping in mappings for target in cast(list[str], mapping["target_tables"])
    }

    assert {"s3_pos", "rds_dms", "kinesis", "silver"} <= source_kinds
    assert EXPECTED_GOLD_TABLES <= targets
    assert all(mapping["field_mappings"] for mapping in mappings)


def test_mapping_tables_and_target_columns_exist_in_contract() -> None:
    sources = _workspace_sources()
    tables = _table_contract(sources)
    columns_by_table = {cast(str, table["name"]): _column_names(table) for table in tables}
    mappings = cast(
        list[dict[str, Any]],
        _yaml_source(sources, "contract.mappings")["mappings"],
    )

    for mapping in mappings:
        source_tables = cast(list[str], mapping["source_tables"])
        target_tables = cast(list[str], mapping["target_tables"])
        assert set(source_tables) <= EXPECTED_TABLES
        assert set(target_tables) <= EXPECTED_TABLES
        target_columns = set().union(*(columns_by_table[name] for name in target_tables))
        for field_mapping in cast(list[dict[str, str]], mapping["field_mappings"]):
            assert field_mapping["target"] in target_columns


def test_all_registered_yaml_sources_are_valid_mappings() -> None:
    sources = _workspace_sources()
    yaml_source_ids = {
        "bundle.root",
        "bundle.job",
        "contract.tables",
        "contract.mappings",
        "contract.business_rules",
    }

    for source_id in yaml_source_ids:
        assert isinstance(yaml.safe_load(sources[source_id]), dict)


def test_gold_contract_does_not_expose_direct_pii() -> None:
    tables = _table_contract(_workspace_sources())
    forbidden = {"full_name", "email", "phone", "address", "customer_name"}

    for table in tables:
        if cast(str, table["name"]).startswith("gold."):
            columns = cast(list[dict[str, Any]], table["columns"])
            assert forbidden.isdisjoint(_column_names(table))
            assert all(column["pii"] != "direct" for column in columns)


def test_bundle_is_a_secret_free_mock_skeleton() -> None:
    sources = _workspace_sources()
    bundle = yaml.safe_load(sources["bundle.root"])
    resource = yaml.safe_load(sources["bundle.job"])
    keys = _nested_keys(bundle) | _nested_keys(resource)

    assert {"dev", "test", "prod"} == set(cast(dict[str, Any], bundle)["targets"])
    assert {"host", "token", "warehouse_id", "existing_cluster_id", "new_cluster"}.isdisjoint(keys)


def test_all_workspace_sources_are_explicitly_mock_and_safe() -> None:
    sources = _workspace_sources()
    forbidden_claims = ("部署成功", "执行成功", "生产可用", "已验证通过")
    forbidden_secret_markers = ("api_key", "password", "secret_key", "access_key")

    for content in sources.values():
        lowered = content.casefold()
        assert "mock" in lowered
        assert not EMAIL_PATTERN.search(content)
        assert all(marker not in lowered for marker in forbidden_secret_markers)
        assert all(claim not in content for claim in forbidden_claims)
