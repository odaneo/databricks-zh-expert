from uuid import uuid4

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.evaluation.dataset import (
    END_TO_END_EVALUATION_PATH,
    load_evaluation_dataset,
)
from databricks_zh_expert.evaluation.rules import score_case
from databricks_zh_expert.evaluation.types import EvaluationEvidence
from databricks_zh_expert.llm.model_registry import ModelAlias
from databricks_zh_expert.prompts.registry import PromptName


def _case(case_id: str):
    dataset = load_evaluation_dataset(END_TO_END_EVALUATION_PATH)
    return next(case for case in dataset.cases if case.id == case_id)


def _evidence(**overrides: object) -> EvaluationEvidence:
    model_call_id = uuid4()
    values: dict[str, object] = {
        "http_status": 201,
        "requested_model": ModelAlias.DEEPSEEK_V4_FLASH,
        "used_model": ModelAlias.DEEPSEEK_V4_FLASH,
        "fallback_used": False,
        "attempt_count": 1,
        "prompt_name": PromptName.SQL_GENERATION,
        "prompt_version": "1.1.0",
        "artifact_type": ArtifactType.SQL,
        "project_fact_status": "proposal",
        "assistant_content": (
            "```sql\nSELECT o.order_date, "
            "SUM(od.unit_price * od.quantity * (1 - od.discount)) AS net_sales\n"
            "FROM orders o JOIN order_details od ON o.order_id = od.order_id\n"
            "GROUP BY o.order_date;\n```"
        ),
        "citation_urls": ("https://docs.databricks.com/aws/en/sql/",),
        "model_call_ids": (model_call_id,),
        "trace_model_call_ids": (model_call_id,),
        "model_call_success": True,
        "artifact_valid": True,
        "workspace_id": "northwind_psql",
        "workspace_version": "1.0.0",
        "workspace_source_hash": "a" * 64,
        "workspace_unit_ids": (
            "source_ddl.northwind.northwind-schema:7",
            "source_ddl.northwind.northwind-schema:8",
            "rules:4",
        ),
        "workspace_source_paths": (
            ".databricks-expert/source-schema/northwind-schema.sql",
            ".databricks-expert/business-rules.md",
        ),
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "latency_ms": 500,
        "error_code": None,
        "error_message": None,
    }
    values.update(overrides)
    return EvaluationEvidence.model_validate(values)


def test_score_case_passes_complete_sql_evidence_deterministically() -> None:
    case = _case("nw_sql_daily_sales")
    evidence = _evidence()

    first = score_case(case, evidence)
    second = score_case(case, evidence)

    assert first == second
    assert first.hard_passed is True
    assert first.soft_score == 1.0
    assert first.automated_passed is True
    assert first.manual_review.required is True
    assert first.manual_review.status.value == "pending"


def test_score_case_fails_fallback_missing_trace_and_workspace_unit() -> None:
    case = _case("nw_sql_daily_sales")
    evidence = _evidence(
        used_model=ModelAlias.DEEPSEEK_V4_PRO,
        fallback_used=True,
        attempt_count=2,
        trace_model_call_ids=(),
        workspace_unit_ids=("source_ddl.northwind.northwind-schema:8",),
    )

    result = score_case(case, evidence)

    assert result.hard_passed is False
    assert result.automated_passed is False
    assert {rule.rule_id for rule in result.hard_rules if not rule.passed} >= {
        "model_no_fallback",
        "trace_complete",
        "workspace_expected_units",
    }


def test_score_case_accepts_missing_field_explanation_but_rejects_generated_store_sql() -> None:
    case = _case("nw_sql_missing_field")
    safe = _evidence(
        assistant_content=(
            "```sql\n-- orders.store_id 在源 Schema 中不存在，无法生成门店聚合。\n"
            "SELECT order_id FROM orders;\n```"
        ),
        workspace_unit_ids=("source_ddl.northwind.northwind-schema:8",),
    )
    unsafe = safe.model_copy(
        update={
            "assistant_content": (
                "```sql\nSELECT store_id, COUNT(*) FROM orders GROUP BY store_id;\n```"
            )
        }
    )

    assert score_case(case, safe).hard_passed is True
    assert score_case(case, unsafe).hard_passed is False


def test_score_case_ignores_forbidden_terms_in_sql_comments() -> None:
    case = _case("nw_sql_customer_value")
    safe = _evidence(
        assistant_content=(
            "```sql\n"
            "-- email 不在源 Schema 中，不得使用。\n"
            "SELECT c.customer_id, COUNT(DISTINCT o.order_id),\n"
            "       SUM(od.unit_price * od.quantity * (1 - od.discount)) AS net_sales\n"
            "FROM customers c\n"
            "JOIN orders o ON o.customer_id = c.customer_id\n"
            "JOIN order_details od ON od.order_id = o.order_id\n"
            "GROUP BY c.customer_id;\n"
            "```"
        ),
        workspace_unit_ids=(
            "source_ddl.northwind.northwind-schema:4",
            "source_ddl.northwind.northwind-schema:8",
            "source_ddl.northwind.northwind-schema:29",
        ),
    )
    unsafe = safe.model_copy(
        update={
            "assistant_content": safe.assistant_content.replace(
                "c.customer_id, COUNT", "c.customer_id, c.email, COUNT"
            )
        }
    )

    assert score_case(case, safe).hard_passed is True
    assert score_case(case, unsafe).hard_passed is False


def test_score_case_requires_official_citation_domain() -> None:
    case = _case("generic_unity_catalog")
    evidence = _evidence(
        prompt_name=PromptName.KNOWLEDGE_QA,
        artifact_type=ArtifactType.ANSWER,
        project_fact_status=None,
        assistant_content=(
            "# Unity Catalog 最小权限\n\n"
            "## 结论\n采用最小权限。\n\n"
            "## 适用场景\n生产治理。\n\n"
            "## 详细说明\n按主体授予 USE CATALOG、USE SCHEMA 和 SELECT。\n\n"
            "## 注意事项\n审计授权。\n\n"
            "## 人工确认事项\n确认主体。\n\n"
            "## 引用来源\n见结构化引用。"
        ),
        citation_urls=("https://example.com/unity-catalog",),
        workspace_id="northwind_psql",
        workspace_version=None,
        workspace_source_hash=None,
        workspace_unit_ids=(),
        workspace_source_paths=(),
    )

    result = score_case(case, evidence)

    assert result.hard_passed is False
    assert "official_citation_domain" in {
        rule.rule_id for rule in result.hard_rules if not rule.passed
    }


def test_score_case_allows_deployment_question_but_rejects_completed_claim() -> None:
    case = _case("generic_project_proposal")
    content = """# AWS Databricks 项目提案

## 项目背景
已知事实：项目运行在 AWS。设计假设：采用分层架构。

## 目标与范围
范围待确认。

## 方案设计
设计假设需要评审。

## 实施计划
按里程碑实施和验收。

## 交付物
提案与代码草稿。

## 风险与应对
需求尚未确定。

## 待确认事项
是否已经部署 DMS？
"""
    safe = _evidence(
        prompt_name=PromptName.PROPOSAL_GENERATION,
        artifact_type=ArtifactType.PROPOSAL,
        project_fact_status=None,
        assistant_content=content,
        workspace_id=None,
        workspace_version=None,
        workspace_source_hash=None,
        workspace_unit_ids=(),
        workspace_source_paths=(),
    )
    unsafe = safe.model_copy(
        update={"assistant_content": content.replace("是否已经部署 DMS？", "项目已经部署完成。")}
    )

    assert score_case(case, safe).hard_passed is True
    assert score_case(case, unsafe).hard_passed is False


def test_workflow_allows_alert_email_but_rejects_customer_email_field() -> None:
    case = _case("nw_workflow_customer_product")

    assert "email" not in case.expected.forbidden_terms
    assert any("customer" in pattern for pattern in case.expected.forbidden_patterns)
