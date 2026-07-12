from dataclasses import replace

import pytest
from jinja2 import DictLoader, UndefinedError

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.prompts.registry import (
    DEFAULT_PROMPT,
    PROMPT_SPECS,
    PromptName,
    PromptRegistry,
    PromptSpec,
    PromptUnavailableError,
)
from databricks_zh_expert.prompts.renderer import JinjaPromptRenderer


class RecordingRenderer:
    def __init__(self, content: str = "已渲染") -> None:
        self.content = content
        self.rendered: list[PromptName] = []

    def render(self, spec: PromptSpec) -> str:
        self.rendered.append(spec.name)
        return self.content


def test_default_prompt_renders_a_chinese_system_message() -> None:
    rendered = PromptRegistry.create_default().render(None)

    assert rendered.name is PromptName.DATABRICKS_QA
    assert rendered.version == "1.0.1"
    assert rendered.artifact_type is ArtifactType.ANSWER
    assert "始终使用中文" in rendered.system_message
    assert "## 结论" in rendered.system_message
    assert "{{" not in rendered.system_message
    assert "{%" not in rendered.system_message


def test_sql_prompt_uses_a_compact_code_contract() -> None:
    rendered = PromptRegistry.create_default().render(PromptName.SQL_GENERATION)

    assert rendered.artifact_type is ArtifactType.SQL
    assert "语言标识为 `sql`" in rendered.system_message
    assert "不输出一级标题或固定文档章节" in rendered.system_message
    assert "简短代码注释" in rendered.system_message
    assert "必要时可在代码块后简短补充" in rendered.system_message
    assert "## 使用场景" not in rendered.system_message


def test_pyspark_prompt_uses_a_compact_code_contract() -> None:
    rendered = PromptRegistry.create_default().render(PromptName.PYSPARK_GENERATION)

    assert rendered.artifact_type is ArtifactType.PYSPARK
    assert "语言标识为 `python`" in rendered.system_message
    assert "不输出一级标题或固定文档章节" in rendered.system_message
    assert "## PySpark 代码" not in rendered.system_message


def test_workflow_prompt_contains_its_document_sections() -> None:
    rendered = PromptRegistry.create_default().render(PromptName.WORKFLOW_DESIGN)

    assert "第一行必须是唯一的一级标题" in rendered.system_message
    assert "根据用户需求生成简短、具体的一级标题" in rendered.system_message
    assert "不得使用 `# 标题`" in rendered.system_message
    assert "## Bronze 层设计" in rendered.system_message
    assert "## Job 依赖关系" in rendered.system_message
    assert "## 后续确认事项" in rendered.system_message


def test_reserved_prompt_is_rejected_before_rendering() -> None:
    renderer = RecordingRenderer()
    registry = PromptRegistry(
        renderer=renderer,
        prompts=PROMPT_SPECS,
        default_prompt=DEFAULT_PROMPT,
    )

    with pytest.raises(PromptUnavailableError) as caught:
        registry.render(PromptName.KNOWLEDGE_QA)

    assert caught.value.spec.name is PromptName.KNOWLEDGE_QA
    assert renderer.rendered == []


def test_validate_all_checks_reserved_templates_too() -> None:
    renderer = RecordingRenderer()
    registry = PromptRegistry(
        renderer=renderer,
        prompts=PROMPT_SPECS,
        default_prompt=DEFAULT_PROMPT,
    )

    registry.validate_all()

    assert renderer.rendered == list(PromptName)


def test_jinja_renderer_uses_strict_undefined() -> None:
    renderer = JinjaPromptRenderer(loader=DictLoader({"broken.jinja2": "{{ missing_value }}"}))
    spec = replace(PROMPT_SPECS[0], template_name="broken.jinja2")

    with pytest.raises(UndefinedError):
        renderer.render(spec)


def test_registry_rejects_an_empty_rendered_prompt() -> None:
    registry = PromptRegistry(
        renderer=RecordingRenderer("  \n"),
        prompts=PROMPT_SPECS,
        default_prompt=DEFAULT_PROMPT,
    )

    with pytest.raises(ValueError, match="Prompt 模板渲染结果不能为空"):
        registry.render(PromptName.DATABRICKS_QA)


def test_registry_exposes_fixed_prompt_metadata() -> None:
    registry = PromptRegistry.create_default()

    assert registry.default_prompt is PromptName.DATABRICKS_QA
    assert registry.prompts == PROMPT_SPECS
    assert registry.get(PromptName.SELF_CHECK).artifact_type is ArtifactType.CHECKLIST
