from typing import TYPE_CHECKING, Protocol

from jinja2 import BaseLoader, Environment, PackageLoader, StrictUndefined

if TYPE_CHECKING:
    from databricks_zh_expert.prompts.registry import PromptSpec


class PromptRenderer(Protocol):
    def render(self, spec: "PromptSpec") -> str: ...


class JinjaPromptRenderer:
    def __init__(self, loader: BaseLoader | None = None) -> None:
        self._environment = Environment(
            loader=(
                loader
                if loader is not None
                else PackageLoader("databricks_zh_expert.prompts", "templates")
            ),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

    def render(self, spec: "PromptSpec") -> str:
        template = self._environment.get_template(spec.template_name)
        return template.render(
            required_sections=spec.required_sections,
            code_fence_language=spec.code_fence_language,
            use_workspace_context=spec.use_workspace_context,
            project_fact_status=spec.project_fact_status,
        )
