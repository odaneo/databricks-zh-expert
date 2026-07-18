# 阶段 5：Databricks 专家模板库实施计划

> **执行要求：** 使用 `superpowers:executing-plans` 在当前会话逐任务执行；按用户偏好不使用子智能体。
> 每个任务先写失败测试，再做最小实现，验证通过后按用户指示提交。不得清理任何验收数据。

**目标：** 在现有顾问型 Agent 中增加受 Git 管理、独立持久化、自动检索和完整审计的 Databricks 专家模板库，并提供通用核心层与 AWS 零售销售项目覆盖层。

**架构：** Markdown + YAML Front Matter 是唯一真源；显式 CLI 将模板增量、原子地同步到 PostgreSQL 独立表。ChatService 根据不可变会话 Profile 和 Prompt 策略组合官方 RAG 与专家模板上下文，官方引用与项目经验保持分离，模型调用通过 Trace 和 `model_calls` JSONB 审计。

**技术栈：** Python 3.12.10、FastAPI、Pydantic 2、PyYAML、markdown-it-py、tiktoken、SQLAlchemy 2、Alembic、PostgreSQL、pgvector、OpenAI Embedding、LiteLLM、pytest、Ruff、Pyright、uv。

**当前状态：** 实现、真实验收和代码提交均已完成。真实索引包含 37 个 active 模板和 121 个
Chunk；固定评估 Recall@3 为 96.67%，Profile 泄漏和继承遗漏均为 0；两次 DeepSeek 冒烟及 Trace 1.5 已保留。

## 全局约束

1. 第一版只支持 `generic` 与 `retail_sales_demo` 两个文件注册 Profile；默认值固定为 `generic`。
2. 模板真源固定为当前仓库 `knowledge/expert_templates/`，不创建新 Git 仓库或远程内容服务。
3. 模板、Profile、检索预算和 Prompt 策略都是跨环境产品行为，不新增阶段 5 环境变量。
4. PostgreSQL 继续使用当前配置的非 `public` Schema，不新增数据库、Docker 服务或向量数据库。
5. 专家数据只能写入 `expert_templates`、`expert_template_chunks`、`expert_template_sync_runs`，不得混入 `kb_*`。
6. `messages.source_citations` 只能保存官方知识引用，不能保存项目模板。
7. 模板选择不增加分类模型或 rerank 模型；官方与专家检索复用一次查询 Embedding。
8. 不使用 Preview 或 Experimental 功能，不执行 Databricks、AWS、SQL、PySpark、Job 或 Pipeline 操作。
9. 所有模板、文档、API 描述和错误消息使用中文；标识符、字段、表名和命令使用英文。
10. 代码型模板保持简短，以代码和必要注释为主，不生成固定长篇章节。
11. 修改 Python 后必须运行 Ruff 与 Pyright/Pylance；数据库改动必须运行 Alembic 检查。
12. 不清理现有或新增的会话、消息、模型调用、知识数据、模板数据和真实 Trace。
13. README 只允许增加专家索引所必需的一条启动步骤，不加入内部架构说明或预期输出。

---

## 已确认设计

详细产品边界、数据模型、Prompt 矩阵和完成定义见：

`docs/superpowers/specs/2026-07-16-stage-5-databricks-expert-template-library-design.md`

实施期间若发现与规格冲突的新事实，先停止相关任务并记录影响，不静默改变 Profile、引用、Preview、错误或
审计边界。

## 基线

开始任务 1 前确认：

```powershell
git status --short
uv lock --check
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
```

阶段 4 收尾基线为 306 个测试通过、覆盖率 90.30%、Ruff 通过、Pyright 0 errors、Alembic 无待生成迁移。
若开始实施时基线已经变化，以当时 `main` 的真实结果记录到任务 1 提交说明中，不回退用户已有修改。

## 目标文件结构

```text
knowledge/expert_templates/
  profiles.yml
  core/
    blueprints/*.md
    decision_guides/*.md
    code_patterns/*.md
    checklists/*.md
    deliverables/*.md
  overlays/retail_sales_demo/*.md

src/databricks_zh_expert/
  expert_templates/
    __init__.py
    constants.py
    types.py
    registry.py
    repository.py
    sync.py
    retrieval.py
    context.py
    evaluation.py
    cli.py
  search/
    __init__.py
    markdown.py
    hybrid.py
  api/
    expert_template_schemas.py
    expert_templates.py
  chat/
    context.py

tests/
  evals/expert_templates.yml
  fixtures/expert_templates/
  unit/test_expert_template_*.py
  unit/test_search_*.py
  integration/test_expert_template_*.py

alembic/versions/0007_expert_templates.py
```

## 任务顺序

1. 固定模板契约、Profile 和 Registry。
2. 编写通用核心专家资产。
3. 编写 AWS 零售销售项目覆盖层。
4. 创建数据库迁移和 ORM 模型。
5. 抽取共享 Markdown Chunk 与混合排序内核。
6. 实现专家模板原子同步、Repository 和 CLI。
7. 实现专家模板检索、上下文和固定评估。
8. 实现会话 Profile、只读 API 和 readiness。
9. 集成 ChatService、双通道上下文、数据库审计和 Trace 1.5。
10. 执行完整评估、真实冒烟和阶段收尾。

---

### 任务 1：固定模板契约、Profile 和 Registry

**文件：**

- Create: `src/databricks_zh_expert/expert_templates/__init__.py`
- Create: `src/databricks_zh_expert/expert_templates/constants.py`
- Create: `src/databricks_zh_expert/expert_templates/types.py`
- Create: `src/databricks_zh_expert/expert_templates/registry.py`
- Create: `tests/unit/test_expert_template_registry.py`
- Create: `tests/fixtures/expert_templates/valid/profiles.yml`
- Create: `tests/fixtures/expert_templates/valid/core/blueprints/medallion-standard.md`

**接口：**

- Produces: `ExpertTemplateKind`、`ExpertTemplateCategory`、`ExpertProfile`、`ExpertTemplateSource`。
- Produces: `ExpertTemplateRegistry.load(root: Path) -> ExpertTemplateRegistry`。
- Produces: `ExpertTemplateRegistry.create_default() -> ExpertTemplateRegistry`。
- Produces: `get_profile(profile_id: str) -> ExpertProfile`、`get_template(template_id: str) -> ExpertTemplateSource`。
- Produces: `profiles`、`templates`、`default_profile_id`、`source_hash` 只读属性。
- Consumes: 现有 `PromptName`、PyYAML、markdown-it-py，不访问数据库或网络。

- [x] **Step 1: 先写 Registry 失败测试**

在 `tests/unit/test_expert_template_registry.py` 固定以下行为：

```python
def test_registry_loads_valid_profile_and_template() -> None:
    registry = ExpertTemplateRegistry.load(FIXTURE_ROOT / "valid")

    assert registry.default_profile_id == "generic"
    assert registry.get_profile("generic").layers == ("core",)
    assert registry.get_template("medallion.standard").version == "1.0.0"
    assert len(registry.source_hash) == 64


@pytest.mark.parametrize(
    "mutation, expected_message",
    [
        ("unknown_front_matter_field", "包含未知字段"),
        ("invalid_semver", "版本必须使用 MAJOR.MINOR.PATCH"),
        ("h1_name_mismatch", "一级标题必须等于模板名称"),
        ("unknown_prompt", "Prompt 未注册"),
        ("inheritance_cycle", "模板继承存在循环"),
        ("overlay_extends_overlay", "覆盖层只能扩展 core 模板"),
    ],
)
def test_registry_rejects_invalid_assets(tmp_path: Path, mutation: str, expected_message: str) -> None:
    root = build_template_fixture(tmp_path, mutation=mutation)

    with pytest.raises(ExpertTemplateRegistryError, match=expected_message):
        ExpertTemplateRegistry.load(root)
```

测试辅助函数必须在测试文件内写出完整、最小的 YAML 和 Markdown，不依赖生产资产。

- [x] **Step 2: 运行测试并确认因模块不存在而失败**

```powershell
uv run --locked pytest tests/unit/test_expert_template_registry.py -q
```

预期：FAIL，错误包含 `ModuleNotFoundError: databricks_zh_expert.expert_templates`。

- [x] **Step 3: 实现严格类型与固定常量**

在 `constants.py` 定义规格中的根目录、Chunk、候选、top-k、token 和分数常量；不得读取 `.env`：

```python
EXPERT_TEMPLATE_ROOT = Path("knowledge/expert_templates")
EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS = 800
EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS = 80
EXPERT_TEMPLATE_VECTOR_CANDIDATE_K = 20
EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K = 20
EXPERT_TEMPLATE_TOP_K = 3
EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS = 2500
EXPERT_TEMPLATE_MIN_VECTOR_SCORE = 0.30
```

在 `types.py` 使用冻结 dataclass 和 `StrEnum` 定义规格中的五种 kind、十一种 category，以及：

```python
@dataclass(frozen=True, slots=True)
class ExpertTemplateSource:
    template_id: str
    name: str
    summary: str
    version: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: str
    profile_id: str | None
    cloud: str
    prompt_names: tuple[PromptName, ...]
    tags: tuple[str, ...]
    extends_template_id: str | None
    official_refs: tuple[str, ...]
    source_path: str
    content: str
    content_hash: str
```

- [x] **Step 4: 实现安全 Front Matter 与 Markdown Registry**

`registry.py` 必须：

1. 使用 `yaml.safe_load()` 和 Pydantic `extra="forbid"` 校验 YAML。
2. 规范化 CRLF 为 LF，使用相对 POSIX `source_path`。
3. 使用 markdown-it token 校验唯一 H1、原始 HTML、代码围栏和必要章节。
4. 校验 Profile 默认值、Prompt 默认模板、layer、cloud 和继承关系。
5. 对排序后的 `profiles.yml` 与 Markdown 内容 Hash 计算稳定 `source_hash`。
6. 抛出只包含中文安全信息的 `ExpertTemplateRegistryError`，不泄露绝对路径。

- [x] **Step 5: 运行 Registry 测试**

```powershell
uv run --locked pytest tests/unit/test_expert_template_registry.py -q
```

预期：PASS。

- [x] **Step 6: 运行静态检查**

```powershell
uv run --locked ruff format src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_registry.py
uv run --locked ruff check src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_registry.py
uv run --locked pyright
```

预期：Ruff 通过，Pyright 0 errors。

- [x] **Step 7: 提交任务 1**

```powershell
git add src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_registry.py tests/fixtures/expert_templates
git commit -m "feat: add expert template registry"
```

---

### 任务 2：编写通用核心专家资产

**文件：**

- Create: `knowledge/expert_templates/profiles.yml`
- Create: `knowledge/expert_templates/core/blueprints/s3-auto-loader.md`
- Create: `knowledge/expert_templates/core/blueprints/dms-s3-cdc.md`
- Create: `knowledge/expert_templates/core/blueprints/kinesis-streaming.md`
- Create: `knowledge/expert_templates/core/blueprints/medallion-standard.md`
- Create: `knowledge/expert_templates/core/blueprints/lakeflow-sdp.md`
- Create: `knowledge/expert_templates/core/blueprints/lakeflow-jobs.md`
- Create: `knowledge/expert_templates/core/blueprints/unity-catalog.md`
- Create: `knowledge/expert_templates/core/blueprints/pii-protection.md`
- Create: `knowledge/expert_templates/core/decision_guides/ingestion-mode.md`
- Create: `knowledge/expert_templates/core/decision_guides/pipeline-dataset-type.md`
- Create: `knowledge/expert_templates/core/decision_guides/scd-type.md`
- Create: `knowledge/expert_templates/core/decision_guides/incremental-replay-backfill.md`
- Create: `knowledge/expert_templates/core/code_patterns/autoloader-pyspark.md`
- Create: `knowledge/expert_templates/core/code_patterns/dms-cdc-apply-pyspark.md`
- Create: `knowledge/expert_templates/core/code_patterns/kinesis-pyspark.md`
- Create: `knowledge/expert_templates/core/code_patterns/quality-expectations-python.md`
- Create: `knowledge/expert_templates/core/code_patterns/delta-merge-sql.md`
- Create: `knowledge/expert_templates/core/code_patterns/gold-aggregation-sql.md`
- Create: `knowledge/expert_templates/core/checklists/ingestion-and-schema.md`
- Create: `knowledge/expert_templates/core/checklists/data-quality.md`
- Create: `knowledge/expert_templates/core/checklists/workflow-monitoring.md`
- Create: `knowledge/expert_templates/core/checklists/unity-catalog-pii.md`
- Create: `knowledge/expert_templates/core/checklists/performance.md`
- Create: `knowledge/expert_templates/core/checklists/cost.md`
- Create: `knowledge/expert_templates/core/checklists/production-readiness.md`
- Create: `knowledge/expert_templates/core/deliverables/architecture-design.md`
- Create: `knowledge/expert_templates/core/deliverables/table-design.md`
- Create: `knowledge/expert_templates/core/deliverables/job-design.md`
- Create: `knowledge/expert_templates/core/deliverables/technical-proposal.md`
- Create: `tests/unit/test_expert_template_content.py`

**接口：**

- Consumes: 任务 1 `ExpertTemplateRegistry` 和 Front Matter 契约。
- Produces: 29 个 `layer=core` 的 active 源资产。
- Produces: `generic` Profile 六个专家启用 Prompt 的默认模板映射。
- Produces: 暂时注册 `retail_sales_demo`，其默认模板先指向 core；任务 3 再切换到覆盖资产。

- [x] **Step 1: 写生产资产目录测试**

```python
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


def test_production_core_template_catalog_is_complete() -> None:
    registry = ExpertTemplateRegistry.create_default()
    core = {template.template_id for template in registry.templates if template.layer == "core"}

    assert core == EXPECTED_CORE_IDS
    assert all(template.profile_id is None for template in registry.templates if template.layer == "core")
```

另加测试保证六个专家启用 Prompt 均有默认模板、全部 `official_refs` 使用 HTTPS、代码模板含正确 fenced
language，任何正文都不包含凭据样式或“已经执行成功”断言。

- [x] **Step 2: 运行测试并确认生产目录不存在**

```powershell
uv run --locked pytest tests/unit/test_expert_template_content.py -q
```

预期：FAIL，错误指出 `knowledge/expert_templates/profiles.yml` 不存在。

- [x] **Step 3: 编写 Profile 清单和 29 个核心资产**

每个文件必须使用规格中的完整 Front Matter，版本从 `1.0.0` 开始。正文原则：

1. blueprint 明确适用场景、输入、设计决策、风险和人工确认项。
2. decision guide 给出选择条件和不适用条件，不写唯一正确答案。
3. code pattern 直接给短代码与必要注释，不加七段式长文。
4. checklist 使用可执行检查项，不写泛化“遵循最佳实践”。
5. deliverable 给交付结构、字段和确认点，不重复 Prompt 模板的输出契约。
6. 引用当前官方 Docs 或 AWS 文档时只写维护链接，不复制长篇原文。
7. 不写 Preview 功能、价格、虚构基准、真实客户或已运行结果。

- [x] **Step 4: 运行内容和 Registry 测试**

```powershell
uv run --locked pytest tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py -q
```

预期：PASS，生产 Registry 加载 29 个 core 模板。

- [x] **Step 5: 检查模板长度和重复内容**

```powershell
Get-ChildItem knowledge/expert_templates/core -Recurse -Filter *.md | ForEach-Object { "{0}`t{1}" -f $_.Length, $_.FullName }
rg -n "Public Preview|Experimental|真实客户|已经执行成功" knowledge/expert_templates/core
```

预期：每个资产内容非空且尺寸合理；第二条命令无命中。人工抽查相邻模板没有整段重复。

- [x] **Step 6: 运行文档相关静态检查**

```powershell
uv run --locked ruff check src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_content.py
uv run --locked pyright
```

预期：全部通过。

- [x] **Step 7: 提交任务 2**

```powershell
git add knowledge/expert_templates src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_content.py
git commit -m "feat: add core databricks expert templates"
```

---

### 任务 3：编写 AWS 零售销售项目覆盖层

**文件：**

- Modify: `knowledge/expert_templates/profiles.yml`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/project-context.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/source-contracts.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/end-to-end-architecture.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/medallion-mapping.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/workflow-dag.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/unity-catalog-access.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/gold-data-products.md`
- Create: `knowledge/expert_templates/overlays/retail_sales_demo/production-acceptance.md`
- Modify: `tests/unit/test_expert_template_content.py`

**接口：**

- Consumes: 任务 2 的 core ID。
- Produces: 八个 `layer=retail_sales_demo`、`profile=retail_sales_demo`、`cloud=aws` 资产。
- Produces: Profile 的零售默认模板映射和六条显式 `extends` 关系。

- [x] **Step 1: 写覆盖层业务契约测试**

```python
def test_retail_profile_contains_confirmed_mock_architecture() -> None:
    registry = ExpertTemplateRegistry.create_default()
    retail = tuple(
        template for template in registry.templates if template.layer == "retail_sales_demo"
    )

    assert len(retail) == 8
    assert all(template.cloud == "aws" for template in retail)
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
```

另加断言覆盖四个 Gold 数据产品、五类角色、PII 边界和父模板存在性。

- [x] **Step 2: 运行测试并确认覆盖资产缺失**

```powershell
uv run --locked pytest tests/unit/test_expert_template_content.py -q
```

预期：FAIL，零售模板数量为 0。

- [x] **Step 3: 编写八个连贯的零售覆盖资产**

内容必须共享同一套项目词汇和字段假设：

```text
S3: POS 日销售与供应商商品文件
RDS PostgreSQL: customer、product、store、inventory
AWS DMS: full load + CDC 到 S3 Parquet
Kinesis: order、payment、customer_behavior 事件
Catalog: retail_dev、retail_test、retail_prod
Schema: bronze、silver、gold、ops
角色: data_engineer、analyst、marketing、finance、auditor
```

Gold 资产固定覆盖每日销售、商品表现、库存健康、客户与渠道。PII 原始联系方式只能出现在受限 Bronze
假设中，Gold 只能保留分析标识和非直接识别属性。

- [x] **Step 4: 更新零售 Profile 默认模板**

`profiles.yml` 中 `retail_sales_demo` 保留 core + overlay 两层，并至少把：

```yaml
workflow_design: [retail.workflow_dag, retail.end_to_end_architecture]
proposal_generation: [retail.project_context, retail.end_to_end_architecture]
self_check: [retail.production_acceptance]
```

作为无语义命中时的默认值。默认映射引用的模板必须对相应 Prompt 可用。

- [x] **Step 5: 运行 Registry 和内容测试**

```powershell
uv run --locked pytest tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py -q
```

预期：PASS，总资产数为 37，零售层为 8，继承无循环。

- [x] **Step 6: 运行静态检查并提交任务 3**

```powershell
uv run --locked ruff check src tests/unit/test_expert_template_content.py
uv run --locked pyright
git add knowledge/expert_templates tests/unit/test_expert_template_content.py
git commit -m "feat: add retail sales expert profile"
```

---

### 任务 4：创建专家模板数据库迁移和 ORM 模型

**文件：**

- Create: `alembic/versions/0007_expert_templates.py`
- Modify: `src/databricks_zh_expert/db/models.py`
- Modify: `tests/unit/test_models.py`
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_sessions_api.py`

**接口：**

- Produces: ORM `ExpertTemplateRecord`、`ExpertTemplateChunkRecord`、`ExpertTemplateSyncRun`。
- Produces: `ChatSession.expert_profile: str`，数据库默认 `generic`。
- Produces: `ModelCall.expert_profile: str | None`、`expert_template_selections: list[dict[str, Any]] | None`。
- Consumes: 阶段 4 已启用的 PostgreSQL `vector` 扩展和当前 Schema。

- [x] **Step 1: 扩展 ORM 与迁移测试断言**

在 `tests/unit/test_models.py` 把预期表集合扩展为九张表，并断言：

```python
assert ChatSession.__table__.c.expert_profile.nullable is False
assert ModelCall.__table__.c.expert_profile.nullable is True
assert ModelCall.__table__.c.expert_template_selections.nullable is True
assert ExpertTemplateChunkRecord.__table__.c.embedding.type.dim == 1536
```

在迁移测试中执行 0006 -> 0007 -> 0006 -> 0007，确认历史 session 变为 `generic`，历史 model_call 两字段
保持 NULL，三个新表和索引可重复创建与删除。

- [x] **Step 2: 运行模型与迁移测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py -q
```

预期：FAIL，缺少 0007 和专家 ORM。

- [x] **Step 3: 实现 `0007_expert_templates`**

迁移必须一次完成：

1. `sessions.expert_profile VARCHAR(100) NOT NULL SERVER DEFAULT 'generic'`。
2. `model_calls.expert_profile` 与 `expert_template_selections JSONB` 可空。
3. 三张专家表、规格中的 CheckConstraint、唯一约束、FK 和时间字段。
4. `expert_template_chunks.embedding vector(1536)`。
5. generated `search_vector = to_tsvector('simple', content)` 与 GIN 索引。
6. `template_id` active 部分唯一索引：`WHERE status = 'active'`。
7. downgrade 先删 Chunk、模板和运行表，再删新增列；不修改原有业务表内容。

- [x] **Step 4: 实现 ORM 模型**

类名和表名固定为：

```python
class ExpertTemplateRecord(Base):
    __tablename__ = "expert_templates"


class ExpertTemplateChunkRecord(Base):
    __tablename__ = "expert_template_chunks"


class ExpertTemplateSyncRun(Base):
    __tablename__ = "expert_template_sync_runs"
```

三张专家表中的非空 JSONB 数组使用 `default=list` 与数据库 `server_default='[]'::jsonb`；历史
`model_calls` 两个新增字段保持可空且不加 server default。`extends_id` 使用自引用 FK，删除策略为
RESTRICT。

- [x] **Step 5: 运行迁移、模型和会话回归测试**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py -q
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

预期：聚焦测试通过，current 为 0007，Alembic 无新操作。

- [x] **Step 6: 运行静态检查并提交任务 4**

```powershell
uv run --locked ruff format alembic/versions/0007_expert_templates.py src/databricks_zh_expert/db/models.py tests/unit/test_models.py tests/integration/test_migrations.py
uv run --locked ruff check .
uv run --locked pyright
git add alembic/versions/0007_expert_templates.py src/databricks_zh_expert/db/models.py tests/unit/test_models.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py
git commit -m "feat: add expert template schema"
```

---

### 任务 5：抽取共享 Markdown Chunk 与混合排序内核

**文件：**

- Create: `src/databricks_zh_expert/search/__init__.py`
- Create: `src/databricks_zh_expert/search/markdown.py`
- Create: `src/databricks_zh_expert/search/hybrid.py`
- Modify: `src/databricks_zh_expert/rag/chunker.py`
- Modify: `src/databricks_zh_expert/rag/retrieval.py`
- Create: `tests/unit/test_search_markdown.py`
- Create: `tests/unit/test_search_hybrid.py`
- Modify: `tests/unit/test_knowledge_chunker.py`
- Modify: `tests/unit/test_knowledge_retrieval.py`

**接口：**

- Produces: 通用 `MarkdownSource`、`MarkdownChunk`、`MarkdownChunker`。
- Produces: `FusionRank` 与 `reciprocal_rank_fusion_ids()`。
- Produces: `extract_lexical_query()` 共享实现。
- Preserves: `rag.chunker.MarkdownChunker.split(NormalizedDocument)` 和阶段 4 排序的外部行为。

- [x] **Step 1: 写共享组件契约测试**

```python
def test_shared_markdown_chunker_is_deterministic() -> None:
    source = MarkdownSource(
        title="测试模板",
        source_ref="expert-template://test@1.0.0",
        content="# 测试模板\n\n## 适用场景\n\n正文。\n",
    )
    chunker = MarkdownChunker(chunk_size_tokens=80, chunk_overlap_tokens=10)

    assert chunker.split(source) == chunker.split(source)


def test_rrf_ids_returns_stable_ranks() -> None:
    result = reciprocal_rank_fusion_ids(
        vector_ids=(UUID(int=1), UUID(int=2)),
        lexical_ids=(UUID(int=2), UUID(int=3)),
        rrf_k=60,
    )

    assert [item.item_id for item in result] == [UUID(int=2), UUID(int=1), UUID(int=3)]
```

- [x] **Step 2: 运行共享与阶段 4 回归测试并确认新测试失败**

```powershell
uv run --locked pytest tests/unit/test_search_markdown.py tests/unit/test_search_hybrid.py tests/unit/test_knowledge_chunker.py tests/unit/test_knowledge_retrieval.py -q
```

预期：新模块不存在；原阶段 4 测试仍通过。

- [x] **Step 3: 移动通用 Chunk 实现并保留 RAG 适配器**

共享接口固定为：

```python
@dataclass(frozen=True, slots=True)
class MarkdownSource:
    title: str
    source_ref: str
    content: str
    heading_anchors: tuple[str | None, ...] = ()


@dataclass(frozen=True, slots=True)
class MarkdownChunk:
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    token_count: int
    source_ref: str
```

`rag/chunker.py` 只负责把 `NormalizedDocument` 转为 `MarkdownSource`，并把共享 Chunk 暴露为兼容的
`KnowledgeChunk`。不得改变阶段 4 anchor 修复、代码围栏、token 窗口和 source_ref 行为。

- [x] **Step 4: 抽取共享词法查询与 RRF ID 排名**

`search/hybrid.py` 返回不携带业务正文的稳定排名：

```python
@dataclass(frozen=True, slots=True)
class FusionRank:
    item_id: UUID
    vector_rank: int | None
    lexical_rank: int | None
    fused_score: float
```

阶段 4 `rag/retrieval.py` 使用该结果重新组装 `RankedKnowledgeChunk`，所有既有测试结果必须完全一致。

- [x] **Step 5: 运行共享和完整阶段 4 检索测试**

```powershell
uv run --locked pytest tests/unit/test_search_markdown.py tests/unit/test_search_hybrid.py tests/unit/test_knowledge_chunker.py tests/unit/test_knowledge_retrieval.py tests/unit/test_rag_context.py tests/unit/test_knowledge_eval.py -q
```

预期：全部通过，阶段 4 Recall 相关测试无回归。

- [x] **Step 6: 运行静态检查并提交任务 5**

```powershell
uv run --locked ruff format src/databricks_zh_expert/search src/databricks_zh_expert/rag tests/unit/test_search_markdown.py tests/unit/test_search_hybrid.py
uv run --locked ruff check .
uv run --locked pyright
git add src/databricks_zh_expert/search src/databricks_zh_expert/rag/chunker.py src/databricks_zh_expert/rag/retrieval.py tests/unit/test_search_markdown.py tests/unit/test_search_hybrid.py tests/unit/test_knowledge_chunker.py tests/unit/test_knowledge_retrieval.py
git commit -m "refactor: share markdown and hybrid search primitives"
```

---

### 任务 6：实现专家模板原子同步、Repository 和 CLI

**文件：**

- Create: `src/databricks_zh_expert/expert_templates/repository.py`
- Create: `src/databricks_zh_expert/expert_templates/sync.py`
- Create: `src/databricks_zh_expert/expert_templates/cli.py`
- Modify: `src/databricks_zh_expert/expert_templates/types.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/unit/test_expert_template_sync.py`
- Create: `tests/unit/test_expert_template_cli.py`
- Create: `tests/integration/test_expert_template_repository.py`

**接口：**

- Produces: `ExpertTemplateRepository` 的运行、状态、发布、失活和元数据查询接口。
- Produces: `ExpertTemplateSyncService.sync(registry, *, dry_run: bool = False)`。
- Produces: `ExpertTemplateIndexStatus` 与 `ExpertTemplateSyncResult`。
- Produces: 控制台脚本 `databricks-zh-expert-templates` 的 `sync`、`sync --dry-run`、`status`。
- Consumes: 任务 1 Registry、任务 4 ORM、任务 5 共享 Chunk、阶段 4 `OpenAIEmbeddingClient`。

任务 6 使用的跨层 DTO 固定为：

```python
@dataclass(frozen=True, slots=True)
class TemplateVersionState:
    record_id: UUID
    template_id: str
    version: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class PreparedTemplateVersion:
    source: ExpertTemplateSource
    chunks: tuple[MarkdownChunk, ...]
    embeddings: tuple[EmbeddingResult, ...]


@dataclass(frozen=True, slots=True)
class PreparedTemplateSnapshot:
    source_hash: str
    templates: tuple[PreparedTemplateVersion, ...]
    active_template_ids: frozenset[str]
    synced_at: datetime


@dataclass(frozen=True, slots=True)
class SyncRunCompletion:
    status: Literal["succeeded", "failed"]
    discovered_count: int
    inserted_count: int
    activated_count: int
    inactivated_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    error_summary: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class TemplateListQuery:
    profile_id: str | None = None
    kind: ExpertTemplateKind | None = None
    category: ExpertTemplateCategory | None = None
    limit: int = 100
    offset: int = 0
```

`ExpertTemplateIndexStatus` 必须包含 latest_run_status、source_hash_matches、active_template_count、chunk_count、
embedding_model、embedding_dimensions 和 queryable；`ExpertTemplateSyncResult` 使用与完成记录相同的计数字段，
并增加 run_id、source_hash 与 dry_run。

- [x] **Step 1: 写原子同步单元测试**

使用 Fake Repository 和 Fake EmbeddingClient 固定以下状态机：

```python
async def test_sync_embeds_only_new_versions_and_publishes_once() -> None:
    result = await service.sync(registry)

    assert result.discovered_count == 37
    assert result.inserted_count == 37
    assert result.failed_count == 0
    assert repository.publish_calls == 1


async def test_sync_rejects_same_version_with_changed_hash() -> None:
    repository.active_states["medallion.standard"] = TemplateVersionState(
        version="1.0.0",
        content_hash="0" * 64,
    )

    with pytest.raises(ExpertTemplateSyncError, match="内容变化但版本未升级"):
        await service.sync(registry)

    assert repository.publish_calls == 0
```

另测 dry-run 不写库、Embedding 失败不发布、新版本激活旧版本失活、Git 删除立即失活、Chunk 与 Embedding
顺序不一致直接失败。

- [x] **Step 2: 写 PostgreSQL Repository 集成测试**

`tests/integration/test_expert_template_repository.py` 必须验证：

1. 同步运行开始与完成状态。
2. 37 个模板和 Chunk 在一个事务发布。
3. active 部分唯一索引拒绝两个当前版本。
4. 版本升级保留旧正文和 Chunk。
5. `extends_id` 指向当前 core 记录；core 升级可重新解析 active overlay。
6. 发布事务故意抛错后，原 active 集合和最新成功 run 不变。
7. `get_index_status(current_source_hash)` 只有 Hash、模型、维度和默认模板全部一致时 `queryable=true`。

- [x] **Step 3: 运行测试并确认实现缺失**

```powershell
uv run --locked pytest tests/unit/test_expert_template_sync.py tests/unit/test_expert_template_cli.py tests/integration/test_expert_template_repository.py -q
```

预期：FAIL，缺少 Repository、SyncService 和 CLI。

- [x] **Step 4: 实现 Repository 和原子发布 DTO**

核心接口固定为：

```python
class ExpertTemplateRepository:
    async def start_run(self, source_hash: str) -> UUID: ...
    async def finish_run(self, run_id: UUID, completion: SyncRunCompletion) -> None: ...
    async def get_active_states(self) -> Mapping[str, TemplateVersionState]: ...
    async def publish_snapshot(self, snapshot: PreparedTemplateSnapshot) -> None: ...
    async def get_index_status(self, current_source_hash: str) -> ExpertTemplateIndexStatus: ...
    async def list_active_templates(self, query: TemplateListQuery) -> tuple[ExpertTemplateRecord, ...]: ...
```

`publish_snapshot()` 必须在单个 `session.begin()` 中锁定当前 active 模板，插入新增版本与 Chunk，解析父记录，
再统一激活、失活。同步服务在打开事务前完成所有 Markdown Chunk 与 Embedding 网络调用。

- [x] **Step 5: 实现同步服务**

同步服务必须按 `registry.templates` 的稳定顺序处理，并使用：

```python
MarkdownSource(
    title=template.name,
    source_ref=f"expert-template://{template.template_id}@{template.version}",
    content=template.content,
)
```

生成共享 Chunk。Embedding 批次结果必须验证 index、模型和 1536 维；任何失败只完成 failed run，不调用
`publish_snapshot()`。

- [x] **Step 6: 实现 CLI 与项目脚本**

在 `pyproject.toml` 增加：

```toml
databricks-zh-expert-templates = "databricks_zh_expert.expert_templates.cli:main"
```

CLI 采用阶段 4 相同的 Windows selector event loop 和 UTF-8 输出。`sync` 成功返回 0、同步失败返回 1、源
契约无效返回 2；不输出 API Key、正文或绝对路径。

- [x] **Step 7: 更新锁文件并运行聚焦测试**

```powershell
uv lock
uv lock --check
uv run --locked pytest tests/unit/test_expert_template_sync.py tests/unit/test_expert_template_cli.py tests/integration/test_expert_template_repository.py -q
```

预期：全部通过；`uv.lock` 只反映当前项目脚本元数据，不新增第三方包。

- [x] **Step 8: 运行静态与迁移检查**

```powershell
uv run --locked ruff format src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_sync.py tests/unit/test_expert_template_cli.py tests/integration/test_expert_template_repository.py
uv run --locked ruff check .
uv run --locked pyright
uv run --locked alembic check
```

预期：全部通过。

- [x] **Step 9: 提交任务 6**

```powershell
git add pyproject.toml uv.lock src/databricks_zh_expert/expert_templates tests/unit/test_expert_template_sync.py tests/unit/test_expert_template_cli.py tests/integration/test_expert_template_repository.py
git commit -m "feat: sync expert templates to postgres"
```

---

### 任务 7：实现专家模板检索、上下文和固定评估

**文件：**

- Create: `src/databricks_zh_expert/expert_templates/retrieval.py`
- Create: `src/databricks_zh_expert/expert_templates/context.py`
- Create: `src/databricks_zh_expert/expert_templates/evaluation.py`
- Modify: `src/databricks_zh_expert/expert_templates/repository.py`
- Modify: `src/databricks_zh_expert/expert_templates/cli.py`
- Modify: `src/databricks_zh_expert/rag/retrieval.py`
- Create: `tests/unit/test_expert_template_retrieval.py`
- Create: `tests/unit/test_expert_template_context.py`
- Create: `tests/unit/test_expert_template_eval.py`
- Create: `tests/integration/test_expert_template_retrieval.py`
- Create: `tests/evals/expert_templates.yml`

**接口：**

- Produces: `ExpertTemplateRetriever.retrieve(query, *, query_embedding, profile_id, prompt_name)`。
- Produces: `ExpertTemplateContextBuilder.build(...) -> ExpertTemplateRetrievalBundle`。
- Produces: `KnowledgeRetriever.retrieve_with_embedding(query, query_embedding)`，保留原 `retrieve(query)`。
- Produces: `ExpertTemplateEvaluator.evaluate_file(path) -> ExpertTemplateEvaluationResult`。
- Consumes: 任务 5 RRF、任务 6 Repository、阶段 4 EmbeddingResult。

- [x] **Step 1: 写 Profile、Prompt 和 cloud 预过滤测试**

```python
async def test_generic_profile_never_returns_retail_overlay() -> None:
    bundle = await retriever.retrieve(
        "设计零售销售工作流",
        query_embedding=VALID_QUERY_VECTOR,
        profile_id="generic",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert all(selection.layer == "core" for selection in bundle.selected_templates)


async def test_retail_overlay_loads_active_core_parent() -> None:
    bundle = await retriever.retrieve(
        "设计 AWS 零售销售工作流",
        query_embedding=VALID_QUERY_VECTOR,
        profile_id="retail_sales_demo",
        prompt_name=PromptName.WORKFLOW_DESIGN,
    )

    assert [item.template_id for item in bundle.selected_templates][:2] == [
        "workflow.lakeflow_jobs",
        "retail.workflow_dag",
    ]
    assert bundle.selected_templates[0].reason == "inherited"
```

另测不同 Prompt 排除无关资产、AWS Profile 同时允许 neutral 与 aws、generic 禁止 aws overlay、语义低于阈值
时使用 `profiles.yml` 默认模板。

- [x] **Step 2: 写完整模板上下文预算测试**

`ExpertTemplateContextBuilder` 测试必须证明：

1. 候选先按最佳 Chunk 聚合到模板。
2. 实际上下文包含完整模板 Markdown，不返回孤立 Chunk。
3. 最多三个主要模板，父模板去重。
4. 总 token 不超过 2,500。
5. 文本明确写出用户、官方、overlay、core 的优先级。
6. Context 不包含本地绝对路径和 `official_refs` 伪引用。

- [x] **Step 3: 写 30 条固定评估数据**

`tests/evals/expert_templates.yml` 固定以下覆盖组和 expected ID：

| Query IDs | Profile | 主要 expected template |
| --- | --- | --- |
| `g_s3`, `g_dms`, `g_kinesis` | generic | 三个 ingestion blueprint，并让至少一条同时期望 `decision.ingestion_mode` |
| `g_medallion`, `g_dataset_type`, `g_scd`, `g_backfill` | generic | medallion 与三个其余 decision guide |
| `g_uc`, `g_pii`, `g_quality`, `g_monitoring` | generic | governance 与 checklist |
| `g_autoloader_code`, `g_dms_code`, `g_kinesis_code`, `g_merge_sql`, `g_gold_sql` | generic | 六个 code pattern 中对应资产 |
| `g_performance`, `g_cost`, `g_arch_doc`, `g_table_doc`, `g_job_doc`, `g_proposal` | generic | checklist 与 deliverable |
| `r_context`, `r_sources`, `r_architecture`, `r_medallion`, `r_workflow`, `r_access`, `r_gold`, `r_acceptance` | retail_sales_demo | 八个 retail 资产 |

总数固定为 30。每条 generic 数据增加 `forbidden_layers: [retail_sales_demo]`；零售继承用例同时列出父模板
expected ID。

- [x] **Step 4: 运行新测试并确认实现缺失**

```powershell
uv run --locked pytest tests/unit/test_expert_template_retrieval.py tests/unit/test_expert_template_context.py tests/unit/test_expert_template_eval.py tests/integration/test_expert_template_retrieval.py -q
```

预期：FAIL，检索和上下文模块不存在。

- [x] **Step 5: 实现 Repository 候选查询**

向量与全文查询必须在 SQL 层应用 active、模型、Profile layer、cloud 和 Prompt JSONB 过滤，然后分别返回
20 个候选。精确余弦与全文排序使用稳定 tie-break：template ID、version、chunk_index、UUID。

候选 DTO 至少包含：

```python
@dataclass(frozen=True, slots=True)
class ExpertTemplateCandidate:
    chunk_id: UUID
    template_record_id: UUID
    template_id: str
    version: str
    name: str
    layer: str
    profile_id: str | None
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    content: str
    content_hash: str
    extends_record_id: UUID | None
    vector_similarity: float | None
    lexical_score: float | None
```

- [x] **Step 6: 实现检索、完整模板上下文和默认回退**

`ExpertTemplateRetriever` 不拥有 EmbeddingClient，只接受已经验证的 1536 维向量。使用共享
`extract_lexical_query()` 与 `reciprocal_rank_fusion_ids()`，按模板最佳 Chunk 聚合，再交给 ContextBuilder。

如果没有满足阈值的语义与全文候选，从 Registry 的当前 Profile Prompt 默认 ID 构建上下文，并记录
`reason="default"`；默认模板不存在则抛 `ExpertTemplateContextNotFoundError`。

- [x] **Step 7: 为官方 Retriever 增加向量复用入口**

```python
class KnowledgeRetriever:
    async def retrieve(self, query: str) -> RetrievalBundle:
        embedding = await self._embedding_client.embed_query(query)
        return await self.retrieve_with_embedding(query, embedding.embedding)

    async def retrieve_with_embedding(
        self,
        query: str,
        query_embedding: Sequence[float],
    ) -> RetrievalBundle:
        ...
```

原 `retrieve()` 行为和阶段 4 测试结果必须保持不变。

- [x] **Step 8: 实现评估器和 CLI `evaluate`**

评估结果固定包含 query_count、hit_count、recall_at_3、profile_leak_count、inheritance_miss_count、passed。
`passed` 只在 Recall@3 >= 0.90、Profile 泄漏为 0、继承缺失为 0 时为 true。CLI 失败返回 1，数据集无效
返回 2。

- [x] **Step 9: 运行聚焦测试和阶段 4回归**

```powershell
uv run --locked pytest tests/unit/test_expert_template_retrieval.py tests/unit/test_expert_template_context.py tests/unit/test_expert_template_eval.py tests/integration/test_expert_template_retrieval.py tests/unit/test_knowledge_retrieval.py tests/unit/test_knowledge_eval.py -q
```

预期：全部通过。

- [x] **Step 10: 运行静态检查并提交任务 7**

```powershell
uv run --locked ruff format src/databricks_zh_expert/expert_templates src/databricks_zh_expert/rag/retrieval.py tests/unit/test_expert_template_retrieval.py tests/unit/test_expert_template_context.py tests/unit/test_expert_template_eval.py tests/integration/test_expert_template_retrieval.py
uv run --locked ruff check .
uv run --locked pyright
git add src/databricks_zh_expert/expert_templates src/databricks_zh_expert/rag/retrieval.py tests/unit/test_expert_template_retrieval.py tests/unit/test_expert_template_context.py tests/unit/test_expert_template_eval.py tests/integration/test_expert_template_retrieval.py tests/evals/expert_templates.yml
git commit -m "feat: retrieve and evaluate expert templates"
```

---

### 任务 8：实现会话 Profile、只读 API 和 readiness

**文件：**

- Create: `src/databricks_zh_expert/api/expert_template_schemas.py`
- Create: `src/databricks_zh_expert/api/expert_templates.py`
- Modify: `src/databricks_zh_expert/api/chat.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/api/health.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/chat/schemas.py`
- Modify: `src/databricks_zh_expert/core/errors.py`
- Modify: `src/databricks_zh_expert/main.py`
- Create: `tests/integration/test_expert_templates_api.py`
- Modify: `tests/integration/test_sessions_api.py`
- Modify: `tests/integration/test_health_ready.py`
- Modify: `tests/unit/test_health.py`
- Modify: `tests/unit/test_errors.py`
- Modify: `tests/conftest.py`

**接口：**

- Produces: `POST /api/chat/sessions` 的可选 `expert_profile`。
- Produces: Session 创建、列表、详情响应中的 `expert_profile`。
- Produces: `GET /api/expert-profiles`、`GET /api/expert-templates`、`GET /api/expert-templates/index/status`。
- Produces: readiness 的 `expert_templates` 状态。
- Consumes: 任务 1 Registry 与任务 6 Repository。

- [x] **Step 1: 写会话 Profile API 失败测试**

```python
async def test_create_session_defaults_to_generic_profile(client: AsyncClient) -> None:
    response = await client.post("/api/chat/sessions", json={"title": "通用会话"})

    assert response.status_code == 201
    assert response.json()["expert_profile"] == "generic"


async def test_create_session_rejects_unknown_profile(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat/sessions",
        json={"title": "错误会话", "expert_profile": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "expert_profile_not_found"
```

另测 Profile 出现在列表与详情，API 中不存在修改 Profile 的路由，历史会话默认 generic。

- [x] **Step 2: 写只读目录和 readiness 测试**

验证：

1. `/api/expert-profiles` 只返回 generic 与 retail，默认值正确。
2. `/api/expert-templates` 支持 profile、kind、category、分页，只返回 active 元数据。
3. 响应不包含 `content`、`embedding`、`source_path`、候选分数。
4. `/api/expert-templates/index/status` 返回 source Hash 匹配和 queryable。
5. 专家索引未同步时 `/health/ready` 返回 503，模型调用接口尚未触发。

`tests/conftest.py` 增加可复用的测试 Registry 和已就绪专家索引 fixture；不得让普通 API 测试访问 OpenAI。

- [x] **Step 3: 运行 API 测试并确认字段和路由缺失**

```powershell
uv run --locked pytest tests/integration/test_sessions_api.py tests/integration/test_expert_templates_api.py tests/integration/test_health_ready.py tests/unit/test_health.py tests/unit/test_errors.py -q
```

预期：FAIL，缺少 Profile 字段、API 和 readiness 状态。

- [x] **Step 4: 在应用启动时加载并校验 Registry**

`create_app()` 增加可注入的 `expert_template_registry`，默认调用 `create_default()`，随后执行完整校验并保存到
`app.state.expert_template_registry`。启动预检不得访问数据库或 OpenAI。

- [x] **Step 5: 实现不可变会话 Profile**

`SessionCreate.expert_profile` 是最长 100 的字符串，默认 `generic`。API 在调用
`ChatRepository.create_session(title, expert_profile)` 前通过 Registry 验证。Repository 不允许更新
`expert_profile`，SessionResponse 与 SessionDetail 只读返回该值。

- [x] **Step 6: 实现只读专家 API**

API 响应模型固定为：

```python
class ExpertProfileResponse(BaseModel):
    id: str
    display_name: str
    description: str
    cloud: str


class ExpertTemplateMetadataResponse(BaseModel):
    template_id: str
    version: str
    name: str
    summary: str
    kind: ExpertTemplateKind
    category: ExpertTemplateCategory
    layer: str
    profile_id: str | None
    cloud: str
    prompt_names: list[PromptName]
    tags: list[str]
```

列表 API 不提供正文详情端点、同步端点、写入端点或模板选择端点。

- [x] **Step 7: 扩展 readiness**

`ReadinessResponse` 增加 `expert_templates: Literal["ok"]`。数据库正常但 Registry 当前 Hash 与数据库最近成功
同步不一致时抛 `expert_template_index_not_ready` 503。`/health` 与 `/health/live` 不查询数据库或模板索引。

- [x] **Step 8: 运行 API、回归和静态检查**

```powershell
uv run --locked pytest tests/integration/test_sessions_api.py tests/integration/test_expert_templates_api.py tests/integration/test_health_ready.py tests/unit/test_health.py tests/unit/test_errors.py -q
uv run --locked ruff format src/databricks_zh_expert/api src/databricks_zh_expert/chat src/databricks_zh_expert/main.py tests/integration/test_expert_templates_api.py
uv run --locked ruff check .
uv run --locked pyright
```

预期：全部通过。

- [x] **Step 9: 提交任务 8**

```powershell
git add src/databricks_zh_expert/api src/databricks_zh_expert/chat/repository.py src/databricks_zh_expert/chat/schemas.py src/databricks_zh_expert/core/errors.py src/databricks_zh_expert/main.py tests/conftest.py tests/integration/test_expert_templates_api.py tests/integration/test_sessions_api.py tests/integration/test_health_ready.py tests/unit/test_health.py tests/unit/test_errors.py
git commit -m "feat: expose expert profiles and index status"
```

---

### 任务 9：集成 ChatService、双通道上下文、审计和 Trace 1.5

**文件：**

- Create: `src/databricks_zh_expert/chat/context.py`
- Modify: `src/databricks_zh_expert/chat/service.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/core/errors.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/prompts/registry.py`
- Modify: `src/databricks_zh_expert/observability/model_trace.py`
- Modify: `tests/unit/test_prompt_registry.py`
- Modify: `tests/unit/test_chat_service.py`
- Modify: `tests/unit/test_model_trace.py`
- Modify: `tests/integration/test_messages_api.py`
- Modify: `tests/integration/test_knowledge_messages_api.py`
- Create: `tests/integration/test_expert_template_messages_api.py`
- Modify: `tests/conftest.py`

**接口：**

- Produces: `ChatContextService.build(query, prompt_spec, expert_profile) -> ChatContextBundle`。
- Produces: `PromptSpec.use_official_knowledge` 与 `use_expert_templates`。
- Produces: `ExpertTemplateTrace`、候选 Trace、选择 Trace 和 Trace schema 1.5。
- Produces: 每次新 `model_calls` 的 Profile 与专家选择 JSONB。
- Preserves: 消息 API 请求与成功响应不增加模板字段，官方 citations 结构不变。

- [x] **Step 1: 写 Prompt 策略矩阵测试**

```python
EXPECTED_CONTEXT_POLICY = {
    PromptName.DATABRICKS_QA: (False, True),
    PromptName.KNOWLEDGE_QA: (True, False),
    PromptName.SQL_GENERATION: (True, True),
    PromptName.PYSPARK_GENERATION: (True, True),
    PromptName.WORKFLOW_DESIGN: (True, True),
    PromptName.PROPOSAL_GENERATION: (True, True),
    PromptName.SELF_CHECK: (False, True),
    PromptName.DOCUMENT_SUMMARY: (False, False),
}


def test_prompt_context_policy_is_explicit() -> None:
    assert {
        spec.name: (spec.use_official_knowledge, spec.use_expert_templates)
        for spec in PROMPT_SPECS
    } == EXPECTED_CONTEXT_POLICY
```

`PromptSpec` 新字段没有改变 Jinja2 正文，因此现有版本保持不变。

- [x] **Step 2: 写单次 Embedding 与上下文顺序测试**

Fake EmbeddingClient 记录调用次数，Fake 官方与专家 Retriever 记录传入向量：

```python
async def test_generation_prompt_reuses_one_embedding_for_two_retrievers() -> None:
    bundle = await context_service.build(
        "设计零售工作流",
        prompt_spec=WORKFLOW_SPEC,
        expert_profile="retail_sales_demo",
    )

    assert embedding_client.query_count == 1
    assert knowledge_retriever.query_embedding == expert_retriever.query_embedding
    assert bundle.expert_context is not None
    assert bundle.official_context is not None
```

ChatService 请求顺序断言为 system、历史、专家上下文、官方上下文、当前 user。knowledge_qa 只出现官方上下文，
document_summary 两类都不出现。

- [x] **Step 3: 写错误与持久化边界测试**

验证：

1. 专家索引未就绪返回 `expert_template_index_not_ready`，user message 保留，不调用模型。
2. 专家默认与检索都无结果返回 `expert_template_context_not_found`。
3. Embedding 缺失或失败继续使用现有稳定错误，不进行 fallback 聊天调用。
4. fallback 的每个模型尝试写相同 Profile 和模板选择 JSONB。
5. 纯 knowledge_qa 新 model_call 写当前 Profile 与空模板数组。
6. assistant `source_citations` 只来自官方 RetrievalBundle。
7. 消息 API 成功响应不出现 `expert_templates` 字段。

- [x] **Step 4: 写 Trace 1.5 序列化测试**

Trace 测试必须断言：

```python
payload = json.loads(JsonlModelTraceSink._serialize(trace))

assert payload["schema_version"] == "1.5"
assert payload["trace"]["expert_profile"] == "retail_sales_demo"
assert payload["expert_templates"]["selected"][0]["template_id"] == "retail.workflow_dag"
assert payload["expert_templates"]["selected"][0]["extends"] == "workflow.lakeflow_jobs@1.0.0"
assert payload["request"]["messages"][-3]["content"].startswith("以下内容是内部专家模板")
```

候选必须包含 rank、vector/lexical rank 与 score、fused score、selected；选择必须包含 ID、版本、Hash、layer、
profile、reason 和 extends。模板本地绝对路径不得出现。

- [x] **Step 5: 运行新测试并确认集成缺失**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py -q
```

预期：FAIL，缺少策略字段、ContextService 和 Trace 1.5。

- [x] **Step 6: 实现 `ChatContextService`**

```python
@dataclass(frozen=True, slots=True)
class ChatContextBundle:
    expert: ExpertTemplateRetrievalBundle | None
    official: RetrievalBundle | None


class ChatContextService:
    async def build(
        self,
        query: str,
        *,
        prompt_spec: PromptSpec,
        expert_profile: str,
    ) -> ChatContextBundle: ...
```

服务先检查所需索引状态，再只调用一次 `embed_query()`。如果 Prompt 两类都不需要，完全不调用 Embedding。
它只返回领域 Bundle，不保存消息、model_call 或 Trace。

- [x] **Step 7: 改造 ChatService 编排**

ChatService 从已读取 Session 获取不可变 Profile，保存 user message 后调用 ContextService。专家和官方上下文使用
两个独立 `ModelMessage(role="user")` 放在当前 user 前，专家在前、官方在后。模型 fallback 复用同一
`model_messages`，不得重新检索或重新生成 Embedding。

`tests/conftest.py` 为既有消息 API 提供 Fake ChatContextService 或已就绪的本地候选，确保自动测试不访问
OpenAI；新增双检索集成测试显式覆盖真实 Repository 过滤和 Fake Embedding 复用。

Artifact 成功后仅把官方 Bundle 转为 `source_citations`。模板选择不写 assistant message，也不进入 API
成功响应。

- [x] **Step 8: 扩展 model_calls 与 Trace**

`ChatRepository.create_model_call()` 增加：

```python
expert_profile: str
expert_template_selections: list[dict[str, object]]
```

每个阶段 5 新调用都写值。`build_trace()` 接受 `ExpertTemplateTrace | None`，JsonlModelTraceSink 输出 schema
1.5；现有 `retrieval` 仍表示官方知识，字段含义不变。

- [x] **Step 9: 运行聚焦、API 和阶段 4 回归测试**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py -q
```

预期：全部通过。

- [x] **Step 10: 运行静态检查并提交任务 9**

```powershell
uv run --locked ruff format src/databricks_zh_expert/chat src/databricks_zh_expert/prompts/registry.py src/databricks_zh_expert/observability/model_trace.py src/databricks_zh_expert/api/dependencies.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_expert_template_messages_api.py
uv run --locked ruff check .
uv run --locked pyright
git add src/databricks_zh_expert/chat src/databricks_zh_expert/core/errors.py src/databricks_zh_expert/api/dependencies.py src/databricks_zh_expert/prompts/registry.py src/databricks_zh_expert/observability/model_trace.py tests/conftest.py tests/unit/test_prompt_registry.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py
git commit -m "feat: apply expert templates to chat"
```

---

### 任务 10：执行完整评估、真实冒烟和阶段收尾

**文件：**

- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md`
- Modify: `docs/superpowers/plans/2026-07-16-stage-5-databricks-expert-template-library-plan.md`
- Modify only if tests expose a defect: files owned by tasks 1 至 9
- Preserve: configured JSONL Trace path and all acceptance database rows

**接口：**

- Consumes: 任务 1 至 9 的完整阶段 5 功能。
- Produces: 真实专家索引、固定 Recall@3 结果、两次 DeepSeek Artifact、Trace 1.5 验收证据。
- Produces: README 中一条必要同步步骤和总计划阶段 5 完成状态。

- [x] **Step 1: 从当前 head 执行完整自动验证**

```powershell
git diff --check
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
```

预期：无 whitespace 错误；Ruff、Pyright、pytest 和 Alembic 全部通过；覆盖率不低于 80%。失败必须先
定位根因并补回归测试，不能降低覆盖率门禁或删除既有测试。

- [x] **Step 2: 升级真实开发数据库并同步模板**

```powershell
uv run --locked alembic upgrade head
uv run --locked databricks-zh-expert-templates sync --dry-run
uv run --locked databricks-zh-expert-templates sync
uv run --locked databricks-zh-expert-templates status
```

预期：dry-run 不写库；真实同步成功；active 模板 37、Chunk 大于等于 37、Profile 默认模板完整、当前源 Hash
一致、queryable 为 true。不要删除阶段 4 知识表或重建已有官方索引。

- [x] **Step 3: 运行固定专家检索评估**

```powershell
uv run --locked databricks-zh-expert-templates evaluate
```

预期：query_count=30、Recall@3 >= 0.90、profile_leak_count=0、inheritance_miss_count=0、passed=true。
若未通过，保留失败数据，修改检索或模板内容并补测试；不得放宽 expected ID 来掩盖错误。

- [x] **Step 4: 启动服务并创建两个真实零售会话**

在单独终端执行精确启动命令：

```powershell
uv run --locked databricks-zh-expert
```

服务就绪后，在当前终端执行：

```powershell
$workflowSession = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/chat/sessions' -ContentType 'application/json' -Body '{"title":"阶段5零售工作流验收","expert_profile":"retail_sales_demo"}'
$workflowBody = '{"content":"为 AWS 零售销售平台设计包含 S3 日批、RDS DMS CDC 和 Kinesis 事件流的完整工作流，并满足已定义 SLA。","model":"deepseek-v4-flash","prompt":"workflow_design"}'
$workflowResult = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/chat/sessions/{0}/messages" -f $workflowSession.id) -ContentType 'application/json' -Body $workflowBody

$proposalSession = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/chat/sessions' -ContentType 'application/json' -Body '{"title":"阶段5零售提案验收","expert_profile":"retail_sales_demo"}'
$proposalBody = '{"content":"为该零售销售分析平台生成一份面向项目评审的 Databricks 技术提案。","model":"deepseek-v4-flash","prompt":"proposal_generation"}'
$proposalResult = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/chat/sessions/{0}/messages" -f $proposalSession.id) -ContentType 'application/json' -Body $proposalBody
```

预期：两个请求均返回 201，Artifact 分别为 workflow_design 与 proposal；不要在验收脚本中删除这两个
session。

- [x] **Step 5: 人工核对数据库与 Trace 1.5**

按两个精确 session ID 核对：

1. sessions.expert_profile 均为 retail_sales_demo。
2. 每个 model_call 都有 expert_profile 和非空专家选择数组。
3. workflow 与 proposal 使用了对应 retail 模板及 active core 父模板。
4. 官方 citations 只包含 docs.databricks.com 或阶段 4 catalog link，不包含 expert-template URI。
5. Trace schema_version 为 1.5，专家候选、选择、分数、reason、extends 和完整 request.messages 存在。
6. Trace 不包含 OpenAI Key、DeepSeek Key、本地绝对模板路径或真实 PII。
7. 模型输出没有声称已经运行 Databricks、AWS DMS、Kinesis 或 Pipeline。

**禁止执行任何 DELETE、TRUNCATE、按标题通配清理或 Trace 文件清理。**

- [x] **Step 6: 只更新必要启动步骤和总计划**

README 只增加：

```powershell
uv run databricks-zh-expert-templates sync
```

作为迁移后的专家索引初始化步骤，不加入架构解释和预期输出。总计划将阶段 5 标记为实现与验收完成，并把
近期下一步改为阶段 6 代码生成模块。

- [x] **Step 7: 再次执行最终验证**

```powershell
git diff --check
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic current
uv run --locked alembic check
```

预期：全部通过；Alembic current 为 0007；覆盖率不低于 80%；真实模板、会话和 Trace 仍存在。

- [x] **Step 8: 检查提交范围并提交阶段 5 收尾**

```powershell
git status --short
git diff --stat
git diff --check
git add README.md docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md docs/superpowers/plans/2026-07-16-stage-5-databricks-expert-template-library-plan.md
git commit -m "docs: complete stage 5 acceptance"
```

若任务 10 修复了代码或测试，必须把对应文件一并精确加入该提交；不得使用清理命令删除验收数据。

---

## 阶段 5 完成定义

- [x] 37 个左右的模板均通过严格 Registry 校验，没有重复 ID、无效版本、循环继承或 Preview 内容。
- [x] generic 和 retail_sales_demo Profile 可创建会话，Profile 创建后不可修改。
- [x] 三张专家表与会话、model_calls 新字段完成迁移和回归验证。
- [x] 同步是增量、原子和可重建的；同版本不同 Hash 被拒绝，旧版本保留。
- [x] 官方知识与专家模板的数据、上下文、引用和审计完全分离。
- [x] 八种 Prompt 严格遵循规格中的官方/专家检索矩阵。
- [x] 需要双检索时只生成一次查询 Embedding。
- [x] model_calls 和 Trace 1.5 可以恢复实际 Profile、模板版本、Hash、排名、理由和继承。
- [x] 固定 30 条评估 Recall@3 >= 90%，Profile 泄漏与继承缺失均为 0。
- [x] 两次 deepseek-v4-flash 真实冒烟成功，所有验收数据和 Trace 保留。
- [x] Ruff、Pyright/Pylance、pytest、覆盖率和 Alembic 全部通过。

## 实施交接

执行时使用 `superpowers:executing-plans` 按任务顺序完成，每个任务先测试、再实现、再验证。用户此前反馈子智能体
容易卡住，因此阶段 5 默认在当前会话内执行，不使用并行子智能体；每个任务完成后先报告验证结果，再按用户
指示提交。
