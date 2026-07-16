import re
from collections import Counter

from databricks_zh_expert.expert_templates.registry import ExpertTemplateRegistry
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName

EXPECTED_CORE_IDS = {
    "ingestion.s3_auto_loader",
    "ingestion.dms_s3_cdc",
    "ingestion.kinesis_streaming",
    "medallion.standard",
    "pipeline.lakeflow_sdp",
    "workflow.lakeflow_jobs",
    "governance.unity_catalog",
    "governance.pii_protection",
    "decision.ingestion_mode",
    "decision.pipeline_dataset_type",
    "decision.scd_type",
    "decision.incremental_replay_backfill",
    "code.autoloader_pyspark",
    "code.dms_cdc_apply_pyspark",
    "code.kinesis_pyspark",
    "code.quality_expectations_python",
    "code.delta_merge_sql",
    "code.gold_aggregation_sql",
    "checklist.ingestion_and_schema",
    "checklist.data_quality",
    "checklist.workflow_monitoring",
    "checklist.unity_catalog_pii",
    "checklist.performance",
    "checklist.cost",
    "checklist.production_readiness",
    "deliverable.architecture_design",
    "deliverable.table_design",
    "deliverable.job_design",
    "deliverable.technical_proposal",
}

EXPECTED_RETAIL_IDS = {
    "retail.project_context",
    "retail.source_contracts",
    "retail.end_to_end_architecture",
    "retail.medallion_mapping",
    "retail.workflow_dag",
    "retail.unity_catalog_access",
    "retail.gold_data_products",
    "retail.production_acceptance",
}

EXPECTED_RETAIL_EXTENDS = {
    "retail.end_to_end_architecture": "pipeline.lakeflow_sdp",
    "retail.medallion_mapping": "medallion.standard",
    "retail.workflow_dag": "workflow.lakeflow_jobs",
    "retail.unity_catalog_access": "governance.unity_catalog",
    "retail.gold_data_products": "medallion.standard",
    "retail.production_acceptance": "checklist.production_readiness",
}

EXPERT_PROMPTS = {
    PromptName.DATABRICKS_QA,
    PromptName.SQL_GENERATION,
    PromptName.PYSPARK_GENERATION,
    PromptName.WORKFLOW_DESIGN,
    PromptName.PROPOSAL_GENERATION,
    PromptName.SELF_CHECK,
}


def test_production_core_template_catalog_is_complete() -> None:
    registry = ExpertTemplateRegistry.create_default()
    core = tuple(template for template in registry.templates if template.layer == "core")

    assert {template.template_id for template in core} == EXPECTED_CORE_IDS
    assert len(core) == 29
    assert all(not template.is_mock and template.profile_id is None for template in core)
    assert Counter(template.kind for template in core) == {
        ExpertTemplateKind.BLUEPRINT: 8,
        ExpertTemplateKind.DECISION_GUIDE: 4,
        ExpertTemplateKind.CODE_PATTERN: 6,
        ExpertTemplateKind.CHECKLIST: 7,
        ExpertTemplateKind.DELIVERABLE: 4,
    }


def test_generic_profile_defines_valid_core_defaults_for_every_expert_prompt() -> None:
    registry = ExpertTemplateRegistry.create_default()
    profile = registry.get_profile("generic")

    assert set(profile.prompt_defaults) == EXPERT_PROMPTS
    for prompt_name, template_ids in profile.prompt_defaults.items():
        assert template_ids
        for template_id in template_ids:
            template = registry.get_template(template_id)
            assert template.layer == "core"
            assert prompt_name in template.prompt_names
            assert template.cloud == "neutral"


def test_retail_profile_contains_confirmed_mock_architecture() -> None:
    registry = ExpertTemplateRegistry.create_default()
    retail = tuple(
        template for template in registry.templates if template.layer == "retail_sales_demo"
    )

    assert {template.template_id for template in retail} == EXPECTED_RETAIL_IDS
    assert len(retail) == 8
    assert all(
        template.is_mock and template.cloud == "aws" and template.profile_id == "retail_sales_demo"
        for template in retail
    )
    assert Counter(template.kind for template in retail) == {
        ExpertTemplateKind.BLUEPRINT: 5,
        ExpertTemplateKind.DELIVERABLE: 2,
        ExpertTemplateKind.CHECKLIST: 1,
    }

    joined = "\n".join(template.content for template in retail)
    for required_text in (
        "AWS DMS",
        "S3 Parquet",
        "Auto Loader",
        "Kinesis",
        "Lakeflow Spark Declarative Pipelines",
        "5 分钟",
        "15 分钟",
        "07:30",
        "99.5%",
    ):
        assert required_text in joined


def test_retail_assets_cover_products_roles_pii_and_core_inheritance() -> None:
    registry = ExpertTemplateRegistry.create_default()
    retail = tuple(
        template for template in registry.templates if template.layer == "retail_sales_demo"
    )
    joined = "\n".join(template.content for template in retail)

    for product in (
        "每日销售分析",
        "商品表现分析",
        "库存健康分析",
        "客户与渠道分析",
    ):
        assert product in joined
    for role in ("data_engineer", "analyst", "marketing", "finance", "auditor"):
        assert role in joined
    for pii_boundary in (
        "Bronze 原始客户数据",
        "Silver 对联系方式进行标准化和脱敏",
        "Gold 不暴露原始姓名、邮箱、手机号或地址",
    ):
        assert pii_boundary in joined

    assert all("模拟项目" in template.content for template in retail)
    assert {
        template.template_id: template.extends_template_id
        for template in retail
        if template.extends_template_id is not None
    } == EXPECTED_RETAIL_EXTENDS
    for parent_id in EXPECTED_RETAIL_EXTENDS.values():
        assert registry.get_template(parent_id).layer == "core"


def test_retail_profile_uses_overlay_defaults_for_project_prompts() -> None:
    registry = ExpertTemplateRegistry.create_default()
    profile = registry.get_profile("retail_sales_demo")

    assert profile.layers == ("core", "retail_sales_demo")
    assert set(profile.prompt_defaults) == EXPERT_PROMPTS
    assert profile.prompt_defaults[PromptName.WORKFLOW_DESIGN] == (
        "retail.workflow_dag",
        "retail.end_to_end_architecture",
    )
    assert profile.prompt_defaults[PromptName.PROPOSAL_GENERATION] == (
        "retail.project_context",
        "retail.end_to_end_architecture",
    )
    assert profile.prompt_defaults[PromptName.SELF_CHECK] == ("retail.production_acceptance",)

    for prompt_name, template_ids in profile.prompt_defaults.items():
        assert template_ids
        for template_id in template_ids:
            template = registry.get_template(template_id)
            assert template.layer in profile.layers
            assert prompt_name in template.prompt_names
            assert template.cloud in {"neutral", profile.cloud}


def test_core_assets_have_versioned_metadata_and_https_maintenance_refs() -> None:
    registry = ExpertTemplateRegistry.create_default()
    core = tuple(template for template in registry.templates if template.layer == "core")

    assert all(template.version == "1.0.0" for template in core)
    assert all(template.official_refs for template in core)
    assert all(
        reference.startswith("https://")
        for template in core
        for reference in template.official_refs
    )
    assert len({template.content_hash for template in core}) == len(core)


def test_code_patterns_use_the_expected_fenced_language() -> None:
    registry = ExpertTemplateRegistry.create_default()
    code_patterns = tuple(
        template
        for template in registry.templates
        if template.kind is ExpertTemplateKind.CODE_PATTERN
    )

    for template in code_patterns:
        expected_language = "sql" if template.category is ExpertTemplateCategory.SQL else "python"
        assert re.search(rf"^```{expected_language}\s*$", template.content, re.MULTILINE)


def test_core_content_is_specific_and_contains_no_unsafe_claims_or_credentials() -> None:
    registry = ExpertTemplateRegistry.create_default()
    core = tuple(template for template in registry.templates if template.layer == "core")
    forbidden_phrases = (
        "Public Preview",
        "Experimental",
        "真实客户",
        "已经执行成功",
    )
    credential_assignment = re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?key|secret|password)\s*[:=]\s*[^\s<]+"
    )
    aws_access_key = re.compile(r"AKIA[0-9A-Z]{16}")

    for template in core:
        assert 180 <= len(template.content) <= 8_000
        assert all(phrase not in template.content for phrase in forbidden_phrases)
        assert credential_assignment.search(template.content) is None
        assert aws_access_key.search(template.content) is None
