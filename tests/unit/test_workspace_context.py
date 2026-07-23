import hashlib
from collections import Counter

import pytest

from databricks_zh_expert.workspace.constants import (
    WORKSPACE_CONTEXT_MAX_TOKENS,
    WORKSPACE_CONTEXT_TOP_K,
)
from databricks_zh_expert.workspace.context import (
    WorkspaceContextBuilder,
    WorkspaceContextNotFoundError,
)
from databricks_zh_expert.workspace.registry import WorkspaceRegistry
from databricks_zh_expert.workspace.types import (
    WorkspaceContextPurpose,
    WorkspaceDefinition,
    WorkspaceSource,
    WorkspaceSourceKind,
)


def _workspace() -> WorkspaceDefinition:
    return WorkspaceRegistry.create_default().get("northwind_psql")


def _source(
    source_id: str,
    *,
    content: str,
    kind: WorkspaceSourceKind = WorkspaceSourceKind.SOURCE_DDL,
    dialect: str | None = "spark_sql",
) -> WorkspaceSource:
    normalized = content.rstrip("\n") + "\n"
    return WorkspaceSource(
        source_id=source_id,
        kind=kind,
        dialect=dialect,
        source_path=f".databricks-expert/source-schema/{source_id}.sql",
        content=normalized,
        content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _custom_workspace(sources: tuple[WorkspaceSource, ...]) -> WorkspaceDefinition:
    return WorkspaceDefinition(
        workspace_id="test_workspace",
        display_name="测试工作区",
        description="Workspace Context 单元测试工作区。",
        version="1.0.0",
        cloud="aws",
        source_hash="a" * 64,
        sources=sources,
    )


def test_builder_splits_markdown_sections_and_sql_statements_into_stable_units() -> None:
    builder = WorkspaceContextBuilder()

    first = builder.build_units(_workspace())
    second = builder.build_units(_workspace())

    assert first == second
    assert len(first) == 519
    assert Counter(unit.source_id for unit in first) == {
        "architecture": 50,
        "business_glossary": 83,
        "data_products": 52,
        "data_quality": 67,
        "governance_and_operations": 65,
        "requirements": 74,
        "rules": 39,
        "source_ddl.northwind.northwind-schema": 41,
        "source_system": 48,
    }
    requirement_titles = [unit.title for unit in first if unit.source_id == "requirements"]
    assert requirement_titles[:3] == [
        "文档定位",
        "业务目标",
        "源系统与事实边界",
    ]
    assert "AWS DMS 设计决策 / PostgreSQL CDC 前置条件" in requirement_titles
    assert "调度与运行 / 每日认证" in requirement_titles
    assert requirement_titles[-1] == "设计依据"
    assert [
        unit.unit_id for unit in first if unit.source_id == "source_ddl.northwind.northwind-schema"
    ] == [f"source_ddl.northwind.northwind-schema:{index}" for index in range(1, 42)]
    assert all(len(unit.content_hash) == 64 for unit in first)
    assert all(unit.content.endswith("\n") for unit in first)


def test_builder_splits_h3_sections_with_parent_heading_context() -> None:
    source = _source(
        "requirements",
        kind=WorkspaceSourceKind.REQUIREMENT,
        dialect=None,
        content=(
            "# 项目需求\n\n"
            "## 摄取设计\n\n总体说明。\n\n"
            "### CDC\n\nCDC 规则。\n\n"
            "### 重跑\n\n重跑规则。"
        ),
    )

    units = WorkspaceContextBuilder().build_units(_custom_workspace((source,)))

    assert [unit.title for unit in units] == [
        "摄取设计",
        "摄取设计 / CDC",
        "摄取设计 / 重跑",
    ]
    assert "总体说明" in units[0].content
    assert "CDC 规则" in units[1].content
    assert "重跑规则" in units[2].content
    assert "CDC 规则" not in units[0].content


def test_builder_skips_heading_only_parent_without_renumbering_child() -> None:
    source = _source(
        "requirements",
        kind=WorkspaceSourceKind.REQUIREMENT,
        dialect=None,
        content="# 项目需求\n\n## 摄取设计\n\n### CDC\n\nCDC 规则。",
    )

    units = WorkspaceContextBuilder().build_units(_custom_workspace((source,)))

    assert [unit.unit_id for unit in units] == ["requirements:2"]
    assert [unit.title for unit in units] == ["摄取设计 / CDC"]


def test_order_cdc_query_selects_orders_ddl_and_cdc_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 orders 的 order_id、customer_id 和 order_date 设计 AWS DMS CDC 去重 DDL",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.DDL,
    )
    selected_ids = [item.unit_id for item in bundle.selected_units]

    assert "source_ddl.northwind.northwind-schema:8" in selected_ids[:3]
    assert "rules:8" in selected_ids
    assert bundle.selected_units[0].reason == "lexical"
    assert "CREATE TABLE orders" in bundle.context
    assert "### 元数据地位" in bundle.context


def test_sales_mapping_query_selects_order_schemas_product_requirement_and_amount_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 orders、order_details 和 products 的 order_id、product_id、quantity、"
        "unit_price、discount 生成每日销售 Mapping，并确认净销售额口径",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.MAPPING,
    )
    selected_ids = [item.unit_id for item in bundle.selected_units]

    assert {
        "source_ddl.northwind.northwind-schema:7",
        "source_ddl.northwind.northwind-schema:8",
        "source_ddl.northwind.northwind-schema:9",
    }.issubset(set(selected_ids[:5]))
    assert "rules:22" in selected_ids


def test_dms_notebook_query_selects_orders_ingestion_and_late_data_units() -> None:
    bundle = WorkspaceContextBuilder().build(
        "为 orders 使用 AWS DMS、S3 Parquet 和 Auto Loader 生成 CDC 摄取 Notebook，"
        "并使用 order_date、required_date、shipped_date 说明事件时间与迟到数据处理",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.NOTEBOOK,
    )
    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "source_ddl.northwind.northwind-schema:8" in selected_ids
    assert "architecture:32" in selected_ids
    assert "rules:18" in selected_ids


@pytest.mark.parametrize(
    ("purpose", "expected_first_units"),
    [
        (
            WorkspaceContextPurpose.DDL,
            (
                "data_products:3",
                "source_ddl.northwind.northwind-schema:1",
                "rules:8",
            ),
        ),
        (
            WorkspaceContextPurpose.MAPPING,
            (
                "source_ddl.northwind.northwind-schema:1",
                "source_system:9",
                "rules:3",
            ),
        ),
        (
            WorkspaceContextPurpose.SQL,
            (
                "data_products:42",
                "rules:21",
                "source_ddl.northwind.northwind-schema:1",
            ),
        ),
        (
            WorkspaceContextPurpose.PYSPARK,
            (
                "architecture:28",
                "source_ddl.northwind.northwind-schema:1",
                "rules:8",
            ),
        ),
        (
            WorkspaceContextPurpose.NOTEBOOK,
            (
                "architecture:28",
                "source_ddl.northwind.northwind-schema:1",
                "rules:13",
            ),
        ),
    ],
)
def test_all_five_code_purposes_have_stable_fact_balanced_fallbacks(
    purpose: WorkspaceContextPurpose,
    expected_first_units: tuple[str, str, str],
) -> None:
    builder = WorkspaceContextBuilder()

    first = builder.build("火星火山地质勘探", workspace=_workspace(), purpose=purpose)
    second = builder.build("火星火山地质勘探", workspace=_workspace(), purpose=purpose)

    assert first == second
    assert tuple(item.unit_id for item in first.selected_units[:3]) == expected_first_units
    assert all(item.reason == "fallback" for item in first.selected_units)


def test_workflow_context_adds_fallback_fact_coverage_after_lexical_match() -> None:
    workspace = _custom_workspace(
        (
            _source(
                "requirements",
                kind=WorkspaceSourceKind.REQUIREMENT,
                dialect=None,
                content="# 项目需求\n\n## 业务目标\n每日销售分析。",
            ),
            _source(
                "rules",
                kind=WorkspaceSourceKind.RULE,
                dialect=None,
                content="# 已确认规则\n\n## 源数据粒度与业务键\n每行是一笔订单。",
            ),
            _source(
                "source_ddl.sales",
                content="CREATE TABLE source.sales (order_id STRING);",
            ),
        )
    )

    bundle = WorkspaceContextBuilder().build_for_prompt(
        "根据 source.sales 设计工作流",
        workspace=workspace,
        prompt_name="workflow_design",
    )

    assert bundle is not None
    assert bundle.purpose.value == "workflow_design"
    assert [item.unit_id for item in bundle.selected_units[:3]] == [
        "source_ddl.sales:1",
        "requirements:1",
        "rules:1",
    ]
    assert [item.reason for item in bundle.selected_units[:3]] == [
        "lexical",
        "fallback",
        "fallback",
    ]


def test_customer_value_query_selects_cross_file_project_evidence() -> None:
    bundle = WorkspaceContextBuilder().build(
        "生成客户价值 SQL，必须保留没有已发货订单的当前客户，平均商品净订单金额分母为零时为 null，"
        "并统计 freight 为空的运费缺失订单数",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.SQL,
    )

    selected_source_ids = {item.source_id for item in bundle.selected_units}

    assert {"data_products", "data_quality", "rules", "business_glossary"}.issubset(
        selected_source_ids
    )
    assert all(item.source_path.startswith(".databricks-expert/") for item in bundle.selected_units)
    assert all(len(item.content_hash) == 64 for item in bundle.selected_units)


def test_qualified_foreign_key_query_keeps_child_parents_and_quality_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据外键引用完整性，使用 order_details.order_id、order_details.product_id 检查 "
        "orders 和 products 孤儿记录",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.PYSPARK,
    )

    assert {
        "source_ddl.northwind.northwind-schema:7",
        "source_ddl.northwind.northwind-schema:8",
        "source_ddl.northwind.northwind-schema:9",
        "data_quality:23",
    }.issubset({item.unit_id for item in bundle.selected_units[:4]})


def test_qualified_target_table_name_maps_back_to_registered_source_table() -> None:
    bundle = WorkspaceContextBuilder().build(
        "以 silver.customers 当前客户全集为基础生成客户价值 SQL",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.SQL,
    )

    assert "source_ddl.northwind.northwind-schema:4" in {
        item.unit_id for item in bundle.selected_units
    }


def test_amount_cleaning_query_keeps_specific_formula_and_quality_evidence() -> None:
    bundle = WorkspaceContextBuilder().build(
        "生成 PySpark 草稿清洗 order_details。显式选择 order_id、product_id、unit_price、"
        "quantity、discount；将金额和折扣转换为定点小数，按 HALF_UP 四位小数计算行毛额、"
        "折扣额和行净销售额。quantity 或 unit_price 非正、discount 不在 0 到 1 时标记为"
        "关键异常。",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.PYSPARK,
    )

    selected_ids = {item.unit_id for item in bundle.selected_units}
    selected_kinds = {item.kind for item in bundle.selected_units}

    assert "source_ddl.northwind.northwind-schema:7" in selected_ids
    assert "rules:22" in selected_ids
    assert WorkspaceSourceKind.DATA_QUALITY in selected_kinds


def test_autoloader_notebook_query_keeps_managed_state_constraints() -> None:
    bundle = WorkspaceContextBuilder().build(
        "生成 Lakeflow Declarative Pipeline Notebook，使用 Auto Loader 从 External Volume "
        "读取 AWS DMS orders Parquet，启用 cloudFiles.useManagedFileEvents，并由 Lakeflow "
        "托管 Checkpoint 与 Schema State，不得手写 checkpointLocation 或 schemaLocation。",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.NOTEBOOK,
    )

    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "architecture:29" in selected_ids
    assert "architecture:31" in selected_ids


def test_tied_scores_sort_by_source_id_and_unit_order() -> None:
    sources = (
        _source("source_ddl.b", content="CREATE TABLE source.sales_b (sales_id string);"),
        _source("source_ddl.a", content="CREATE TABLE source.sales_a (sales_id string);"),
    )
    workspace = _custom_workspace(sources)
    builder = WorkspaceContextBuilder()

    bundle = builder.build(
        "sales_id",
        workspace=workspace,
        purpose=WorkspaceContextPurpose.SQL,
    )

    assert [item.unit_id for item in bundle.selected_units] == [
        "source_ddl.a:1",
        "source_ddl.b:1",
    ]


def test_builder_selects_at_most_eight_complete_units() -> None:
    bundle = WorkspaceContextBuilder().build(
        "火星火山地质勘探",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.DDL,
    )
    units = {unit.unit_id: unit for unit in WorkspaceContextBuilder().build_units(_workspace())}

    assert len(bundle.selected_units) == WORKSPACE_CONTEXT_TOP_K
    assert bundle.context_token_count <= WORKSPACE_CONTEXT_MAX_TOKENS
    for selection in bundle.selected_units:
        assert units[selection.unit_id].content in bundle.context


def test_builder_skips_oversized_unit_without_truncating_it() -> None:
    source = _source(
        "source_ddl.size",
        content=(
            "CREATE TABLE source.large (large_marker string COMMENT '"
            + "large content " * 2_000
            + "');\nCREATE TABLE source.compact (compact_marker string);"
        ),
    )
    workspace = _custom_workspace((source,))

    bundle = WorkspaceContextBuilder(max_context_tokens=300).build(
        "source.large source.compact large_marker compact_marker",
        workspace=workspace,
        purpose=WorkspaceContextPurpose.SQL,
    )

    assert [item.unit_id for item in bundle.selected_units] == ["source_ddl.size:2"]
    assert "CREATE TABLE source.compact" in bundle.context
    assert "CREATE TABLE source.large" not in bundle.context


def test_builder_raises_when_no_complete_unit_fits_budget() -> None:
    source = _source(
        "source_ddl.large",
        content="CREATE TABLE source.large (payload string COMMENT '"
        + "large content " * 2_000
        + "');",
    )

    with pytest.raises(WorkspaceContextNotFoundError, match="token 预算"):
        WorkspaceContextBuilder(max_context_tokens=150).build(
            "source.large payload",
            workspace=_custom_workspace((source,)),
            purpose=WorkspaceContextPurpose.SQL,
        )


def test_non_proposal_prompt_does_not_build_workspace_context() -> None:
    builder = WorkspaceContextBuilder()

    assert (
        builder.build_for_prompt(
            "解释 Unity Catalog",
            workspace=_workspace(),
            prompt_name="knowledge_qa",
        )
        is None
    )


def test_context_contains_only_relative_user_fact_metadata() -> None:
    bundle = WorkspaceContextBuilder().build(
        "customers customer_id",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.DDL,
    )

    assert "以下内容仅来自用户提供的项目事实" in bundle.context
    assert "Agent 历史提案不会进入此上下文" in bundle.context
    assert "输入包相对路径：.databricks-expert/" in bundle.context
    assert "project_fact_status=proposal" not in bundle.context
    assert str(__file__) not in bundle.context


def test_builder_rejects_limits_above_fixed_stage_boundaries() -> None:
    with pytest.raises(ValueError, match="不能超过 8"):
        WorkspaceContextBuilder(top_k=WORKSPACE_CONTEXT_TOP_K + 1)
    with pytest.raises(ValueError, match="不能超过 8000"):
        WorkspaceContextBuilder(max_context_tokens=WORKSPACE_CONTEXT_MAX_TOKENS + 1)
