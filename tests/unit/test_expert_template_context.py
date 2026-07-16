from uuid import UUID

import pytest

from databricks_zh_expert.expert_templates.context import (
    CandidateReason,
    ExpertTemplateContextBuilder,
    ExpertTemplateContextNotFoundError,
    ExpertTemplateDocument,
    RankedExpertTemplateCandidate,
)
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _document(
    value: int,
    template_id: str,
    *,
    content: str | None = None,
    layer: str = "core",
    profile_id: str | None = None,
    extends_record_id: UUID | None = None,
) -> ExpertTemplateDocument:
    return ExpertTemplateDocument(
        record_id=_uuid(value),
        template_id=template_id,
        version="1.0.0",
        name=f"模板 {template_id}",
        summary=f"{template_id} 摘要",
        kind=ExpertTemplateKind.BLUEPRINT,
        category=ExpertTemplateCategory.WORKFLOW,
        layer=layer,
        profile_id=profile_id,
        cloud="aws" if profile_id else "neutral",
        content_hash=f"{value:064x}",
        extends_record_id=extends_record_id,
        content=content or f"# 模板 {template_id}\n\n这是 {template_id} 的完整模板正文。\n",
        source_path="C:/private/expert-templates/template.md",
        official_refs=("https://docs.databricks.com/private-maintenance-ref",),
    )


def _candidate(
    document: ExpertTemplateDocument,
    *,
    value: int,
    fused_score: float,
    reason: CandidateReason = "semantic",
) -> RankedExpertTemplateCandidate:
    return RankedExpertTemplateCandidate(
        chunk_id=_uuid(1000 + value),
        template_record_id=document.record_id,
        template_id=document.template_id,
        version=document.version,
        name=document.name,
        layer=document.layer,
        profile_id=document.profile_id,
        kind=document.kind,
        category=document.category,
        content_hash=document.content_hash,
        extends_record_id=document.extends_record_id,
        matched_chunk_content=f"孤立 Chunk {value}",
        vector_similarity=0.9,
        lexical_score=0.2,
        vector_rank=value,
        lexical_rank=value,
        fused_score=fused_score,
        reason=reason,
    )


def test_context_uses_full_template_markdown_instead_of_matched_chunk() -> None:
    document = _document(
        1,
        "workflow.lakeflow_jobs",
        content="# Lakeflow Jobs\n\n完整模板正文中的重试、依赖与调度设计。\n",
    )
    builder = ExpertTemplateContextBuilder()

    bundle = builder.build(
        "设计工作流",
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        ranked_candidates=(_candidate(document, value=1, fused_score=0.04),),
        documents={document.record_id: document},
    )

    assert "完整模板正文中的重试、依赖与调度设计" in bundle.context
    assert "孤立 Chunk 1" not in bundle.context
    assert bundle.selected_templates[0].template_id == document.template_id


def test_context_limits_major_templates_and_deduplicates_inherited_parent() -> None:
    parent = _document(1, "workflow.lakeflow_jobs")
    overlay_one = _document(
        2,
        "retail.workflow_dag",
        layer="retail_sales_demo",
        profile_id="retail_sales_demo",
        extends_record_id=parent.record_id,
    )
    overlay_two = _document(
        3,
        "retail.workflow_variant",
        layer="retail_sales_demo",
        profile_id="retail_sales_demo",
        extends_record_id=parent.record_id,
    )
    core_two = _document(4, "pipeline.lakeflow_sdp")
    core_three = _document(5, "medallion.standard")
    ranked = (
        _candidate(overlay_one, value=1, fused_score=0.05),
        _candidate(overlay_two, value=2, fused_score=0.04),
        _candidate(core_two, value=3, fused_score=0.03),
        _candidate(core_three, value=4, fused_score=0.02),
    )
    documents = {
        item.record_id: item for item in (parent, overlay_one, overlay_two, core_two, core_three)
    }

    bundle = ExpertTemplateContextBuilder(top_k=3).build(
        "设计零售工作流",
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
        ranked_candidates=ranked,
        documents=documents,
    )

    selected_ids = tuple(item.template_id for item in bundle.selected_templates)
    assert selected_ids == (
        parent.template_id,
        overlay_one.template_id,
        overlay_two.template_id,
        core_two.template_id,
    )
    assert selected_ids.count(parent.template_id) == 1
    assert bundle.selected_templates[0].reason == "inherited"
    assert all(item.rank == index for index, item in enumerate(bundle.selected_templates, 1))


def test_context_skips_complete_template_that_exceeds_budget() -> None:
    oversized = _document(1, "oversized", content="# Oversized\n\n" + ("很长" * 400))
    compact = _document(2, "compact", content="# Compact\n\n可放入预算的完整正文。\n")
    builder = ExpertTemplateContextBuilder(
        max_context_tokens=700,
        token_counter=len,
    )

    bundle = builder.build(
        "预算测试",
        profile_id="generic",
        prompt_name=PromptName.DATABRICKS_QA,
        ranked_candidates=(
            _candidate(oversized, value=1, fused_score=0.04),
            _candidate(compact, value=2, fused_score=0.03),
        ),
        documents={oversized.record_id: oversized, compact.record_id: compact},
    )

    assert tuple(item.template_id for item in bundle.selected_templates) == ("compact",)
    assert bundle.context_token_count <= 700
    assert "可放入预算的完整正文" in bundle.context
    assert "很长很长" not in bundle.context


def test_context_states_priority_and_never_renders_paths_or_official_refs() -> None:
    document = _document(1, "governance.unity_catalog")

    bundle = ExpertTemplateContextBuilder().build(
        "设计权限",
        profile_id="generic",
        prompt_name=PromptName.DATABRICKS_QA,
        ranked_candidates=(_candidate(document, value=1, fused_score=0.04),),
        documents={document.record_id: document},
    )

    assert "以下内容是内部专家模板" in bundle.context
    assert "系统安全和产品边界" in bundle.context
    assert "用户本轮明确要求" in bundle.context
    assert "Databricks 官方文档事实" in bundle.context
    assert "项目覆盖层假设" in bundle.context
    assert "通用模板默认建议" in bundle.context
    assert "C:/private" not in bundle.context
    assert "private-maintenance-ref" not in bundle.context


def test_context_raises_when_no_complete_template_fits_budget() -> None:
    document = _document(1, "oversized", content="# Oversized\n\n" + ("长" * 500))

    with pytest.raises(ExpertTemplateContextNotFoundError):
        ExpertTemplateContextBuilder(
            max_context_tokens=50,
            token_counter=len,
        ).build(
            "预算测试",
            profile_id="generic",
            prompt_name=PromptName.DATABRICKS_QA,
            ranked_candidates=(_candidate(document, value=1, fused_score=0.04),),
            documents={document.record_id: document},
        )
