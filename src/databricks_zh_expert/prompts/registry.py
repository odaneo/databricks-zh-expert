from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from databricks_zh_expert.artifacts.types import ArtifactType
from databricks_zh_expert.prompts.renderer import JinjaPromptRenderer, PromptRenderer


class PromptName(StrEnum):
    DATABRICKS_QA = "databricks_qa"
    SQL_GENERATION = "sql_generation"
    PYSPARK_GENERATION = "pyspark_generation"
    WORKFLOW_DESIGN = "workflow_design"
    DOCUMENT_SUMMARY = "document_summary"
    KNOWLEDGE_QA = "knowledge_qa"
    PROPOSAL_GENERATION = "proposal_generation"
    SELF_CHECK = "self_check"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: PromptName
    display_name: str
    description: str
    template_name: str
    version: str
    artifact_type: ArtifactType
    required_sections: tuple[str, ...]
    code_fence_language: str | None
    available: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    name: PromptName
    version: str
    artifact_type: ArtifactType
    system_message: str


DEFAULT_PROMPT: Final[PromptName] = PromptName.DATABRICKS_QA

_ANSWER_SECTIONS: Final = (
    "结论",
    "适用场景",
    "详细说明",
    "注意事项",
    "人工确认事项",
)

PROMPT_SPECS: Final[tuple[PromptSpec, ...]] = (
    PromptSpec(
        name=PromptName.DATABRICKS_QA,
        display_name="Databricks 顾问问答",
        description="回答 Databricks 相关问题并给出实施建议和人工确认项。",
        template_name="databricks_qa.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.ANSWER,
        required_sections=_ANSWER_SECTIONS,
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.SQL_GENERATION,
        display_name="Databricks SQL",
        description="直接生成带简短注释的 Databricks SQL 草稿。",
        template_name="sql_generation.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.SQL,
        required_sections=(),
        code_fence_language="sql",
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.PYSPARK_GENERATION,
        display_name="PySpark",
        description="直接生成带简短注释的 PySpark 草稿。",
        template_name="pyspark_generation.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.PYSPARK,
        required_sections=(),
        code_fence_language="python",
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.WORKFLOW_DESIGN,
        display_name="Databricks 工作流设计",
        description="把业务需求拆分为分层数据设计、作业依赖、调度和监控方案。",
        template_name="workflow_design.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.WORKFLOW_DESIGN,
        required_sections=(
            "需求理解",
            "数据源假设",
            "Bronze 层设计",
            "Silver 层设计",
            "Gold 层设计",
            "Notebook 拆分",
            "Job 依赖关系",
            "调度建议",
            "监控点",
            "风险点",
            "后续确认事项",
        ),
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.DOCUMENT_SUMMARY,
        display_name="文档内容摘要",
        description="总结当前会话中提供的文档或文本，不补写原文不存在的事实。",
        template_name="document_summary.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.DOCUMENT_SUMMARY,
        required_sections=(
            "摘要",
            "核心要点",
            "术语与字段",
            "风险与限制",
            "待确认事项",
        ),
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.KNOWLEDGE_QA,
        display_name="预置知识库问答",
        description="依据预置 Databricks 知识库检索上下文回答并给出来源。",
        template_name="knowledge_qa.jinja2",
        version="1.2.0",
        artifact_type=ArtifactType.ANSWER,
        required_sections=(*_ANSWER_SECTIONS, "引用来源"),
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.PROPOSAL_GENERATION,
        display_name="提案或设计书草案",
        description="生成包含范围、实施步骤、交付物和风险的项目提案草案。",
        template_name="proposal_generation.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.PROPOSAL,
        required_sections=(
            "项目背景",
            "目标与范围",
            "方案设计",
            "实施计划",
            "交付物",
            "风险与应对",
            "待确认事项",
        ),
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
    PromptSpec(
        name=PromptName.SELF_CHECK,
        display_name="交付物自检",
        description="检查当前会话中的交付物并区分通过项、问题项和修改建议。",
        template_name="self_check.jinja2",
        version="1.0.1",
        artifact_type=ArtifactType.CHECKLIST,
        required_sections=(
            "检查对象",
            "通过项",
            "问题项",
            "修改建议",
            "人工确认事项",
        ),
        code_fence_language=None,
        available=True,
        unavailable_reason=None,
    ),
)


class PromptUnavailableError(ValueError):
    def __init__(self, spec: PromptSpec) -> None:
        self.spec = spec
        super().__init__(spec.unavailable_reason or "Prompt 当前不可用。")


class PromptRegistry:
    def __init__(
        self,
        *,
        renderer: PromptRenderer,
        prompts: tuple[PromptSpec, ...],
        default_prompt: PromptName,
    ) -> None:
        self._renderer = renderer
        self._prompts = prompts
        self._default_prompt = default_prompt
        self._by_name = {spec.name: spec for spec in prompts}

    @property
    def default_prompt(self) -> PromptName:
        return self._default_prompt

    @property
    def prompts(self) -> tuple[PromptSpec, ...]:
        return self._prompts

    @classmethod
    def create_default(cls) -> "PromptRegistry":
        return cls(
            renderer=JinjaPromptRenderer(),
            prompts=PROMPT_SPECS,
            default_prompt=DEFAULT_PROMPT,
        )

    def get(self, name: PromptName) -> PromptSpec:
        return self._by_name[name]

    def render(self, requested: PromptName | None) -> RenderedPrompt:
        spec = self.get(requested or self.default_prompt)
        if not spec.available:
            raise PromptUnavailableError(spec)
        return self._render_spec(spec)

    def validate_all(self) -> None:
        for spec in self.prompts:
            self._render_spec(spec)

    def _render_spec(self, spec: PromptSpec) -> RenderedPrompt:
        system_message = self._renderer.render(spec).strip()
        if not system_message:
            raise ValueError(f"Prompt 模板渲染结果不能为空：{spec.name}。")
        return RenderedPrompt(
            name=spec.name,
            version=spec.version,
            artifact_type=spec.artifact_type,
            system_message=system_message,
        )
