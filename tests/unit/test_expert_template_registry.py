from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from databricks_zh_expert.expert_templates.constants import (
    EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS,
    EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS,
    EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K,
    EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS,
    EXPERT_TEMPLATE_MIN_VECTOR_SCORE,
    EXPERT_TEMPLATE_ROOT,
    EXPERT_TEMPLATE_TOP_K,
    EXPERT_TEMPLATE_VECTOR_CANDIDATE_K,
)
from databricks_zh_expert.expert_templates.registry import (
    ExpertTemplateRegistry,
    ExpertTemplateRegistryError,
)
from databricks_zh_expert.expert_templates.types import (
    ExpertTemplateCategory,
    ExpertTemplateKind,
)
from databricks_zh_expert.prompts.registry import PromptName

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "expert_templates"
EXPERT_PROMPTS = (
    "databricks_qa",
    "ddl_generation",
    "mapping_generation",
    "sql_generation",
    "pyspark_generation",
    "notebook_generation",
    "workflow_design",
    "proposal_generation",
    "self_check",
)


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def _prompt_defaults(template_id: str = "medallion.standard") -> dict[str, list[str]]:
    return {prompt: [template_id] for prompt in EXPERT_PROMPTS}


def _profiles_yaml(*, include_unknown_generic_field: bool = False) -> str:
    generic: dict[str, object] = {
        "id": "generic",
        "display_name": "通用 Databricks 顾问",
        "description": "只使用通用核心专家模板。",
        "cloud": "neutral",
        "layers": ["core"],
        "is_mock": False,
        "default": True,
        "prompt_defaults": _prompt_defaults(),
    }
    if include_unknown_generic_field:
        generic["unexpected"] = True
    payload = {
        "version": 1,
        "profiles": [
            generic,
            {
                "id": "retail_sales_demo",
                "display_name": "AWS 零售销售 Demo",
                "description": "使用通用核心层和 AWS 零售销售模拟覆盖层。",
                "cloud": "aws",
                "layers": ["core", "retail_sales_demo"],
                "is_mock": True,
                "default": False,
                "prompt_defaults": _prompt_defaults(),
            },
        ],
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _template_markdown(
    *,
    template_id: str = "medallion.standard",
    name: str = "通用 Medallion 分层设计",
    version: str = "1.0.0",
    kind: str = "blueprint",
    category: str = "medallion",
    layer: str = "core",
    profile: str | None = None,
    cloud: str = "neutral",
    prompt_names: tuple[str, ...] = EXPERT_PROMPTS,
    extends: str | None = None,
    is_mock: bool = False,
    include_unknown_front_matter_field: bool = False,
    body: str | None = None,
) -> str:
    metadata: dict[str, object] = {
        "id": template_id,
        "name": name,
        "summary": "定义 Bronze、Silver、Gold 的职责、输入输出和质量边界。",
        "version": version,
        "kind": kind,
        "category": category,
        "layer": layer,
        "profile": profile,
        "cloud": cloud,
        "prompt_names": list(prompt_names),
        "tags": ["bronze", "silver", "gold"],
        "extends": extends,
        "is_mock": is_mock,
        "official_refs": ["https://docs.databricks.com/aws/en/lakehouse/medallion"],
    }
    if include_unknown_front_matter_field:
        metadata["unexpected"] = True
    rendered_body = dedent(
        body
        or f"""
        # {name}

        ## 适用场景

        用于设计可复用的数据分层边界。

        ## 实施步骤

        1. 明确每一层的输入、输出和质量责任。
        """
    ).strip()
    front_matter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front_matter}\n---\n\n{rendered_body}\n"


def build_template_fixture(root: Path, *, mutation: str | None = None) -> Path:
    profiles = _profiles_yaml()
    base = _template_markdown()
    extra_templates: list[tuple[str, str]] = []

    if mutation == "unknown_front_matter_field":
        base = _template_markdown(include_unknown_front_matter_field=True)
    elif mutation == "invalid_semver":
        base = _template_markdown(version="1.0")
    elif mutation == "h1_name_mismatch":
        base = _template_markdown(
            body="""
            # 不匹配的标题

            ## 适用场景

            正文。

            ## 实施步骤

            1. 验证标题。
            """
        )
    elif mutation == "unknown_prompt":
        base = _template_markdown(prompt_names=(*EXPERT_PROMPTS, "not_registered"))
    elif mutation == "inheritance_cycle":
        base = _template_markdown(extends="medallion.foundation")
        extra_templates.append(
            (
                "core/blueprints/medallion-foundation.md",
                _template_markdown(
                    template_id="medallion.foundation",
                    name="通用分层基础",
                    extends="medallion.standard",
                ),
            )
        )
    elif mutation == "overlay_extends_overlay":
        extra_templates.extend(
            (
                (
                    "overlays/retail_sales_demo/blueprints/retail-parent.md",
                    _template_markdown(
                        template_id="retail.parent",
                        name="零售父模板",
                        layer="retail_sales_demo",
                        profile="retail_sales_demo",
                        cloud="aws",
                        is_mock=True,
                    ),
                ),
                (
                    "overlays/retail_sales_demo/blueprints/retail-child.md",
                    _template_markdown(
                        template_id="retail.child",
                        name="零售子模板",
                        layer="retail_sales_demo",
                        profile="retail_sales_demo",
                        cloud="aws",
                        extends="retail.parent",
                        is_mock=True,
                    ),
                ),
            )
        )
    elif mutation == "raw_html":
        base = _template_markdown(
            body="""
            # 通用 Medallion 分层设计

            ## 适用场景

            <div>不允许的 HTML</div>

            ## 实施步骤

            1. 验证正文。
            """
        )
    elif mutation == "jinja_expression":
        base = _template_markdown(
            body="""
            # 通用 Medallion 分层设计

            ## 适用场景

            使用 {{ runtime_value }}。

            ## 实施步骤

            1. 验证正文。
            """
        )
    elif mutation == "nested_front_matter":
        base = _template_markdown(
            body="""
            # 通用 Medallion 分层设计

            ## 适用场景

            用于验证嵌套元数据。

            ---
            owner: hidden
            ---

            ## 实施步骤

            1. 拒绝第二段 Front Matter。
            """
        )
    elif mutation == "missing_required_section":
        base = _template_markdown(
            body="""
            # 通用 Medallion 分层设计

            ## 背景

            只有背景信息。
            """
        )
    elif mutation == "code_pattern_without_fence":
        extra_templates.append(
            (
                "core/code_patterns/delta-merge.md",
                _template_markdown(
                    template_id="code.delta_merge_sql",
                    name="Delta MERGE SQL 模式",
                    kind="code_pattern",
                    category="sql",
                    prompt_names=("sql_generation",),
                ),
            )
        )
    elif mutation == "unknown_profile_field":
        profiles = _profiles_yaml(include_unknown_generic_field=True)

    _write(root, "profiles.yml", profiles)
    _write(root, "core/blueprints/medallion-standard.md", base)
    for relative_path, content in extra_templates:
        _write(root, relative_path, content)
    return root


def test_fixed_template_constants_and_enums() -> None:
    assert EXPERT_TEMPLATE_ROOT == Path("knowledge/expert_templates")
    assert EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS == 800
    assert EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS == 80
    assert EXPERT_TEMPLATE_VECTOR_CANDIDATE_K == 20
    assert EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K == 20
    assert EXPERT_TEMPLATE_TOP_K == 3
    assert EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS == 2500
    assert EXPERT_TEMPLATE_MIN_VECTOR_SCORE == 0.30
    assert tuple(ExpertTemplateKind) == (
        ExpertTemplateKind.BLUEPRINT,
        ExpertTemplateKind.DECISION_GUIDE,
        ExpertTemplateKind.CODE_PATTERN,
        ExpertTemplateKind.CHECKLIST,
        ExpertTemplateKind.DELIVERABLE,
    )
    assert tuple(ExpertTemplateCategory) == (
        ExpertTemplateCategory.INGESTION,
        ExpertTemplateCategory.MEDALLION,
        ExpertTemplateCategory.PIPELINE,
        ExpertTemplateCategory.WORKFLOW,
        ExpertTemplateCategory.GOVERNANCE,
        ExpertTemplateCategory.DATA_QUALITY,
        ExpertTemplateCategory.SQL,
        ExpertTemplateCategory.PYSPARK,
        ExpertTemplateCategory.PERFORMANCE,
        ExpertTemplateCategory.COST,
        ExpertTemplateCategory.DELIVERY,
    )


def test_registry_loads_valid_profile_and_template() -> None:
    registry = ExpertTemplateRegistry.load(FIXTURE_ROOT / "valid")

    assert registry.default_profile_id == "generic"
    assert tuple(profile.id for profile in registry.profiles) == (
        "generic",
        "retail_sales_demo",
    )
    assert registry.get_profile("generic").layers == ("core",)
    assert registry.get_profile("generic").prompt_defaults[PromptName.DATABRICKS_QA] == (
        "medallion.standard",
    )
    template = registry.get_template("medallion.standard")
    assert template.version == "1.0.0"
    assert template.source_path == "core/blueprints/medallion-standard.md"
    assert template.content.startswith("# 通用 Medallion 分层设计\n")
    assert "\r" not in template.content
    assert len(template.content_hash) == 64
    assert len(registry.source_hash) == 64


def test_registry_hash_is_stable_across_newline_styles(tmp_path: Path) -> None:
    lf_root = build_template_fixture(tmp_path / "lf")
    crlf_root = build_template_fixture(tmp_path / "crlf")
    for path in crlf_root.rglob("*"):
        if path.is_file():
            content = path.read_bytes().replace(b"\n", b"\r\n")
            path.write_bytes(content)

    assert (
        ExpertTemplateRegistry.load(lf_root).source_hash
        == ExpertTemplateRegistry.load(crlf_root).source_hash
    )


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("unknown_front_matter_field", "包含未知字段"),
        ("invalid_semver", "版本必须使用 MAJOR.MINOR.PATCH"),
        ("h1_name_mismatch", "一级标题必须等于模板名称"),
        ("unknown_prompt", "Prompt 未注册"),
        ("inheritance_cycle", "模板继承存在循环"),
        ("overlay_extends_overlay", "覆盖层只能扩展 core 模板"),
        ("raw_html", "禁止原始 HTML"),
        ("jinja_expression", "禁止 Jinja 表达式"),
        ("nested_front_matter", "禁止嵌套 Front Matter"),
        ("missing_required_section", "必须包含“适用场景”"),
        ("code_pattern_without_fence", "必须包含 sql 代码围栏"),
        ("unknown_profile_field", "包含未知字段"),
    ],
)
def test_registry_rejects_invalid_assets(
    tmp_path: Path,
    mutation: str,
    expected_message: str,
) -> None:
    root = build_template_fixture(tmp_path, mutation=mutation)

    with pytest.raises(ExpertTemplateRegistryError, match=expected_message):
        ExpertTemplateRegistry.load(root)


def test_registry_errors_do_not_leak_absolute_paths(tmp_path: Path) -> None:
    root = build_template_fixture(tmp_path, mutation="invalid_semver")

    with pytest.raises(ExpertTemplateRegistryError) as error:
        ExpertTemplateRegistry.load(root)

    assert str(root.resolve()) not in str(error.value)


def test_registry_rejects_unknown_lookup_ids() -> None:
    registry = ExpertTemplateRegistry.load(FIXTURE_ROOT / "valid")

    with pytest.raises(ExpertTemplateRegistryError, match="专家 Profile 未注册"):
        registry.get_profile("unknown")
    with pytest.raises(ExpertTemplateRegistryError, match="专家模板未注册"):
        registry.get_template("unknown")
