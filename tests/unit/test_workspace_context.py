import hashlib

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
    assert len(first) == 56
    assert [unit.title for unit in first if unit.source_id == "requirements"] == [
        "业务目标",
        "源系统",
        "期望数据产品",
        "摄取需求",
        "数据量与 SLA 假设",
        "治理与安全",
        "技术约束",
        "待确认事项",
    ]
    assert [
        unit.unit_id for unit in first if unit.source_id == "source_ddl.northwind.northwind-schema"
    ] == [f"source_ddl.northwind.northwind-schema:{index}" for index in range(1, 42)]
    assert all(len(unit.content_hash) == 64 for unit in first)
    assert all(unit.content.endswith("\n") for unit in first)


def test_order_cdc_query_selects_orders_ddl_and_cdc_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 orders 的 order_id、customer_id 和 order_date 设计 AWS DMS CDC 去重 DDL",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.DDL,
    )
    selected_ids = [item.unit_id for item in bundle.selected_units]

    assert "source_ddl.northwind.northwind-schema:8" in selected_ids[:3]
    assert "rules:2" in selected_ids
    assert bundle.selected_units[0].reason == "lexical"
    assert "CREATE TABLE orders" in bundle.context
    assert "## CDC 与去重" in bundle.context


def test_sales_mapping_query_selects_order_schemas_product_requirement_and_amount_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 orders、order_details 和 products 的 order_id、product_id、quantity、"
        "unit_price、discount 生成每日销售 Mapping，并确认净销售额口径",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.MAPPING,
    )
    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "source_ddl.northwind.northwind-schema:7" in selected_ids
    assert "source_ddl.northwind.northwind-schema:8" in selected_ids
    assert "source_ddl.northwind.northwind-schema:9" in selected_ids
    assert "rules:4" in selected_ids


def test_dms_notebook_query_selects_orders_ingestion_and_late_data_units() -> None:
    bundle = WorkspaceContextBuilder().build(
        "为 orders 使用 AWS DMS、S3 Parquet 和 Auto Loader 生成 CDC 摄取 Notebook，"
        "并使用 order_date、required_date、shipped_date 说明事件时间与迟到数据处理",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.NOTEBOOK,
    )
    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "source_ddl.northwind.northwind-schema:8" in selected_ids
    assert "requirements:4" in selected_ids
    assert "rules:3" in selected_ids


@pytest.mark.parametrize(
    ("purpose", "expected_first_units"),
    [
        (
            WorkspaceContextPurpose.DDL,
            (
                "requirements:3",
                "source_ddl.northwind.northwind-schema:1",
                "rules:1",
            ),
        ),
        (
            WorkspaceContextPurpose.MAPPING,
            (
                "source_ddl.northwind.northwind-schema:1",
                "rules:1",
                "requirements:3",
            ),
        ),
        (
            WorkspaceContextPurpose.SQL,
            (
                "requirements:3",
                "source_ddl.northwind.northwind-schema:1",
                "rules:4",
            ),
        ),
        (
            WorkspaceContextPurpose.PYSPARK,
            (
                "requirements:4",
                "source_ddl.northwind.northwind-schema:1",
                "rules:2",
            ),
        ),
        (
            WorkspaceContextPurpose.NOTEBOOK,
            (
                "requirements:4",
                "source_ddl.northwind.northwind-schema:1",
                "rules:3",
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

    assert "以下内容仅来自用户提供的全新项目事实" in bundle.context
    assert "Agent 历史提案不会进入此上下文" in bundle.context
    assert "输入包相对路径：.databricks-expert/" in bundle.context
    assert "project_fact_status=proposal" not in bundle.context
    assert str(__file__) not in bundle.context


def test_builder_rejects_limits_above_fixed_stage_boundaries() -> None:
    with pytest.raises(ValueError, match="不能超过 8"):
        WorkspaceContextBuilder(top_k=WORKSPACE_CONTEXT_TOP_K + 1)
    with pytest.raises(ValueError, match="不能超过 8000"):
        WorkspaceContextBuilder(max_context_tokens=WORKSPACE_CONTEXT_MAX_TOKENS + 1)
