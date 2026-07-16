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


def test_both_profiles_define_valid_core_defaults_for_every_expert_prompt() -> None:
    registry = ExpertTemplateRegistry.create_default()

    for profile_id in ("generic", "retail_sales_demo"):
        profile = registry.get_profile(profile_id)
        assert set(profile.prompt_defaults) == EXPERT_PROMPTS
        for prompt_name, template_ids in profile.prompt_defaults.items():
            assert template_ids
            for template_id in template_ids:
                template = registry.get_template(template_id)
                assert template.layer == "core"
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
