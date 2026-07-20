import hashlib
import re
from pathlib import Path

import sqlparse

from databricks_zh_expert.workspace.registry import WorkspaceRegistry
from databricks_zh_expert.workspace.types import WorkspaceSourceKind

WORKSPACE_ROOT = Path("examples/workspaces")
NORTHWIND_ROOT = WORKSPACE_ROOT / "northwind_psql"
PACKAGE_ROOT = NORTHWIND_ROOT / ".databricks-expert"
UPSTREAM_SQL = NORTHWIND_ROOT / "upstream" / "northwind.sql"
SCHEMA_SQL = PACKAGE_ROOT / "source-schema" / "northwind-schema.sql"
UPSTREAM_SHA256 = "0ee30c01ba282f7194f38bf7f99cd6be0470b7ee5f67d0f7ca41fb058d735e0c"
EXPECTED_FILES = {
    ".databricks-expert/project.yml",
    ".databricks-expert/requirements.md",
    ".databricks-expert/business-rules.md",
    ".databricks-expert/source-schema/northwind-schema.sql",
    "upstream/northwind.sql",
    "UPSTREAM.md",
    "LICENSE.northwind",
}
EXPECTED_TABLES = {
    "categories",
    "customer_customer_demo",
    "customer_demographics",
    "customers",
    "employees",
    "employee_territories",
    "order_details",
    "orders",
    "products",
    "region",
    "shippers",
    "suppliers",
    "territories",
    "us_states",
}
CREATE_TABLE_PATTERN = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)",
    re.IGNORECASE,
)


def test_northwind_is_the_only_builtin_workspace() -> None:
    registry = WorkspaceRegistry.create_default()

    assert [workspace.workspace_id for workspace in registry.workspaces] == ["northwind_psql"]
    assert not (WORKSPACE_ROOT / "retail_sales_demo" / ".databricks-expert").exists()


def test_northwind_contains_only_fixed_workspace_inputs_and_upstream_audit_files() -> None:
    actual_files = {
        path.relative_to(NORTHWIND_ROOT).as_posix()
        for path in NORTHWIND_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert actual_files == EXPECTED_FILES


def test_upstream_sql_is_preserved_with_the_pinned_hash() -> None:
    assert hashlib.sha256(UPSTREAM_SQL.read_bytes()).hexdigest() == UPSTREAM_SHA256


def test_registry_loads_only_project_fact_sources() -> None:
    workspace = WorkspaceRegistry.create_default().get("northwind_psql")

    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert [source.source_id for source in workspace.sources] == [
        "requirements",
        "rules",
        "source_ddl.northwind.northwind-schema",
    ]
    assert {source.kind for source in workspace.sources} == {
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.RULE,
        WorkspaceSourceKind.SOURCE_DDL,
    }
    assert all("upstream/northwind.sql" not in source.source_path for source in workspace.sources)


def test_schema_only_file_contains_all_tables_primary_keys_and_foreign_keys() -> None:
    content = SCHEMA_SQL.read_text(encoding="utf-8")
    statements = tuple(sqlparse.split(content))

    assert set(CREATE_TABLE_PATTERN.findall(content)) == EXPECTED_TABLES
    assert len(CREATE_TABLE_PATTERN.findall(content)) == 14
    assert len(re.findall(r"\bPRIMARY\s+KEY\b", content, re.IGNORECASE)) == 14
    assert len(re.findall(r"\bFOREIGN\s+KEY\b", content, re.IGNORECASE)) == 13
    assert len(statements) == 41
    assert "PRIMARY KEY (order_id, product_id)" in content
    assert "FOREIGN KEY (reports_to) REFERENCES employees" in content


def test_schema_only_file_excludes_upstream_data_and_session_statements() -> None:
    content = SCHEMA_SQL.read_text(encoding="utf-8")

    assert not re.search(r"\bINSERT\s+INTO\b", content, re.IGNORECASE)
    assert not re.search(r"\bDROP\s+TABLE\b", content, re.IGNORECASE)
    assert not re.search(r"^\s*SET\s+", content, re.IGNORECASE | re.MULTILINE)
    assert "Alfreds Futterkiste" not in content
    assert all(
        marker not in content.casefold()
        for marker in ("password", "api_key", "secret_key", "access_key")
    )


def test_requirements_fix_architecture_and_five_data_products() -> None:
    content = (PACKAGE_ROOT / "requirements.md").read_text(encoding="utf-8")

    assert "RDS PostgreSQL → AWS DMS → S3 Parquet → Auto Loader" in content
    assert all(
        product in content
        for product in (
            "每日销售",
            "客户价值",
            "商品与品类表现",
            "员工销售表现",
            "配送表现",
        )
    )
    assert all(term not in content for term in ("门店", "退货事实", "币种字段"))


def test_business_rules_fix_sales_and_shipping_definitions() -> None:
    content = (PACKAGE_ROOT / "business-rules.md").read_text(encoding="utf-8")

    assert "unit_price * quantity" in content
    assert "unit_price * quantity * discount" in content
    assert "unit_price * quantity * (1 - discount)" in content
    assert "orders.order_date" in content
    assert "freight" in content
    assert "shipped_date > required_date" in content
    assert "默认统计全部订单" in content
    assert "只统计已发货订单" in content
