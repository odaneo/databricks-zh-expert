from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.prompts.registry import (
    DEFAULT_PROMPT,
    PROMPT_SPECS,
    PromptName,
)

EXPECTED_CONTEXT_POLICY = {
    PromptName.DATABRICKS_QA: (False, True),
    PromptName.KNOWLEDGE_QA: (True, False),
    PromptName.DDL_GENERATION: (True, True),
    PromptName.MAPPING_GENERATION: (True, True),
    PromptName.SQL_GENERATION: (True, True),
    PromptName.PYSPARK_GENERATION: (True, True),
    PromptName.NOTEBOOK_GENERATION: (True, True),
    PromptName.WORKFLOW_DESIGN: (True, True),
    PromptName.PROPOSAL_GENERATION: (True, True),
    PromptName.SELF_CHECK: (False, True),
    PromptName.DOCUMENT_SUMMARY: (False, False),
}


def test_prompt_names_are_fixed() -> None:
    assert tuple(PromptName) == (
        PromptName.DATABRICKS_QA,
        PromptName.DDL_GENERATION,
        PromptName.MAPPING_GENERATION,
        PromptName.SQL_GENERATION,
        PromptName.PYSPARK_GENERATION,
        PromptName.NOTEBOOK_GENERATION,
        PromptName.WORKFLOW_DESIGN,
        PromptName.DOCUMENT_SUMMARY,
        PromptName.KNOWLEDGE_QA,
        PromptName.PROPOSAL_GENERATION,
        PromptName.SELF_CHECK,
    )


def test_artifact_types_are_fixed() -> None:
    assert tuple(ArtifactType) == (
        ArtifactType.ANSWER,
        ArtifactType.SQL,
        ArtifactType.CSV,
        ArtifactType.PYSPARK,
        ArtifactType.NOTEBOOK,
        ArtifactType.WORKFLOW_DESIGN,
        ArtifactType.DOCUMENT_SUMMARY,
        ArtifactType.PROPOSAL,
        ArtifactType.CHECKLIST,
    )


def test_prompt_catalog_is_fixed_and_ordered() -> None:
    assert tuple(spec.name for spec in PROMPT_SPECS) == tuple(PromptName)
    assert DEFAULT_PROMPT is PromptName.DATABRICKS_QA


def test_every_artifact_type_has_an_available_prompt() -> None:
    available_artifacts = {spec.artifact_type for spec in PROMPT_SPECS if spec.available}

    assert available_artifacts == set(ArtifactType)


def test_knowledge_prompt_is_available_with_citation_contract() -> None:
    knowledge = next(spec for spec in PROMPT_SPECS if spec.name is PromptName.KNOWLEDGE_QA)

    assert knowledge.available is True
    assert knowledge.unavailable_reason is None
    assert knowledge.version == "1.2.0"
    assert knowledge.required_sections[-1] == "引用来源"


def test_code_prompts_declare_their_fence_languages() -> None:
    by_name = {spec.name: spec for spec in PROMPT_SPECS}

    assert by_name[PromptName.SQL_GENERATION].code_fence_language == "sql"
    assert by_name[PromptName.DDL_GENERATION].code_fence_language == "sql"
    assert by_name[PromptName.MAPPING_GENERATION].code_fence_language == "csv"
    assert by_name[PromptName.PYSPARK_GENERATION].code_fence_language == "python"
    assert by_name[PromptName.NOTEBOOK_GENERATION].code_fence_language == "python"
    assert all(
        spec.code_fence_language is None
        for spec in PROMPT_SPECS
        if spec.name
        not in {
            PromptName.DDL_GENERATION,
            PromptName.MAPPING_GENERATION,
            PromptName.SQL_GENERATION,
            PromptName.PYSPARK_GENERATION,
            PromptName.NOTEBOOK_GENERATION,
        }
    )


def test_every_prompt_has_a_semantic_version() -> None:
    versions = {spec.name: spec.version for spec in PROMPT_SPECS}

    assert versions[PromptName.KNOWLEDGE_QA] == "1.2.0"
    assert versions[PromptName.DDL_GENERATION] == "1.0.0"
    assert versions[PromptName.MAPPING_GENERATION] == "1.0.0"
    assert versions[PromptName.NOTEBOOK_GENERATION] == "1.0.0"
    assert versions[PromptName.SQL_GENERATION] == "1.1.0"
    assert versions[PromptName.PYSPARK_GENERATION] == "1.1.0"


def test_code_prompts_do_not_require_document_sections() -> None:
    code_prompt_names = {
        PromptName.SQL_GENERATION,
        PromptName.PYSPARK_GENERATION,
        PromptName.DDL_GENERATION,
        PromptName.MAPPING_GENERATION,
        PromptName.NOTEBOOK_GENERATION,
    }

    assert all(
        spec.required_sections == () for spec in PROMPT_SPECS if spec.name in code_prompt_names
    )
    assert all(
        spec.required_sections for spec in PROMPT_SPECS if spec.name not in code_prompt_names
    )


def test_prompt_context_policy_is_explicit() -> None:
    assert {
        spec.name: (spec.use_official_knowledge, spec.use_expert_templates) for spec in PROMPT_SPECS
    } == EXPECTED_CONTEXT_POLICY


def test_only_five_generation_prompts_use_workspace_context_and_create_proposals() -> None:
    workspace_prompts = {
        PromptName.DDL_GENERATION,
        PromptName.MAPPING_GENERATION,
        PromptName.SQL_GENERATION,
        PromptName.PYSPARK_GENERATION,
        PromptName.NOTEBOOK_GENERATION,
    }

    assert {spec.name for spec in PROMPT_SPECS if spec.use_workspace_context} == workspace_prompts
    assert {
        spec.name for spec in PROMPT_SPECS if spec.project_fact_status == "proposal"
    } == workspace_prompts
