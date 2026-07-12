from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.prompts.registry import (
    DEFAULT_PROMPT,
    PROMPT_SPECS,
    PromptName,
)


def test_prompt_names_are_fixed() -> None:
    assert tuple(PromptName) == (
        PromptName.DATABRICKS_QA,
        PromptName.SQL_GENERATION,
        PromptName.PYSPARK_GENERATION,
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
        ArtifactType.PYSPARK,
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


def test_knowledge_prompt_is_reserved_for_stage_four() -> None:
    knowledge = next(spec for spec in PROMPT_SPECS if spec.name is PromptName.KNOWLEDGE_QA)

    assert knowledge.available is False
    assert knowledge.unavailable_reason == "预置 Databricks 知识库将在阶段 4 启用。"


def test_code_prompts_declare_their_fence_languages() -> None:
    by_name = {spec.name: spec for spec in PROMPT_SPECS}

    assert by_name[PromptName.SQL_GENERATION].code_fence_language == "sql"
    assert by_name[PromptName.PYSPARK_GENERATION].code_fence_language == "python"
    assert all(
        spec.code_fence_language is None
        for spec in PROMPT_SPECS
        if spec.name not in {PromptName.SQL_GENERATION, PromptName.PYSPARK_GENERATION}
    )


def test_every_prompt_has_a_semantic_version() -> None:
    assert all(spec.version == "1.0.1" for spec in PROMPT_SPECS)


def test_code_prompts_do_not_require_document_sections() -> None:
    code_prompt_names = {
        PromptName.SQL_GENERATION,
        PromptName.PYSPARK_GENERATION,
    }

    assert all(
        spec.required_sections == () for spec in PROMPT_SPECS if spec.name in code_prompt_names
    )
    assert all(
        spec.required_sections for spec in PROMPT_SPECS if spec.name not in code_prompt_names
    )
