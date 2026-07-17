# 阶段 6：项目感知代码生成模块实施计划

> **执行要求：** 使用 `superpowers:executing-plans` 在当前会话逐任务执行；按用户偏好不使用子智能体。
> 每个任务先写失败测试，再做最小实现，验证通过后按用户指示提交。不得清理任何验收数据。

**目标：** 在现有 SQL / PySpark 代码 Artifact 基础上增加一个真实目录结构的 AWS 零售销售 Mock 工作区，
使 SQL、PySpark 和 Python source Notebook 草稿能够使用可追溯的项目表、字段、映射和业务规则。

**架构：** Git 中的示例工作区是阶段 6 唯一项目事实来源；严格 `WorkspaceRegistry` 加载清单和受控文件，
确定性 `WorkspaceContextBuilder` 在 token 预算内选择相关文件。会话只保存不可变 `workspace_id`，模型调用只保存
版本、Hash 和选择元数据；ChatService 通过 `WorkspaceContextBundle` 组装项目上下文，未来可无缝替换为本地
SQLite Provider。

**技术栈：** Python 3.12.10、FastAPI、Pydantic 2、PyYAML、Jinja2、markdown-it-py、tiktoken、
SQLAlchemy 2、Alembic、PostgreSQL、LiteLLM、OpenAI Embedding、pytest、Ruff、Pyright、uv。

## 全局约束

1. 阶段 6 只支持内置 `retail_sales_demo` 工作区，不接受任意本地路径或上传文件。
2. 项目文件是唯一真源；PostgreSQL 不保存项目文件正文、DDL 正文、项目 Chunk 或项目 Embedding。
3. 不增加 SQLite、FTS5、向量扩展、SQLGlot、Spark、Databricks CLI、Databricks SDK 或 Docker 服务。
4. `expert_profile` 与 `workspace_id` 是两个独立字段，不根据其中一个隐式推导另一个。
5. Workspace Context 只用于 `sql_generation`、`pyspark_generation`、`notebook_generation`。
6. Workspace 文件选择不调用 OpenAI、DeepSeek、Embedding、rerank 或 LangGraph。
7. SQL 与 PySpark 保持直接代码围栏和简短注释，不恢复固定长篇章节，不新增严格运行时语法阻断。
8. Notebook 只返回 Python source 格式草稿，不创建 `.py`、`.ipynb`、DBC 或 Databricks Workspace 对象。
9. 不执行生成代码、Bundle、Job、Pipeline 或任何 Databricks / AWS 操作。
10. Source 路径只使用工作区相对 POSIX 路径，API、数据库和 Trace 不得泄露绝对路径。
11. 阶段 6 不新增环境变量；目录、大小、top-k 和 token 预算均为跨环境代码常量。
12. 所有文档、Mock 说明、API 描述和错误消息使用中文；代码标识符和项目字段使用英文。
13. 修改 Python 后必须运行 Ruff 与 Pyright/Pylance；数据库改动必须运行 Alembic 检查。
14. 不降低当前 80% 覆盖率门禁、阶段 4 Recall@5 或阶段 5 Recall@3 门禁。
15. 不清理现有或新增的会话、消息、模型调用、知识数据、模板数据和真实 Trace。
16. README 没有新增启动步骤时保持不变，不增加阶段 6 架构说明。

---

## 已确认设计

详细产品边界、领域契约、数据模型、Prompt 策略和完成定义见：

`docs/superpowers/specs/2026-07-17-stage-6-project-aware-code-generation-design.md`

实施期间若发现与规格冲突的新事实，先停止相关任务并记录影响，不静默增加 SQLite、用户目录扫描、代码执行、
严格代码解析或 Databricks 连接。

## 基线

开始任务 1 前执行：

```powershell
git status --short
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic current
uv run --locked alembic check
```

预期：Git 工作区只包含用户明确保留的改动；锁文件、Ruff、Pyright、pytest 和 Alembic 全部通过；覆盖率不低于
80%；当前迁移为 `0007_expert_templates`。若基线已经变化，记录当前真实值，不回退用户已有修改。

## 目标文件结构

```text
examples/workspaces/retail_sales_demo/
  .databricks-expert/project.yml
  databricks.yml
  resources/retail-sales.job.yml
  docs/project-overview.md
  contracts/tables.yml
  contracts/mappings.yml
  contracts/business-rules.yml
  sql/ddl/bronze.sql
  sql/ddl/silver.sql
  sql/ddl/gold.sql
  src/common/parameters.py
  src/bronze/ingest_pos_sales.py

src/databricks_zh_expert/
  workspace/
    __init__.py
    constants.py
    types.py
    registry.py
    context.py
  api/
    workspace_schemas.py
    workspaces.py

src/databricks_zh_expert/prompts/templates/
  notebook_generation.jinja2

knowledge/expert_templates/core/code_patterns/
  databricks-notebook-python.md

tests/
  evals/workspace_context.yml
  fixtures/workspaces/valid/
  unit/test_workspace_registry.py
  unit/test_retail_workspace_content.py
  unit/test_workspace_context.py
  unit/test_workspace_context_eval.py
  integration/test_workspaces_api.py
  integration/test_workspace_code_generation_messages_api.py

alembic/versions/0008_workspace_code_generation.py
```

## 任务顺序

1. 固定 Workspace 契约、常量和 Registry。
2. 编写 AWS 零售销售示例工作区。
3. 实现确定性 Workspace Context 选择与渲染。
4. 完成 SQL、PySpark 和 Notebook Prompt 契约。
5. 创建迁移、会话绑定和只读 Workspace API。
6. 集成 ChatService、模型调用审计和 Trace 1.6。
7. 增加固定上下文评估和三类代码 API 回归。
8. 执行数据库升级、模板同步、真实冒烟和阶段收尾。

---

### 任务 1：固定 Workspace 契约、常量和 Registry

**文件：**

- Create: `src/databricks_zh_expert/workspace/__init__.py`
- Create: `src/databricks_zh_expert/workspace/constants.py`
- Create: `src/databricks_zh_expert/workspace/types.py`
- Create: `src/databricks_zh_expert/workspace/registry.py`
- Create: `tests/unit/test_workspace_registry.py`
- Create: `tests/fixtures/workspaces/valid/retail_sales_demo/.databricks-expert/project.yml`
- Create: `tests/fixtures/workspaces/valid/retail_sales_demo/docs/project-overview.md`
- Create: `tests/fixtures/workspaces/valid/retail_sales_demo/contracts/tables.yml`

**接口：**

- Produces: `WorkspaceSourceKind`、`WorkspaceSource`、`WorkspaceDefinition`。
- Produces: `WorkspaceRegistry.load(root: Path) -> WorkspaceRegistry`。
- Produces: `WorkspaceRegistry.create_default() -> WorkspaceRegistry`。
- Produces: `get(workspace_id: str) -> WorkspaceDefinition`、`workspaces` 只读属性。
- Produces: `WorkspaceRegistryError`，错误消息为中文且不包含绝对路径。
- Consumes: 现有 `PromptName`、PyYAML、Pydantic，不访问数据库或网络。

- [ ] **Step 1: 写 Registry 正常加载测试**

```python
def test_registry_loads_workspace_and_explicit_sources() -> None:
    registry = WorkspaceRegistry.load(FIXTURE_ROOT / "valid")

    workspace = registry.get("retail_sales_demo")
    assert workspace.version == "1.0.0"
    assert workspace.cloud == "aws"
    assert workspace.is_mock is True
    assert [source.source_id for source in workspace.sources] == [
        "contract.tables",
        "project.overview",
    ]
    assert len(workspace.source_hash) == 64
    assert all("\\" not in source.source_path for source in workspace.sources)
```

- [ ] **Step 2: 写严格字段和路径安全测试**

使用测试内辅助函数复制 valid fixture，并逐项变更：

```python
@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("unknown_manifest_field", "包含未知字段"),
        ("invalid_workspace_id", "工作区 ID"),
        ("invalid_semver", "版本必须使用 MAJOR.MINOR.PATCH"),
        ("unknown_prompt", "Prompt 未注册"),
        ("unknown_default_source", "默认上下文引用不存在"),
        ("absolute_source_path", "必须使用工作区相对路径"),
        ("parent_traversal", "不能包含 .."),
        ("forbidden_extension", "文件类型不允许"),
        ("non_utf8_source", "必须使用 UTF-8"),
        ("oversized_source", "超过最大大小"),
    ],
)
def test_registry_rejects_invalid_workspace(
    tmp_path: Path,
    mutation: str,
    expected_message: str,
) -> None:
    root = build_workspace_fixture(tmp_path, mutation=mutation)

    with pytest.raises(WorkspaceRegistryError, match=expected_message):
        WorkspaceRegistry.load(root)
```

在 Windows 支持创建符号链接时增加逃逸测试；系统不允许创建符号链接时使用 monkeypatch 固定
`Path.resolve()` 结果，不让测试依赖管理员权限。

- [ ] **Step 3: 运行测试并确认模块缺失**

```powershell
uv run --locked pytest tests/unit/test_workspace_registry.py -q
```

预期：FAIL，错误包含 `ModuleNotFoundError: databricks_zh_expert.workspace`。

- [ ] **Step 4: 实现固定常量和冻结领域类型**

`constants.py` 固定：

```python
WORKSPACE_ROOT = Path("examples/workspaces")
WORKSPACE_SOURCE_MAX_BYTES = 256_000
WORKSPACE_CONTEXT_TOP_K = 6
WORKSPACE_CONTEXT_MAX_TOKENS = 4_000
WORKSPACE_ALLOWED_SUFFIXES = frozenset({".md", ".yml", ".yaml", ".sql", ".py"})
```

`types.py` 实现规格中的类型，并额外固定：

```python
@dataclass(frozen=True, slots=True)
class WorkspaceDefinition:
    workspace_id: str
    display_name: str
    description: str
    version: str
    cloud: str
    is_mock: bool
    source_hash: str
    default_context: Mapping[PromptName, tuple[str, ...]]
    sources: tuple[WorkspaceSource, ...]
```

不得把工作区根绝对路径放入 DTO。

- [ ] **Step 5: 实现严格 Registry**

`WorkspaceRegistry.load()` 必须：

1. 只查找根目录立即子目录中的 `.databricks-expert/project.yml`。
2. 使用 `yaml.safe_load()` 和 Pydantic `extra="forbid"`。
3. 校验 `schema_version=1`、ID、SemVer、cloud、Mock 和当前已注册的代码 Prompt；任务 4 注册
   Notebook Prompt 时，清单契约自动扩展为三个代码 Prompt。
4. 校验 Source ID、默认映射、允许扩展名、大小、UTF-8 和根目录约束。
5. 规范化换行与相对 POSIX 路径，对清单和正文计算稳定 SHA-256。
6. 按 `workspace_id` 和 `source_id` 排序，文件遍历顺序不能影响结果。
7. 抛出安全中文错误，不返回绝对路径和文件正文。

- [ ] **Step 6: 运行测试和静态检查**

```powershell
uv run --locked pytest tests/unit/test_workspace_registry.py -q
uv run --locked ruff format src/databricks_zh_expert/workspace tests/unit/test_workspace_registry.py
uv run --locked ruff check src/databricks_zh_expert/workspace tests/unit/test_workspace_registry.py
uv run --locked pyright
```

预期：测试和 Ruff 通过，Pyright 0 errors。

- [ ] **Step 7: 提交任务 1**

```powershell
git add src/databricks_zh_expert/workspace tests/unit/test_workspace_registry.py tests/fixtures/workspaces
git commit -m "feat: add project workspace registry"
```

---

### 任务 2：编写 AWS 零售销售示例工作区

**文件：**

- Create: `examples/workspaces/retail_sales_demo/.databricks-expert/project.yml`
- Create: `examples/workspaces/retail_sales_demo/databricks.yml`
- Create: `examples/workspaces/retail_sales_demo/resources/retail-sales.job.yml`
- Create: `examples/workspaces/retail_sales_demo/docs/project-overview.md`
- Create: `examples/workspaces/retail_sales_demo/contracts/tables.yml`
- Create: `examples/workspaces/retail_sales_demo/contracts/mappings.yml`
- Create: `examples/workspaces/retail_sales_demo/contracts/business-rules.yml`
- Create: `examples/workspaces/retail_sales_demo/sql/ddl/bronze.sql`
- Create: `examples/workspaces/retail_sales_demo/sql/ddl/silver.sql`
- Create: `examples/workspaces/retail_sales_demo/sql/ddl/gold.sql`
- Create: `examples/workspaces/retail_sales_demo/src/common/parameters.py`
- Create: `examples/workspaces/retail_sales_demo/src/bronze/ingest_pos_sales.py`
- Create: `tests/unit/test_retail_workspace_content.py`

**接口：**

- Consumes: 任务 1 `WorkspaceRegistry` 和清单契约。
- Produces: 一个 `id=retail_sales_demo`、`version=1.0.0`、`cloud=aws`、`is_mock=true` 工作区。
- Produces: 16 张表、字段、业务键、映射、业务规则和对应 Bronze / Silver / Gold DDL。
- Produces: 最小 Bundle 与既有 PySpark 风格样例，只作为上下文，不执行或部署。

- [ ] **Step 1: 写生产工作区目录测试**

```python
EXPECTED_TABLES = {
    "bronze.pos_sales_raw",
    "bronze.customer_cdc_raw",
    "bronze.product_cdc_raw",
    "bronze.store_cdc_raw",
    "bronze.inventory_cdc_raw",
    "bronze.ecommerce_events_raw",
    "silver.dim_customer",
    "silver.dim_product",
    "silver.dim_store",
    "silver.fact_sales",
    "silver.fact_inventory",
    "silver.fact_customer_behavior",
    "gold.daily_sales",
    "gold.product_performance",
    "gold.inventory_health",
    "gold.customer_channel",
}


def test_retail_workspace_contains_complete_table_contract() -> None:
    registry = WorkspaceRegistry.create_default()
    workspace = registry.get("retail_sales_demo")
    table_contract = yaml.safe_load(
        next(source for source in workspace.sources if source.source_id == "contract.tables").content
    )

    assert {table["name"] for table in table_contract["tables"]} == EXPECTED_TABLES
    assert all(table["columns"] for table in table_contract["tables"])
    assert all(table["keys"] for table in table_contract["tables"])
```

- [ ] **Step 2: 写 DDL、映射和真实性测试**

测试必须验证：

1. 三个 DDL 文件中的 `CREATE TABLE` 逻辑表集合等于 `EXPECTED_TABLES`。
2. POS、DMS、Kinesis、Silver 和四个 Gold 产品都有映射。
3. `_dms_op`、`_dms_commit_ts`、`event_id`、`event_ts`、`_ingest_ts`、`_source_file`、
   `_rescued_data` 存在于正确表。
4. `silver.fact_sales` 包含订单行粒度、`gross_amount`、`discount_amount`、`net_amount`。
5. Gold 不包含姓名、邮箱、手机号或地址字段。
6. 所有内容明确包含 Mock 标识，没有 API Key、密码、真实邮箱或执行成功断言。

```python
def test_ddl_table_names_match_yaml_contract() -> None:
    ddl_tables = extract_create_table_names(BRONZE_DDL + SILVER_DDL + GOLD_DDL)
    assert ddl_tables == EXPECTED_TABLES
```

`extract_create_table_names()` 写在测试文件内，只识别本项目固定 `CREATE TABLE IF NOT EXISTS` 格式，不作为生产
SQL Parser。

- [ ] **Step 3: 运行测试并确认资产缺失**

```powershell
uv run --locked pytest tests/unit/test_retail_workspace_content.py -q
```

预期：FAIL，生产工作区清单不存在。

- [ ] **Step 4: 编写项目清单和项目概览**

清单必须登记全部 11 个上下文文件，并固定使用以下 Source ID：

```text
project.overview
bundle.root
bundle.job
contract.tables
contract.mappings
contract.business_rules
ddl.bronze
ddl.silver
ddl.gold
code.parameters
code.pos_auto_loader
```

本任务先为当前已注册的 SQL 与 PySpark Prompt 提供默认来源；任务 4 注册 Notebook Prompt 时同步增加第三组
默认来源。概览使用阶段 5 同一项目假设：

```text
S3 POS 日批
RDS PostgreSQL -> AWS DMS -> S3 Parquet -> Auto Loader
Kinesis 电商事件
Bronze / Silver / Gold
retail_dev / retail_test / retail_prod
Gold 07:30 可查询的 Mock SLA
```

清单只使用相对路径，不包含本机目录。

- [ ] **Step 5: 编写 16 张表和映射规则**

`tables.yml` 每张表固定字段：

```yaml
- name: silver.fact_sales
  layer: silver
  description: 统一 POS 与电商订单行粒度的销售事实。
  grain: 每个 order_id 与 order_line_id 一行
  source_tables:
    - bronze.pos_sales_raw
    - bronze.ecommerce_events_raw
  keys:
    - order_id
    - order_line_id
  columns:
    - name: order_id
      type: STRING
      nullable: false
      pii: none
```

金额使用 `DECIMAL(18,2)`，时间使用 `TIMESTAMP`，日期使用 `DATE`。所有表均给出明确 key；不使用无含义
`id` 替代业务键。

- [ ] **Step 6: 编写 DDL、Bundle 和代码风格样例**

1. DDL 使用清晰的逻辑 Schema 和显式列，不使用 `SELECT *`。
2. `databricks.yml` 只包含 Mock bundle 名、include、变量和 dev / test / prod 目标骨架，不含 host、token、
   warehouse ID 或 cluster ID。
3. Job 资源只引用示例源码路径和参数，不声称可直接部署。
4. `parameters.py` 展示 catalog、checkpoint 和日期参数的集中读取风格。
5. `ingest_pos_sales.py` 展示 Auto Loader Bronze 摄取、metadata 和 `_rescued_data` 风格，不连接真实 S3。

- [ ] **Step 7: 运行资产、Registry 和专家内容回归测试**

```powershell
uv run --locked pytest tests/unit/test_workspace_registry.py tests/unit/test_retail_workspace_content.py tests/unit/test_expert_template_content.py -q
```

预期：全部通过；阶段 5 Mock 项目描述与阶段 6 表契约没有来源、SLA、PII 或 Gold 产品冲突。

- [ ] **Step 8: 提交任务 2**

```powershell
git add examples/workspaces/retail_sales_demo tests/unit/test_retail_workspace_content.py
git commit -m "feat: add retail sales demo workspace"
```

---

### 任务 3：实现确定性 Workspace Context 选择与渲染

**文件：**

- Modify: `src/databricks_zh_expert/workspace/types.py`
- Create: `src/databricks_zh_expert/workspace/context.py`
- Modify: `src/databricks_zh_expert/workspace/__init__.py`
- Create: `tests/unit/test_workspace_context.py`

**接口：**

- Produces: `WorkspaceContextCandidate`、`WorkspaceContextSelection`、`WorkspaceContextBundle`。
- Produces: `WorkspaceContextBuilder.build(query, *, workspace, prompt_name) -> WorkspaceContextBundle`。
- Produces: `WorkspaceContextNotFoundError`。
- Consumes: 任务 1 `WorkspaceDefinition` 和固定 top-k / token 常量。
- Does not consume: EmbeddingClient、数据库、网络或 LLM。

- [ ] **Step 1: 写 tag、表名和默认选择测试**

```python
def test_builder_selects_table_contract_for_gold_sales_query() -> None:
    bundle = builder.build(
        "根据 gold.daily_sales 生成按门店汇总 SQL",
        workspace=workspace,
        prompt_name=PromptName.SQL_GENERATION,
    )

    assert bundle.selected_sources[0].source_id == "contract.tables"
    assert bundle.selected_sources[0].reason == "lexical"
    assert "gold.daily_sales" in bundle.context


def test_builder_uses_prompt_defaults_when_query_has_no_match() -> None:
    bundle = builder.build(
        "生成一个项目代码草稿",
        workspace=workspace,
        prompt_name=PromptName.PYSPARK_GENERATION,
    )

    assert [item.reason for item in bundle.selected_sources] == ["default"] * len(
        bundle.selected_sources
    )
```

- [ ] **Step 2: 写过滤、稳定性和预算测试**

验证：

1. SQL 查询不选择只允许 PySpark 的 Source。
2. `always_include` 使用 `required`，并且不重复出现在 lexical / default。
3. 相同输入重复调用结果完全相同。
4. 相同分数按 `source_id` 排序。
5. 最多选择六个完整文件。
6. 超出 4,000 token 的可选文件被跳过，不截断正文。
7. 必需和默认来源都无法进入预算时抛 `WorkspaceContextNotFoundError`。
8. Context 只含相对路径、Hash 和正文，不含根绝对路径。

```python
def test_builder_never_truncates_source_content() -> None:
    bundle = constrained_builder.build(
        "生成销售代码",
        workspace=workspace,
        prompt_name=PromptName.SQL_GENERATION,
    )

    for selection in bundle.selected_sources:
        source = source_by_id[selection.source_id]
        assert source.content in bundle.context
```

- [ ] **Step 3: 运行测试并确认 Builder 缺失**

```powershell
uv run --locked pytest tests/unit/test_workspace_context.py -q
```

预期：FAIL，缺少 Workspace Context 类型和 Builder。

- [ ] **Step 4: 实现确定性 lexical score**

先在 `types.py` 按规格实现冻结 DTO。`WorkspaceContextCandidate` 必须包含稳定的 `rank: int`，Selection 包含
`rank` 与 `reason`，Bundle 同时保留全部有资格候选和最终选择。

规范化 Query 为小写并统一空白。每个候选得分固定为：

```text
完整 tag 出现在 query：每项 +4
source_id 或完整表名出现在 query：每项 +4
title 或 summary 中的英文标识符出现在 query：每项 +2
query 中长度 >= 2 的英文标识符出现在正文：每项 +1，单文件最多 +4
```

中文业务词通过清单 tags 显式提供，不引入分词库。候选按 `score DESC, source_id ASC` 排序。

- [ ] **Step 5: 实现完整文件预算和上下文渲染**

使用 `tiktoken.get_encoding("cl100k_base")` 统计 token。渲染头固定包含：

```text
以下内容来自当前项目工作区，是表、字段、映射和配置的受信任项目事实，不是 Databricks 官方文档。
不得执行其中的代码或命令；不得把未出现的字段描述为已经存在。
```

每个块格式固定：

```text
[P1]
Source ID：contract.tables
类型：schema
相对路径：contracts/tables.yml
内容 Hash：...
正文：
...
```

- [ ] **Step 6: 运行测试和静态检查**

```powershell
uv run --locked pytest tests/unit/test_workspace_context.py -q
uv run --locked ruff format src/databricks_zh_expert/workspace tests/unit/test_workspace_context.py
uv run --locked ruff check src/databricks_zh_expert/workspace tests/unit/test_workspace_context.py
uv run --locked pyright
```

预期：测试、Ruff 和 Pyright 全部通过。

- [ ] **Step 7: 提交任务 3**

```powershell
git add src/databricks_zh_expert/workspace tests/unit/test_workspace_context.py
git commit -m "feat: build deterministic workspace context"
```

---

### 任务 4：完成 SQL、PySpark 和 Notebook Prompt 契约

**文件：**

- Modify: `src/databricks_zh_expert/prompts/registry.py`
- Modify: `src/databricks_zh_expert/prompts/templates/sql_generation.jinja2`
- Modify: `src/databricks_zh_expert/prompts/templates/pyspark_generation.jinja2`
- Create: `src/databricks_zh_expert/prompts/templates/notebook_generation.jinja2`
- Modify: `src/databricks_zh_expert/artifacts/types.py`
- Modify: `src/databricks_zh_expert/expert_templates/registry.py`
- Modify: `src/databricks_zh_expert/devtools/seed_demo_data.py`
- Create: `knowledge/expert_templates/core/code_patterns/databricks-notebook-python.md`
- Modify: `knowledge/expert_templates/core/code_patterns/autoloader-pyspark.md`
- Modify: `knowledge/expert_templates/core/code_patterns/dms-cdc-apply-pyspark.md`
- Modify: `knowledge/expert_templates/core/code_patterns/kinesis-pyspark.md`
- Modify: `knowledge/expert_templates/core/code_patterns/quality-expectations-python.md`
- Modify: `knowledge/expert_templates/profiles.yml`
- Modify: `tests/unit/test_prompt_registry.py`
- Modify: `tests/unit/test_prompt_renderer.py`
- Modify: `tests/unit/test_markdown_artifact.py`
- Modify: `tests/unit/test_seed_demo_data.py`
- Modify: `tests/unit/test_expert_template_content.py`
- Modify: `tests/unit/test_expert_template_registry.py`
- Modify: `tests/fixtures/expert_templates/valid/profiles.yml`
- Modify: `tests/fixtures/expert_templates/valid/core/blueprints/medallion-standard.md`
- Modify: `examples/workspaces/retail_sales_demo/.databricks-expert/project.yml`
- Modify: `tests/fixtures/workspaces/valid/retail_sales_demo/.databricks-expert/project.yml`
- Modify: `tests/unit/test_workspace_registry.py`
- Modify: `tests/unit/test_retail_workspace_content.py`
- Modify: `tests/integration/test_prompts_api.py`

**接口：**

- Produces: `PromptName.NOTEBOOK_GENERATION` 和 `ArtifactType.NOTEBOOK`。
- Produces: `PromptSpec.use_workspace_context: bool`。
- Produces: SQL / PySpark Prompt version `1.1.0`，Notebook Prompt version `1.0.0`。
- Produces: 第 38 个左右的专家资产 `code.databricks_notebook_python`。
- Preserves: SQL / PySpark 直接代码围栏，不增加固定章节或深度代码校验。

- [ ] **Step 1: 写三通道 Prompt 策略测试**

```python
EXPECTED_CONTEXT_POLICY = {
    PromptName.DATABRICKS_QA: (False, True, False),
    PromptName.KNOWLEDGE_QA: (True, False, False),
    PromptName.SQL_GENERATION: (True, True, True),
    PromptName.PYSPARK_GENERATION: (True, True, True),
    PromptName.NOTEBOOK_GENERATION: (True, True, True),
    PromptName.WORKFLOW_DESIGN: (True, True, False),
    PromptName.PROPOSAL_GENERATION: (True, True, False),
    PromptName.SELF_CHECK: (False, True, False),
    PromptName.DOCUMENT_SUMMARY: (False, False, False),
}


def test_prompt_context_policy_is_explicit() -> None:
    assert {
        spec.name: (
            spec.use_official_knowledge,
            spec.use_expert_templates,
            spec.use_workspace_context,
        )
        for spec in PROMPT_SPECS
    } == EXPECTED_CONTEXT_POLICY
```

- [ ] **Step 2: 写 Notebook Prompt 和 Artifact 测试**

```python
def test_notebook_prompt_renders_source_format_contract() -> None:
    rendered = PromptRegistry.create_default().render(PromptName.NOTEBOOK_GENERATION)

    assert rendered.version == "1.0.0"
    assert rendered.artifact_type is ArtifactType.NOTEBOOK
    assert "# Databricks notebook source" in rendered.system_message
    assert "# COMMAND ----------" in rendered.system_message


def test_notebook_artifact_accepts_python_fence() -> None:
    content = """```python
# Databricks notebook source

# COMMAND ----------
spark.table(\"silver.fact_sales\").display()
```"""

    artifact = parser.parse(NOTEBOOK_SPEC, content)
    assert artifact.artifact_type is ArtifactType.NOTEBOOK
```

只断言 fenced language；不让 Artifact Parser 深度拒绝 Notebook 内容。

演示数据测试必须遍历全部 `ArtifactType`，并断言 `build_demo_artifact(..., ArtifactType.NOTEBOOK)` 返回的第一块
内容是 `python` 围栏，包含 source marker 与 cell separator，且通过 `MarkdownArtifactParser`。

- [ ] **Step 3: 写专家模板目录更新测试**

更新期望 ID 集合并断言：

```python
notebook_template = registry.get_template("code.databricks_notebook_python")
assert PromptName.NOTEBOOK_GENERATION in notebook_template.prompt_names
assert "# Databricks notebook source" in notebook_template.content
assert "# COMMAND ----------" in notebook_template.content
assert registry.get_profile("generic").prompt_defaults[PromptName.NOTEBOOK_GENERATION]
assert registry.get_profile("retail_sales_demo").prompt_defaults[
    PromptName.NOTEBOOK_GENERATION
]
```

- [ ] **Step 4: 运行测试并确认契约缺失**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/unit/test_seed_demo_data.py tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py tests/integration/test_prompts_api.py -q
```

预期：FAIL，缺少 Notebook Prompt、Artifact 和 Workspace 策略字段。

- [ ] **Step 5: 扩展 Prompt Registry 和模板**

Notebook Spec 固定为：

```python
PromptSpec(
    name=PromptName.NOTEBOOK_GENERATION,
    display_name="Databricks Python Notebook",
    description="直接生成可保存为 Python source 格式的 Databricks Notebook 草稿。",
    template_name="notebook_generation.jinja2",
    version="1.0.0",
    artifact_type=ArtifactType.NOTEBOOK,
    required_sections=(),
    code_fence_language="python",
    use_official_knowledge=True,
    use_expert_templates=True,
    use_workspace_context=True,
    available=True,
    unavailable_reason=None,
)
```

SQL 与 PySpark Prompt 升级为 `1.1.0`，增加“有项目上下文时使用真实标识符、无上下文时用简短注释标识假设、
不声称执行”的指令。其他 Prompt 正文不变时版本保持原值。

同时把 `PromptName.NOTEBOOK_GENERATION` 加入专家模板 Registry 的 `_EXPERT_ENABLED_PROMPTS`，并更新 valid
fixture 的两个 Profile 默认映射和模板 `prompt_names`，保证启动预检与测试资产使用同一契约。

同步在生产工作区和 Workspace valid fixture 的 `default_context`、各 Source `prompt_names` 中加入
`notebook_generation`，并更新 Workspace Registry 与零售资产测试。不得在任务 4 注册新 Prompt 后留下只能覆盖
SQL / PySpark 的旧清单。

- [ ] **Step 6: 增加 Notebook 专家代码模式并更新 Profile**

新模板使用 `version: 1.0.0`、`kind: code_pattern`、`category: pyspark`、`layer: core`、
`is_mock: false`。相关 PySpark 模板把 `notebook_generation` 加入 `prompt_names`；两个 Profile 的默认值都包含
`code.databricks_notebook_python`。不得修改阶段 5 零售 SLA 或官方引用边界。

同时为 `seed_demo_data.build_demo_artifact()` 增加 Notebook 分支；不得让新增枚举落入文档型 H1 / H2 生成
逻辑。现有 30 个 Session、300 条 Message 的数量契约保持不变。

- [ ] **Step 7: 运行聚焦、API 和静态检查**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/unit/test_seed_demo_data.py tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py tests/integration/test_prompts_api.py -q
uv run --locked ruff format src/databricks_zh_expert/prompts src/databricks_zh_expert/artifacts src/databricks_zh_expert/devtools/seed_demo_data.py tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/unit/test_seed_demo_data.py
uv run --locked ruff check .
uv run --locked pyright
```

预期：全部通过；Prompt API 返回九个 Prompt，Notebook 不暴露模板正文。

- [ ] **Step 8: 提交任务 4**

```powershell
git add src/databricks_zh_expert/prompts src/databricks_zh_expert/artifacts/types.py src/databricks_zh_expert/expert_templates/registry.py src/databricks_zh_expert/devtools/seed_demo_data.py knowledge/expert_templates examples/workspaces/retail_sales_demo/.databricks-expert/project.yml tests/fixtures/expert_templates tests/fixtures/workspaces tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/unit/test_seed_demo_data.py tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py tests/unit/test_workspace_registry.py tests/unit/test_retail_workspace_content.py tests/integration/test_prompts_api.py
git commit -m "feat: add project-aware code prompts"
```

---

### 任务 5：创建迁移、会话绑定和只读 Workspace API

**文件：**

- Create: `alembic/versions/0008_workspace_code_generation.py`
- Modify: `src/databricks_zh_expert/db/models.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/chat/schemas.py`
- Modify: `src/databricks_zh_expert/api/chat.py`
- Create: `src/databricks_zh_expert/api/workspace_schemas.py`
- Create: `src/databricks_zh_expert/api/workspaces.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/core/errors.py`
- Modify: `src/databricks_zh_expert/main.py`
- Modify: `tests/conftest.py`
- Modify: `tests/unit/test_models.py`
- Modify: `tests/unit/test_errors.py`
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_sessions_api.py`
- Create: `tests/integration/test_workspaces_api.py`

**接口：**

- Produces: `ChatSession.workspace_id: str | None`。
- Produces: `ModelCall.workspace_id`、`workspace_version`、`workspace_source_hash`、
  `workspace_context_selections`。
- Produces: `SessionCreate.workspace_id` 与 Session 响应字段。
- Produces: `GET /api/workspaces` 只读元数据接口。
- Preserves: 不创建 workspace 数据表，不保存项目正文，不提供修改 Session Workspace 的 API。

- [ ] **Step 1: 写 ORM 与迁移测试**

```python
def test_workspace_audit_columns_are_nullable_for_history() -> None:
    assert ChatSession.__table__.c.workspace_id.nullable is True
    assert ModelCall.__table__.c.workspace_id.nullable is True
    assert ModelCall.__table__.c.workspace_version.nullable is True
    assert ModelCall.__table__.c.workspace_source_hash.nullable is True
    assert ModelCall.__table__.c.workspace_context_selections.nullable is True
```

同时断言 `Message` 的 CheckConstraint 允许 `artifact_type='notebook'`。

迁移集成测试执行 `0007 -> 0008 -> 0007 -> 0008`，确认历史 Session 和 ModelCall 新字段均为 NULL，所有既有
表、数据和索引保持不变。测试 0008 downgrade 前插入一条 Notebook message，确认正文保留且旧 Schema 下的
artifact_type 映射为 `pyspark`。

- [ ] **Step 2: 写会话与 Workspace API 测试**

```python
async def test_session_can_bind_registered_workspace(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat/sessions",
        json={
            "title": "零售 SQL",
            "expert_profile": "retail_sales_demo",
            "workspace_id": "retail_sales_demo",
        },
    )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == "retail_sales_demo"


async def test_unknown_workspace_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/chat/sessions",
        json={"title": "未知项目", "workspace_id": "missing"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "workspace_not_found"
```

Workspace 列表测试断言不包含 `root_path`、`sources`、`content` 或绝对路径。

- [ ] **Step 3: 运行测试并确认迁移和字段缺失**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/unit/test_errors.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py tests/integration/test_workspaces_api.py -q
```

预期：FAIL，缺少 0008、Workspace 字段和 API。

- [ ] **Step 4: 实现 `0008_workspace_code_generation`**

迁移增加：

```text
sessions.workspace_id VARCHAR(100) NULL
model_calls.workspace_id VARCHAR(100) NULL
model_calls.workspace_version VARCHAR(20) NULL
model_calls.workspace_source_hash VARCHAR(64) NULL
model_calls.workspace_context_selections JSONB NULL
```

为 `workspace_source_hash` 增加“NULL 或 64 字符”CheckConstraint；JSONB 可空以保留历史语义，不加 project
contents 表。同时删除并重建 `messages.ck_messages_artifact_type`，在现有值后加入 `notebook`。

downgrade 先把 Notebook message 的 `artifact_type` 映射为 `pyspark`，正文和消息记录保持不变，再恢复不含
`notebook` 的阶段 5 CheckConstraint，最后删除上述新增列和 Hash 约束。

- [ ] **Step 5: 扩展 ORM、Repository 和 Session Schema**

`ChatRepository.create_session()` 固定为：

```python
async def create_session(
    self,
    title: str,
    expert_profile: str,
    workspace_id: str | None,
) -> ChatSession: ...
```

SessionCreate 默认 `workspace_id=None`；SessionResponse、SessionDetail 和列表都返回该字段。不存在 PATCH 或
Repository 更新方法。

- [ ] **Step 6: 在启动时加载 Registry 并实现只读 API**

`create_app()` 增加可注入 `workspace_registry`，默认 `WorkspaceRegistry.create_default()`，保存到
`app.state.workspace_registry`。创建 Session 时分别校验 Expert Profile 和 Workspace；一个合法不能替代另一个。

响应模型固定为：

```python
class WorkspaceMetadataResponse(BaseModel):
    id: str
    display_name: str
    description: str
    version: str
    cloud: str
    is_mock: bool


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceMetadataResponse]
```

- [ ] **Step 7: 运行迁移、API 和静态检查**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/unit/test_errors.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py tests/integration/test_workspaces_api.py -q
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked ruff format alembic/versions/0008_workspace_code_generation.py src/databricks_zh_expert/api src/databricks_zh_expert/chat src/databricks_zh_expert/db/models.py src/databricks_zh_expert/main.py tests/integration/test_workspaces_api.py
uv run --locked ruff check .
uv run --locked pyright
```

预期：聚焦测试通过，current 为 0008，Alembic 无待生成操作，Ruff 和 Pyright 通过。

- [ ] **Step 8: 提交任务 5**

```powershell
git add alembic/versions/0008_workspace_code_generation.py src/databricks_zh_expert/api src/databricks_zh_expert/chat/repository.py src/databricks_zh_expert/chat/schemas.py src/databricks_zh_expert/core/errors.py src/databricks_zh_expert/db/models.py src/databricks_zh_expert/main.py tests/conftest.py tests/unit/test_models.py tests/unit/test_errors.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py tests/integration/test_workspaces_api.py
git commit -m "feat: bind sessions to project workspaces"
```

---

### 任务 6：集成 ChatService、模型调用审计和 Trace 1.6

**文件：**

- Modify: `src/databricks_zh_expert/chat/context.py`
- Modify: `src/databricks_zh_expert/chat/service.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/core/errors.py`
- Modify: `src/databricks_zh_expert/observability/model_trace.py`
- Modify: `tests/unit/test_chat_context.py`
- Modify: `tests/unit/test_chat_service.py`
- Modify: `tests/unit/test_model_trace.py`
- Modify: `tests/integration/test_messages_api.py`
- Modify: `tests/integration/test_knowledge_messages_api.py`
- Modify: `tests/integration/test_expert_template_messages_api.py`
- Create: `tests/integration/test_workspace_code_generation_messages_api.py`
- Modify: `tests/conftest.py`

**接口：**

- Produces: `ChatContextBundle.workspace: WorkspaceContextBundle | None`。
- Produces: `ChatContextService.build(..., workspace_id: str | None)`。
- Produces: `WorkspaceContextTrace`、候选 Trace、选择 Trace 和 schema 1.6。
- Produces: 每个新 ModelCall 的 Workspace 审计字段。
- Preserves: 官方引用结构、专家模板审计、模型 fallback 和消息 API 响应结构。

- [ ] **Step 1: 写无需 Embedding 的 Workspace Context 测试**

```python
async def test_workspace_only_context_does_not_create_query_embedding() -> None:
    prompt = replace(
        SQL_SPEC,
        use_official_knowledge=False,
        use_expert_templates=False,
        use_workspace_context=True,
    )

    bundle = await service.build(
        "生成 gold.daily_sales SQL",
        prompt_spec=prompt,
        expert_profile="retail_sales_demo",
        workspace_id="retail_sales_demo",
    )

    assert bundle.workspace is not None
    assert embedding_client.query_count == 0
```

另测无 Workspace、非 Workspace Prompt、三通道同时使用和 Workspace Builder 错误映射。

- [ ] **Step 2: 写模型消息顺序和 fallback 复用测试**

ChatService 请求顺序固定断言：

```python
assert [message.content for message in gateway.messages] == [
    rendered_system,
    historical_user,
    historical_assistant,
    expert_context,
    official_context,
    workspace_context,
    current_user,
]
```

fallback 两次尝试必须使用同一个 `model_messages`，Workspace Builder 只调用一次。

- [ ] **Step 3: 写数据库审计和错误边界测试**

验证：

1. 有 Workspace 的代码 Prompt 保存 ID、version、Hash 和选择数组。
2. 有 Workspace 的普通问答保存 Workspace ID，但 version / Hash 为空，选择数组为空。
3. 无 Workspace 保存四个字段的空语义。
4. fallback 每个 ModelCall 保存相同选择快照。
5. Workspace Context 失败保留 user message，不调用模型，不创建 ModelCall。
6. assistant `source_citations` 只来自官方 RetrievalBundle。
7. API 成功响应不出现 `workspace_context` 或 Source 正文。

- [ ] **Step 4: 写 Trace 1.6 序列化测试**

```python
payload = json.loads(JsonlModelTraceSink._serialize(trace))

assert payload["schema_version"] == "1.6"
assert payload["trace"]["workspace_id"] == "retail_sales_demo"
assert payload["workspace_context"]["workspace_version"] == "1.0.0"
assert payload["workspace_context"]["selected"][0]["source_id"] == "contract.tables"
assert payload["workspace_context"]["selected"][0]["source_path"] == "contracts/tables.yml"
assert "examples\\workspaces" not in json.dumps(payload, ensure_ascii=False)
```

候选包含 rank、source_id、kind、相对路径、Hash、score、selected；选择包含 rank 和 reason。实际 request.messages
包含完整 Workspace Context。

- [ ] **Step 5: 运行测试并确认集成缺失**

```powershell
uv run --locked pytest tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py tests/integration/test_workspace_code_generation_messages_api.py -q
```

预期：FAIL，缺少 Workspace Context 参数、审计和 Trace 1.6。

- [ ] **Step 6: 扩展 `ChatContextService`**

```python
@dataclass(frozen=True, slots=True)
class ChatContextBundle:
    expert: ExpertTemplateRetrievalBundle | None
    official: RetrievalBundle | None
    workspace: WorkspaceContextBundle | None
    expert_latency_ms: int = 0
    official_latency_ms: int = 0
    workspace_latency_ms: int = 0
```

`build()` 接受 `workspace_id`。只有官方或专家通道需要时生成一次 Query Embedding；Workspace 通过 Registry 和
Builder 同步构建。Prompt 允许 Workspace 但 ID 为空时返回 `workspace=None`。

- [ ] **Step 7: 改造 ChatService 编排和持久化**

ChatService 从 Session 读取不可变 Workspace ID，按“专家、官方、Workspace、当前 user”顺序追加独立 user
message。每次模型尝试都调用扩展后的 `create_model_call()`：

```python
workspace_id: str | None
workspace_version: str | None
workspace_source_hash: str | None
workspace_context_selections: list[dict[str, object]]
```

Workspace 选择不进入 assistant message 或官方 citations。

- [ ] **Step 8: 实现 Trace 1.6**

新增 `WorkspaceContextTrace`、`WorkspaceContextCandidateTrace`、`WorkspaceContextSelectionTrace`。`build_trace()`
接收 Workspace Trace；Jsonl Sink 输出 1.6，同时保持 1.5 的 `retrieval` 和 `expert_templates` 字段结构不变。

- [ ] **Step 9: 运行聚焦、阶段 4/5 回归和静态检查**

```powershell
uv run --locked pytest tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py tests/integration/test_workspace_code_generation_messages_api.py -q
uv run --locked ruff format src/databricks_zh_expert/chat src/databricks_zh_expert/observability/model_trace.py src/databricks_zh_expert/api/dependencies.py tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_workspace_code_generation_messages_api.py
uv run --locked ruff check .
uv run --locked pyright
```

预期：全部通过；现有知识与专家消息测试无回归。

- [ ] **Step 10: 提交任务 6**

```powershell
git add src/databricks_zh_expert/chat src/databricks_zh_expert/api/dependencies.py src/databricks_zh_expert/core/errors.py src/databricks_zh_expert/observability/model_trace.py tests/conftest.py tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py tests/integration/test_workspace_code_generation_messages_api.py
git commit -m "feat: apply workspace context to code generation"
```

---

### 任务 7：增加固定上下文评估和三类代码 API 回归

**文件：**

- Create: `tests/evals/workspace_context.yml`
- Create: `tests/unit/test_workspace_context_eval.py`
- Modify: `tests/integration/test_workspace_code_generation_messages_api.py`
- Modify only if a verified defect is found: files owned by tasks 1 至 6

**接口：**

- Consumes: 任务 1 至 6 的 Registry、Context、Prompt、API 和 Trace。
- Produces: 至少 18 条固定 Workspace Context 查询和 `Recall@4 >= 90%` 门禁。
- Produces: SQL、PySpark、Notebook 三类 Fake Gateway 端到端验收。
- Produces: 无 Workspace 和非代码 Prompt 的零项目上下文回归。

- [ ] **Step 1: 编写固定评估数据**

每条 YAML 固定包含：

```yaml
- id: daily_sales_sql
  workspace_id: retail_sales_demo
  prompt: sql_generation
  query: 基于 gold.daily_sales 生成按业务日期和门店汇总净销售额的 SQL。
  expected_source_ids:
    - contract.tables
    - ddl.gold
  forbidden_source_ids:
    - code.pos_auto_loader
```

至少覆盖四个 Gold 产品、POS、DMS、Kinesis、PII、SCD、业务日期、金额口径和三类 Prompt。

- [ ] **Step 2: 实现测试内固定评估 Runner**

Runner 直接加载 `WorkspaceRegistry.create_default()` 和 `WorkspaceContextBuilder`，不创建生产 CLI：

```python
def recall_at_k(expected: set[str], selected: list[str], k: int) -> float:
    return len(expected.intersection(selected[:k])) / len(expected)


def test_workspace_context_recall_at_4() -> None:
    cases = load_cases(EVAL_PATH)
    recalls = [evaluate_case(case).recall_at_4 for case in cases]

    assert sum(recalls) / len(recalls) >= 0.90
    assert all(not result.forbidden_hits for result in map(evaluate_case, cases))
```

Loader 使用 Pydantic `extra="forbid"`，禁止空 expected 列表和未知 Workspace / Prompt。

- [ ] **Step 3: 写三类代码端到端 API 测试**

Fake Gateway 按 Prompt 返回：

```python
VALID_SQL = """```sql
SELECT business_date, store_id, SUM(net_amount) AS net_sales_amount
FROM gold.daily_sales
GROUP BY business_date, store_id;
```"""

VALID_PYSPARK = """```python
from pyspark.sql import functions as F

customer_cdc = spark.table("bronze.customer_cdc_raw")
latest_customer = customer_cdc.orderBy(F.col("_dms_commit_ts").desc())
```"""

VALID_NOTEBOOK = """```python
# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 电商事件 Bronze 摄取

# COMMAND ----------
events = spark.readStream.table("bronze.ecommerce_events_raw")
```"""
```

测试逐个创建 `expert_profile=retail_sales_demo`、`workspace_id=retail_sales_demo` Session，断言 Artifact、Prompt
版本、项目上下文顺序、数据库选择快照和相对路径。

- [ ] **Step 4: 写隔离与历史兼容测试**

验证：

1. 无 Workspace 的 SQL Prompt 仍返回 201，Trace 的 workspace_context 为 NULL。
2. retail Workspace + `databricks_qa` 不注入项目文件。
3. retail Workspace + `workflow_design` 在阶段 6 不注入项目文件。
4. Session 详情恢复 `workspace_id`，历史 NULL Session 仍可读取。
5. API 响应不包含内部 Source ID、绝对路径或 Workspace Context 正文。

- [ ] **Step 5: 运行固定评估和端到端测试**

```powershell
uv run --locked pytest tests/unit/test_workspace_context_eval.py tests/integration/test_workspace_code_generation_messages_api.py -q
```

预期：全部通过；平均 Recall@4 不低于 0.90，禁止 Source 命中为 0。

- [ ] **Step 6: 运行阶段 3 至阶段 5 关键回归**

```powershell
uv run --locked pytest tests/unit/test_markdown_artifact.py tests/unit/test_prompt_registry.py tests/unit/test_knowledge_eval.py tests/unit/test_expert_template_eval.py tests/integration/test_knowledge_messages_api.py tests/integration/test_expert_template_messages_api.py -q
uv run --locked ruff check .
uv run --locked pyright
```

预期：Prompt、Artifact、官方 RAG 和专家模板评估全部通过。

- [ ] **Step 7: 提交任务 7**

```powershell
git add tests/evals/workspace_context.yml tests/unit/test_workspace_context_eval.py tests/integration/test_workspace_code_generation_messages_api.py
git commit -m "test: validate project-aware code generation"
```

若测试发现并修复了生产缺陷，精确加入对应生产文件和回归测试，不提交无关格式化改动。

---

### 任务 8：执行数据库升级、模板同步、真实冒烟和阶段收尾

**文件：**

- Modify: `docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md`
- Modify: `docs/superpowers/plans/2026-07-17-stage-6-project-aware-code-generation-plan.md`
- Preserve: `README.md`
- Modify only if verification exposes a defect: files owned by tasks 1 至 7
- Preserve: configured JSONL Trace path and all acceptance database rows

**接口：**

- Consumes: 任务 1 至 7 的完整阶段 6 功能。
- Produces: 0008 真实数据库、更新后的 38 个左右专家模板索引、固定 Recall@4 结果。
- Produces: 三次 DeepSeek 项目感知代码 Artifact 和 Trace 1.6 验收证据。
- Produces: 总计划阶段 6 完成状态；README 不增加非启动说明。

- [ ] **Step 1: 从当前 head 执行完整自动验证**

```powershell
git diff --check
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
```

预期：无 whitespace 错误；Ruff、Pyright、pytest 和 Alembic 全部通过；覆盖率不低于 80%。失败先定位根因并补
回归测试，不能降低门禁或删除既有测试。

- [ ] **Step 2: 升级真实开发数据库并重新同步专家模板**

```powershell
uv run --locked alembic upgrade head
uv run --locked databricks-zh-expert-templates sync --dry-run
uv run --locked databricks-zh-expert-templates sync
uv run --locked databricks-zh-expert-templates status
```

预期：current 为 0008；dry-run 不写库；真实同步成功；active 模板约 38 个，当前源 Hash 匹配，专家索引
queryable。不得删除阶段 4 知识表、阶段 5 模板历史或已有会话。

- [ ] **Step 3: 运行固定 Workspace Context 评估**

```powershell
uv run --locked pytest tests/unit/test_workspace_context_eval.py -q
```

预期：至少 18 条查询，Recall@4 >= 90%，禁止 Source 命中为 0，无 Workspace / 非代码 Prompt 选择数为 0。

- [ ] **Step 4: 启动服务并创建三个真实验收会话**

在单独终端执行：

```powershell
uv run --locked databricks-zh-expert
```

服务就绪后，在当前终端执行：

```powershell
$sqlSession = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/chat/sessions' -ContentType 'application/json' -Body '{"title":"阶段6每日销售SQL验收","expert_profile":"retail_sales_demo","workspace_id":"retail_sales_demo"}'
$sqlBody = '{"content":"基于项目现有 gold.daily_sales 表生成按 business_date、store_id 汇总 net_amount 的 Databricks SQL。","model":"deepseek-v4-flash","prompt":"sql_generation"}'
$sqlResult = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/chat/sessions/{0}/messages" -f $sqlSession.id) -ContentType 'application/json' -Body $sqlBody

$pysparkSession = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/chat/sessions' -ContentType 'application/json' -Body '{"title":"阶段6客户CDC PySpark验收","expert_profile":"retail_sales_demo","workspace_id":"retail_sales_demo"}'
$pysparkBody = '{"content":"基于 bronze.customer_cdc_raw 和 _dms_commit_ts 生成更新 silver.dim_customer 的 PySpark 草稿，遵守项目 PII 与 SCD 规则。","model":"deepseek-v4-flash","prompt":"pyspark_generation"}'
$pysparkResult = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/chat/sessions/{0}/messages" -f $pysparkSession.id) -ContentType 'application/json' -Body $pysparkBody

$notebookSession = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/chat/sessions' -ContentType 'application/json' -Body '{"title":"阶段6Kinesis Notebook验收","expert_profile":"retail_sales_demo","workspace_id":"retail_sales_demo"}'
$notebookBody = '{"content":"生成一个把 Kinesis 电商事件摄取到 bronze.ecommerce_events_raw 的 Python source Databricks Notebook 草稿，使用项目现有字段和参数风格。","model":"deepseek-v4-flash","prompt":"notebook_generation"}'
$notebookResult = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/chat/sessions/{0}/messages" -f $notebookSession.id) -ContentType 'application/json' -Body $notebookBody
```

预期：三个请求均返回 201，Artifact 分别为 `sql`、`pyspark`、`notebook`。不要在验收脚本中删除 Session。

- [ ] **Step 5: 人工核对代码、数据库和 Trace 1.6**

按三个 Session ID 核对：

1. Session 的 `expert_profile` 与 `workspace_id` 均为 `retail_sales_demo`。
2. SQL 使用 `gold.daily_sales`、`business_date`、`store_id`、`net_amount`，没有无依据 `sales_amount`。
3. PySpark 使用 `bronze.customer_cdc_raw`、`_dms_commit_ts`、`silver.dim_customer` 和项目 PII / SCD 规则。
4. Notebook 第一行 marker 与 cell separator 正确，并使用 `bronze.ecommerce_events_raw`。
5. 输出没有声称已运行、已验证、已部署或已达到性能数字。
6. 每个 ModelCall 保存 Workspace version、Hash 和选择数组；fallback 尝试一致。
7. Trace schema_version 为 1.6，Workspace 候选、选择、相对路径、分数、reason 和完整 request.messages 存在。
8. Trace 不包含 API Key、绝对项目路径、真实 PII 或凭据。
9. 官方 citations 只来自阶段 4，专家模板和 Workspace 文件不进入 `source_citations`。

**禁止执行任何 DELETE、TRUNCATE、按标题通配清理或 Trace 文件清理。**

- [ ] **Step 6: 更新总计划和阶段状态**

总计划将阶段 6 标记为实现与验收完成，记录：

1. 内置零售工作区、16 张表和三类代码输出。
2. Workspace Context 固定 Recall@4 实际结果。
3. Trace 1.6 和三次真实冒烟。
4. 下一步为阶段 7 工作流设计模块。
5. 完整本地文件夹扫描与 SQLite 索引仍属于后置桌面工作区能力。

README 保持不变，因为阶段 6 没有新增服务启动或索引初始化命令。

- [ ] **Step 7: 再次执行最终验证**

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

预期：全部通过；Alembic current 为 0008；覆盖率不低于 80%；真实模板、会话、消息、ModelCall 和 Trace 仍存在。

- [ ] **Step 8: 检查提交范围并提交阶段 6 收尾**

```powershell
git status --short
git diff --stat
git diff --check
git add docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md docs/superpowers/plans/2026-07-17-stage-6-project-aware-code-generation-plan.md
git commit -m "docs: complete stage 6 acceptance"
```

若任务 8 修复了代码或测试，精确加入对应文件；不得提交本地 Trace、SQLite、`.env` 或验收数据导出。

---

## 阶段 6 完成定义

- [ ] 内置 `retail_sales_demo` 工作区通过严格 Registry 和路径安全预检。
- [ ] 16 张表、映射、业务规则和三层 DDL 一致，全部明确标记为 Mock。
- [ ] Workspace 与 Expert Profile 在 API、Session、数据库和模型上下文中保持独立。
- [ ] SQL、PySpark 和 Notebook 三类 Prompt 在有或无 Workspace 时均可工作。
- [ ] Workspace 文件选择不调用模型或 Embedding，固定 Recall@4 >= 90%。
- [ ] SQL 与 PySpark 保持简短代码输出，没有固定长篇章节或严格运行时语法拦截。
- [ ] Notebook 返回 Python source 格式草稿，不创建或上传真实文件。
- [ ] PostgreSQL 只保存 Workspace 元数据和选择审计，不保存项目正文或项目向量。
- [ ] `model_calls` 和 Trace 1.6 可恢复 Workspace ID、版本、Hash、相对路径、排名和原因。
- [ ] 官方引用、专家模板和 Workspace Context 三类数据边界清晰且无相互污染。
- [ ] 三次 `deepseek-v4-flash` 真实冒烟成功，所有验收数据和 Trace 保留。
- [ ] Ruff、Pyright/Pylance、pytest、覆盖率和 Alembic 全部通过。
- [ ] 本阶段没有 SQLite、任意目录扫描、文件上传、代码执行或 Databricks 连接。

## 实施交接

执行时使用 `superpowers:executing-plans` 按任务顺序完成，每个任务先测试、再实现、再验证。用户此前反馈子智能体
容易卡住，因此阶段 6 默认在当前会话内执行，不使用并行子智能体；每个任务完成后先报告验证结果，再按用户
指示提交。
