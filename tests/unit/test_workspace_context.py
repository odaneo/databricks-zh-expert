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
    WorkspaceMode,
    WorkspaceSource,
    WorkspaceSourceKind,
)


def _workspace() -> WorkspaceDefinition:
    return WorkspaceRegistry.create_default().get("retail_sales_demo")


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
        workspace_mode=WorkspaceMode.GREENFIELD,
        display_name="测试工作区",
        description="Workspace Context 单元测试工作区。",
        version="1.0.0",
        cloud="aws",
        is_mock=True,
        source_hash="a" * 64,
        sources=sources,
    )


def test_builder_splits_markdown_sections_and_sql_statements_into_stable_units() -> None:
    builder = WorkspaceContextBuilder()

    first = builder.build_units(_workspace())
    second = builder.build_units(_workspace())

    assert first == second
    assert len(first) == 23
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
        unit.unit_id
        for unit in first
        if unit.source_id == "source_ddl.rds_postgresql.rds-postgresql"
    ] == [
        "source_ddl.rds_postgresql.rds-postgresql:1",
        "source_ddl.rds_postgresql.rds-postgresql:2",
        "source_ddl.rds_postgresql.rds-postgresql:3",
        "source_ddl.rds_postgresql.rds-postgresql:4",
    ]
    assert all(len(unit.content_hash) == 64 for unit in first)
    assert all(unit.content.endswith("\n") for unit in first)


def test_customer_cdc_query_selects_rds_ddl_and_cdc_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 public.customer 的 customer_id 和 updated_at 设计 CDC 去重 DDL",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.DDL,
    )
    selected_ids = [item.unit_id for item in bundle.selected_units]

    assert "source_ddl.rds_postgresql.rds-postgresql:1" in selected_ids[:3]
    assert "rules:2" in selected_ids
    assert bundle.selected_units[0].reason == "lexical"
    assert "CREATE TABLE public.customer" in bundle.context
    assert "## CDC 与去重" in bundle.context


def test_pos_mapping_query_selects_schema_product_requirement_and_amount_rule() -> None:
    bundle = WorkspaceContextBuilder().build(
        "根据 source.pos_sales_line 的 order_id、quantity、unit_price 和 discount_amount "
        "生成每日销售 Mapping，并确认净销售金额口径",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.MAPPING,
    )
    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "source_ddl.pos_parquet.pos-parquet:1" in selected_ids
    assert "requirements:3" in selected_ids
    assert "rules:4" in selected_ids


def test_kinesis_notebook_query_selects_event_ingestion_and_late_data_units() -> None:
    bundle = WorkspaceContextBuilder().build(
        "为 source.order_event 使用 Kinesis 生成实时摄取 Notebook，并按 event_ts 处理迟到事件",
        workspace=_workspace(),
        purpose=WorkspaceContextPurpose.NOTEBOOK,
    )
    selected_ids = {item.unit_id for item in bundle.selected_units}

    assert "source_ddl.kinesis_events.kinesis-events:1" in selected_ids
    assert "requirements:4" in selected_ids
    assert "rules:3" in selected_ids


@pytest.mark.parametrize(
    ("purpose", "expected_first_units"),
    [
        (
            WorkspaceContextPurpose.DDL,
            (
                "requirements:3",
                "source_ddl.kinesis_events.kinesis-events:1",
                "rules:1",
            ),
        ),
        (
            WorkspaceContextPurpose.MAPPING,
            (
                "source_ddl.kinesis_events.kinesis-events:1",
                "rules:1",
                "requirements:3",
            ),
        ),
        (
            WorkspaceContextPurpose.SQL,
            (
                "requirements:3",
                "source_ddl.kinesis_events.kinesis-events:1",
                "rules:4",
            ),
        ),
        (
            WorkspaceContextPurpose.PYSPARK,
            (
                "requirements:4",
                "source_ddl.kinesis_events.kinesis-events:1",
                "rules:2",
            ),
        ),
        (
            WorkspaceContextPurpose.NOTEBOOK,
            (
                "requirements:4",
                "source_ddl.kinesis_events.kinesis-events:1",
                "rules:3",
            ),
        ),
    ],
)
def test_all_five_purposes_have_stable_fact_balanced_fallbacks(
    purpose: WorkspaceContextPurpose,
    expected_first_units: tuple[str, str, str],
) -> None:
    builder = WorkspaceContextBuilder()

    first = builder.build("火星火山地质勘探", workspace=_workspace(), purpose=purpose)
    second = builder.build("火星火山地质勘探", workspace=_workspace(), purpose=purpose)

    assert first == second
    assert tuple(item.unit_id for item in first.selected_units[:3]) == expected_first_units
    assert all(item.reason == "fallback" for item in first.selected_units)


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
        "public.customer customer_id",
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
