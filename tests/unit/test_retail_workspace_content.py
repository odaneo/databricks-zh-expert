import re
from pathlib import Path

import sqlparse

from databricks_zh_expert.workspace.registry import WorkspaceRegistry
from databricks_zh_expert.workspace.types import WorkspaceSourceKind

WORKSPACE_ROOT = Path("examples/workspaces")
DEMO_ROOT = WORKSPACE_ROOT / "retail_sales_demo"
PACKAGE_ROOT = DEMO_ROOT / ".databricks-expert"
EXPECTED_FILES = {
    ".databricks-expert/project.yml",
    ".databricks-expert/requirements.md",
    ".databricks-expert/business-rules.md",
    ".databricks-expert/source-schema/rds-postgresql.sql",
    ".databricks-expert/source-schema/pos-parquet.sql",
    ".databricks-expert/source-schema/kinesis-events.sql",
}
LEGACY_PATHS = ("docs", "contracts", "sql", "databricks.yml", "resources", "src")
CREATE_TABLE_PATTERN = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)",
    re.IGNORECASE,
)
FORBIDDEN_DML_PATTERN = re.compile(
    r"\b(insert|update|delete|merge)\b|\bcopy\b[\s\S]*\bfrom\s+stdin\b",
    re.IGNORECASE,
)


def _source_content(source_id: str) -> str:
    workspace = WorkspaceRegistry.create_default().get("retail_sales_demo")
    return next(source.content for source in workspace.sources if source.source_id == source_id)


def test_demo_contains_only_six_greenfield_input_files() -> None:
    actual_files = {
        path.relative_to(DEMO_ROOT).as_posix()
        for path in DEMO_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert actual_files == EXPECTED_FILES
    assert all(not (DEMO_ROOT / legacy_path).exists() for legacy_path in LEGACY_PATHS)


def test_demo_registry_contains_only_user_fact_sources() -> None:
    workspace = WorkspaceRegistry.create_default().get("retail_sales_demo")

    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert not hasattr(workspace, "workspace_mode")
    assert not hasattr(workspace, "is_mock")
    assert [source.source_id for source in workspace.sources] == [
        "requirements",
        "rules",
        "source_ddl.kinesis_events.kinesis-events",
        "source_ddl.pos_parquet.pos-parquet",
        "source_ddl.rds_postgresql.rds-postgresql",
    ]
    assert {source.kind for source in workspace.sources} == {
        WorkspaceSourceKind.REQUIREMENT,
        WorkspaceSourceKind.RULE,
        WorkspaceSourceKind.SOURCE_DDL,
    }


def test_rds_schema_contains_four_source_tables() -> None:
    source = _source_content("source_ddl.rds_postgresql.rds-postgresql")

    assert set(CREATE_TABLE_PATTERN.findall(source)) == {
        "public.customer",
        "public.product",
        "public.store",
        "public.inventory",
    }
    assert {
        "customer_id",
        "product_id",
        "store_id",
        "on_hand_quantity",
        "updated_at",
    } <= set(re.findall(r"\b[a-z_][a-z0-9_]*\b", source.casefold()))


def test_pos_schema_describes_sales_line_source_fields() -> None:
    source = _source_content("source_ddl.pos_parquet.pos-parquet")

    assert set(CREATE_TABLE_PATTERN.findall(source)) == {"source.pos_sales_line"}
    assert {
        "order_id",
        "order_line_id",
        "business_date",
        "store_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount_amount",
        "tax_amount",
        "event_ts",
    } <= set(re.findall(r"\b[a-z_][a-z0-9_]*\b", source.casefold()))


def test_kinesis_schema_describes_order_payment_and_behavior_events() -> None:
    source = _source_content("source_ddl.kinesis_events.kinesis-events")

    assert set(CREATE_TABLE_PATTERN.findall(source)) == {
        "source.order_event",
        "source.payment_event",
        "source.behavior_event",
    }
    assert {
        "event_id",
        "event_type",
        "event_ts",
        "order_id",
        "payment_id",
        "customer_id",
        "session_id",
    } <= set(re.findall(r"\b[a-z_][a-z0-9_]*\b", source.casefold()))


def test_requirements_define_sections_and_four_expected_products() -> None:
    content = (PACKAGE_ROOT / "requirements.md").read_text(encoding="utf-8")

    assert [
        "## 业务目标",
        "## 源系统",
        "## 期望数据产品",
        "## 摄取需求",
        "## 数据量与 SLA 假设",
        "## 治理与安全",
        "## 技术约束",
        "## 待确认事项",
    ] == [line for line in content.splitlines() if line.startswith("## ")]
    assert all(product in content for product in ("每日销售", "商品表现", "库存健康", "客户与渠道"))
    assert "RDS PostgreSQL → AWS DMS → S3 Parquet → Auto Loader" in content
    assert "Kinesis" in content


def test_business_rules_define_all_required_sections() -> None:
    content = (PACKAGE_ROOT / "business-rules.md").read_text(encoding="utf-8")

    assert [
        "## 源数据粒度与业务键",
        "## CDC 与去重",
        "## 事件时间与迟到数据",
        "## 指标口径",
        "## 空值与数据质量",
        "## PII 与权限",
        "## 待确认规则",
    ] == [line for line in content.splitlines() if line.startswith("## ")]


def test_demo_has_no_target_schema_mapping_data_or_credentials() -> None:
    sql_sources = tuple((PACKAGE_ROOT / "source-schema").glob("*.sql"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sql_sources)
    statements = [
        statement
        for source in sql_sources
        for statement in sqlparse.split(source.read_text(encoding="utf-8"))
    ]

    assert statements
    assert not re.search(r"\b(bronze|silver|gold)\s*\.", combined, re.IGNORECASE)
    assert not FORBIDDEN_DML_PATTERN.search(combined)
    assert "mapping" not in combined.casefold()
    assert not re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", combined, re.IGNORECASE)
    assert all(
        marker not in combined.casefold()
        for marker in ("password", "api_key", "secret_key", "access_key")
    )
