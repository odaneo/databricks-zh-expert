# 阶段 6：项目感知代码生成模块设计

## 1. 背景

阶段 1 至阶段 5 已经完成 FastAPI 后端、OpenAI / DeepSeek 模型网关、Prompt Registry、Markdown
Artifact、Databricks 官方知识库 RAG，以及“通用核心层 + AWS 零售销售 Mock 覆盖层”专家模板库。

当前 `sql_generation` 和 `pyspark_generation` 已经能够调用模型并返回代码围栏，但它们主要依赖用户自然语言、
官方文档和专家模板。系统还不知道某个具体项目真实存在的表、字段、主键、CDC 规则、目录结构和既有代码风格，
因此生成结果仍可能使用泛化表名或自行假设字段。

项目最终形态采用类似本地代码工作区的模式：用户在桌面客户端选择一个本地文件夹，系统只读扫描项目文件，
建立本地索引，并把与当前问题相关的项目上下文交给代码生成器。完整文件夹选择、通用扫描、增量监听和本地
SQLite 索引现在实现还太早，但如果阶段 6 完全忽略这一最终方向，后续接入真实项目时会重写代码生成边界。

因此阶段 6 采用“现在固定接口、以后替换数据源”的方案：把 `retail_sales_demo` 建成一个真实目录结构的示例
工作区，代码生成只依赖统一 `WorkspaceContextBundle`；未来本地 SQLite Provider 输出相同契约，不修改
ChatService、Prompt 或模型网关。

本阶段仍然是顾问型 Agent，不连接 Databricks Workspace，不执行 SQL、PySpark 或 Notebook，不运行
Databricks CLI，不部署 Declarative Automation Bundles，也不写入用户选择的项目文件夹。

## 2. 阶段目标

1. 创建一个可由普通文件系统读取的 `retail_sales_demo` AWS 零售销售示例工作区。
2. 为项目背景、表结构、映射、业务规则、DDL、代码样例和 Bundle 配置建立严格清单。
3. 定义与具体存储无关的 Workspace Registry、选择器和上下文契约。
4. 让会话可选绑定不可变 `workspace_id`，并保持它与 `expert_profile` 相互独立。
5. 让 SQL、PySpark 和 Notebook 代码生成按需使用项目工作区上下文。
6. 新增 Python source 格式的 Databricks Notebook 草稿输出。
7. 保持 SQL 与 PySpark 输出简短，直接返回代码和必要注释，不恢复固定长篇章节。
8. 在 `model_calls` 和 Trace 1.6 中记录工作区版本、内容 Hash 和实际选中的相对文件。
9. 使用固定问题验证项目上下文选择和三类代码输出，不增加 LLM 分类或项目 Embedding 调用。
10. 为未来“选择本地文件夹 + 本地 SQLite 索引”保留 Provider 接口，但不提前实现完整工作区系统。

## 3. 已确认的产品决策

以下决策已由用户于 2026-07-17 确认，实施时不再作为开放问题：

1. 产品最终形态以用户选择的本地项目文件夹为项目事实来源，不采用“每次上传项目文件”的工作流。
2. 完整文件夹扫描、文件监听、通用解析和本地项目索引放到桌面客户端前的工作区接入阶段。
3. 阶段 6 现在创建一个真实文件夹形态的 `retail_sales_demo`，不创建只为测试存在的数据库假项目。
4. 示例工作区与未来用户工作区必须经过同一 `WorkspaceContextBundle` 接口进入代码生成。
5. 项目源码、DDL 和配置文件始终是项目事实来源；数据库中的索引只能是可删除、可重建的派生数据。
6. 最终项目派生索引优先放在本地 SQLite，而不是中央 PostgreSQL。
7. SQLite 文件最终放在应用本地数据目录，不写入用户 Git 仓库。
8. 阶段 6 不引入 SQLite；示例工作区直接从 Git 文件加载。
9. 当前 PostgreSQL 继续保存会话、消息、模型调用、官方知识库和专家模板。
10. PostgreSQL 不保存阶段 6 项目源码正文、DDL 正文或项目 Embedding。
11. `expert_profile` 表示顾问方法与模板层；`workspace_id` 表示具体项目事实，两者不能合并。
12. 第一版只有一个内置工作区 `retail_sales_demo`，没有任意本地路径注册 API。
13. 没有选择工作区时，SQL、PySpark 和 Notebook Prompt 仍可按用户消息生成通用草稿。
14. 选择工作区后，模型必须优先使用项目上下文中的真实表名和字段；信息不足时只用简短注释说明假设。
15. 项目上下文使用确定性文件选择，不新增 OpenAI Embedding、DeepSeek 调用、rerank 或 LangGraph。
16. SQL 和 PySpark 仍只校验 Markdown 代码围栏，不增加容易误报的运行时语法或字段强校验。
17. Notebook 第一版只生成 Python source 格式草稿，不生成 `.ipynb` JSON、DBC、HTML 或真实文件下载。
18. 不执行生成代码，不声称代码已编译、已运行、已通过 Databricks 验证或已产生性能结果。
19. 所有真实冒烟会话、消息、`model_calls` 和 Trace 必须保留，不执行验收数据清理。
20. README 不增加阶段 6 内部架构说明；没有新增启动命令时不修改 README。

## 4. 术语与职责

### 4.1 Expert Profile

`expert_profile` 决定使用哪些通用方法论和项目经验模板。例如：

```text
generic
retail_sales_demo
```

它回答的是“应该采用什么设计方法和检查清单”。

### 4.2 Workspace

`workspace_id` 标识一个具体项目工作区。阶段 6 只有：

```text
retail_sales_demo
```

它回答的是“这个项目真实有哪些表、字段、映射、规则和已有代码”。

### 4.3 Workspace Context

Workspace Context 是从工作区文件中确定性选择并渲染出的模型上下文。它只在当前模型调用中使用，不作为
Databricks 官方引用，也不进入 `messages.source_citations`。

### 4.4 权威边界

1. 用户本轮明确要求描述目标和希望发生的变更。
2. Workspace Context 对当前项目已有表、字段、配置和业务规则负责。
3. Databricks 官方 RAG 对产品能力、语法、限制和功能状态负责。
4. Expert Template 对设计方法、默认模式和检查清单负责。
5. 用户提出的新字段可以作为建议，但不得伪装成工作区中已经存在的字段。

不存在一个可以覆盖所有领域的简单总优先级。项目字段冲突时采用 Workspace；Databricks 功能事实冲突时采用
官方资料；专家模板只能提供默认建议。

## 5. 范围

### 5.1 包含

1. Git 内的 `retail_sales_demo` 示例工作区及严格项目清单。
2. 项目概览、16 张表的数据契约、源到目标映射、业务规则和三层 DDL。
3. 最小 `databricks.yml`、资源配置和已有 PySpark 风格样例。
4. Workspace Registry、确定性文件选择、token 预算和上下文渲染。
5. `sessions.workspace_id` 和 `model_calls` 工作区审计字段。
6. 内置工作区只读列表 API 和会话创建时的工作区校验。
7. `PromptSpec.use_workspace_context` 产品策略。
8. SQL、PySpark 和 Notebook 三类代码 Prompt。
9. Notebook Artifact 与 Trace 1.6。
10. 单元测试、集成测试、固定上下文评估和 DeepSeek 真实冒烟。

### 5.2 不包含

1. 桌面文件夹选择器、最近项目列表和项目切换界面。
2. 任意绝对路径注册、HTTP 文件上传或浏览器目录上传。
3. 递归扫描用户项目、`.gitignore` 解析、文件监听和增量重建。
4. 本地 SQLite、FTS5、SQLite 向量扩展或独立向量数据库。
5. 通用 SQL AST、Python AST、Notebook AST 或 Bundle Schema 解析。
6. 自动修改、创建、保存或下载项目文件。
7. 自动执行 SQL、PySpark、Notebook、Job、Pipeline、Bundle 或测试命令。
8. Databricks CLI、Databricks SDK、Databricks Connect 或 Workspace API。
9. SQLGlot、Spark Session、本地 Spark、Docker Spark 或 SQL Warehouse。
10. 代码自动修复、二次模型自检、LLM 意图分类、LLM rerank 或多 Agent 评审。
11. 将项目文件作为官方引用或专家模板保存。
12. 用户项目加密、团队共享、多用户权限和远程项目同步。

## 6. 总体架构

```text
examples/workspaces/retail_sales_demo
  -> WorkspaceRegistry 启动预检
  -> WorkspaceContextBuilder 确定性选择文件
  -> WorkspaceContextBundle
                                 +----------------------+
用户消息 -> PromptSpec ---------->| ChatContextService   |
会话 workspace_id --------------->|                      |
官方知识库 ----------------------->| official context     |
专家模板 ------------------------->| expert context       |
                                 +----------+-----------+
                                            |
                                            v
                                      ChatService
                                            |
                                            v
                                      ModelGateway
                                            |
                                            v
                              SQL / PySpark / Notebook Artifact
                                            |
                          +-----------------+------------------+
                          v                                    v
                    assistant message                 model_calls / Trace 1.6
```

Workspace Registry 只读取清单明确列出的受控文件。阶段 6 不递归发现未登记文件，不生成 Embedding，不写项目
索引表。

## 7. 示例工作区结构

```text
examples/
  workspaces/
    retail_sales_demo/
      .databricks-expert/
        project.yml
      databricks.yml
      resources/
        retail-sales.job.yml
      docs/
        project-overview.md
      contracts/
        tables.yml
        mappings.yml
        business-rules.yml
      sql/
        ddl/
          bronze.sql
          silver.sql
          gold.sql
      src/
        common/
          parameters.py
        bronze/
          ingest_pos_sales.py
```

该目录是一个可读的 Mock 项目，不是可部署承诺。`databricks.yml` 和资源文件用于提供项目结构上下文，阶段 6
不调用 Databricks CLI 验证或部署它们。

## 8. 项目清单契约

固定文件：

```text
.databricks-expert/project.yml
```

第一版格式：

```yaml
schema_version: 1
id: retail_sales_demo
display_name: AWS 零售销售分析 Demo
description: 基于 AWS 的零售销售 Databricks 模拟项目。
version: 1.0.0
cloud: aws
is_mock: true
default_context:
  sql_generation:
    - contract.tables
    - contract.mappings
  pyspark_generation:
    - contract.tables
    - contract.business_rules
    - code.parameters
  notebook_generation:
    - project.overview
    - contract.tables
    - code.parameters
sources:
  - id: contract.tables
    kind: schema
    path: contracts/tables.yml
    title: 项目表结构
    summary: Bronze、Silver、Gold 表和字段定义。
    prompt_names: [sql_generation, pyspark_generation, notebook_generation]
    tags: [表结构, 字段, bronze, silver, gold]
    always_include: false
```

### 8.1 顶层字段

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 第一版固定为整数 `1` |
| `id` | 小写英文、数字和下划线，最长 100 字符，全 Registry 唯一 |
| `display_name` | 中文显示名称，1 至 200 字符 |
| `description` | 中文说明，1 至 500 字符 |
| `version` | 严格 `MAJOR.MINOR.PATCH` |
| `cloud` | 第一版只允许 `aws` |
| `is_mock` | 内置零售工作区必须为 `true` |
| `default_context` | 三个代码 Prompt 到 source ID 数组的映射 |
| `sources` | 至少一个显式上下文来源 |

### 8.2 Source 字段

| 字段 | 规则 |
| --- | --- |
| `id` | 工作区内唯一，最长 100 字符 |
| `kind` | `project`、`schema`、`mapping`、`rule`、`ddl`、`code`、`bundle` |
| `path` | 工作区内相对 POSIX 路径，禁止绝对路径和 `..` |
| `title` | 中文显示标题 |
| `summary` | 用于确定性匹配的简短摘要 |
| `prompt_names` | 只允许三个代码 Prompt |
| `tags` | 1 至 30 个规范化关键词，可含中文业务词和表名 |
| `always_include` | 是否在匹配 Prompt 时优先加入上下文 |

未知字段直接失败。YAML 使用安全解析，不执行自定义标签、Jinja 或对象构造。

内置工作区固定登记以下 11 个 Source ID，后续测试、Trace 和评估统一使用这些 ID：

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

## 9. Workspace 领域类型

```python
class WorkspaceSourceKind(StrEnum):
    PROJECT = "project"
    SCHEMA = "schema"
    MAPPING = "mapping"
    RULE = "rule"
    DDL = "ddl"
    CODE = "code"
    BUNDLE = "bundle"


@dataclass(frozen=True, slots=True)
class WorkspaceSource:
    source_id: str
    kind: WorkspaceSourceKind
    title: str
    summary: str
    prompt_names: tuple[PromptName, ...]
    tags: tuple[str, ...]
    always_include: bool
    source_path: str
    content: str
    content_hash: str


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

工作区路径只在 Registry 内部使用，不进入领域 DTO、API、数据库审计或 Trace。

## 10. Mock 数据契约

### 10.1 表目录

`contracts/tables.yml` 定义以下 16 张逻辑表：

| 层 | 表 |
| --- | --- |
| Bronze | `bronze.pos_sales_raw` |
| Bronze | `bronze.customer_cdc_raw` |
| Bronze | `bronze.product_cdc_raw` |
| Bronze | `bronze.store_cdc_raw` |
| Bronze | `bronze.inventory_cdc_raw` |
| Bronze | `bronze.ecommerce_events_raw` |
| Silver | `silver.dim_customer` |
| Silver | `silver.dim_product` |
| Silver | `silver.dim_store` |
| Silver | `silver.fact_sales` |
| Silver | `silver.fact_inventory` |
| Silver | `silver.fact_customer_behavior` |
| Gold | `gold.daily_sales` |
| Gold | `gold.product_performance` |
| Gold | `gold.inventory_health` |
| Gold | `gold.customer_channel` |

每张表至少定义用途、字段名、Databricks SQL 类型、nullable、主键或业务键、分区或聚簇建议、来源和 PII
分类。金额统一使用 `DECIMAL`，事件时间统一使用 UTC `TIMESTAMP`，不使用真实个人数据。

### 10.2 必须覆盖的关键字段

1. POS：`business_date`、`store_id`、`transaction_id`、`line_id`、`product_id`、`quantity`、
   `gross_amount`、`discount_amount`、`net_amount`。
2. DMS：`_dms_op`、`_dms_commit_ts`、源业务键和摄取时间。
3. Kinesis：`event_id`、`event_type`、`event_ts`、`order_id`、`customer_id`、`channel` 和原始 payload。
4. Bronze 文件：`_ingest_ts`、`_source_file`、`_rescued_data`。
5. Silver 客户：受控 `customer_id`、脱敏联系方式、SCD 生效区间和 `is_current`。
6. Silver 销售事实：订单行粒度和明确金额口径。
7. Gold：四个阶段 5 已确认数据产品所需维度与指标。

### 10.3 映射与业务规则

`contracts/mappings.yml` 明确源字段到 Silver / Gold 字段的映射和转换说明；
`contracts/business-rules.yml` 至少包含：

1. AWS DMS `I/U/D` 处理和 `_dms_commit_ts` 去重顺序。
2. Kinesis `event_id` 幂等去重和迟到事件边界。
3. POS 文件重复、坏记录和 `_rescued_data` 处理。
4. 金额、退货、取消订单和渠道口径。
5. PII 在 Bronze、Silver、Gold 的可见边界。
6. 时区、业务日期和每日 07:30 Gold 可查询的 Mock SLA。

DDL 与 YAML 共同服务于模型：YAML 是机器可读项目契约，DDL 是人和模型可阅读的代码参考。测试必须检查二者
表名集合一致，避免长期漂移。

## 11. Registry 与安全边界

`WorkspaceRegistry.create_default()` 从固定产品目录 `examples/workspaces/` 加载立即子目录中的清单。启动预检：

1. 使用严格 Pydantic 模型和 `yaml.safe_load()` 校验清单。
2. 校验工作区 ID、版本、Source ID、Prompt 和默认映射。
3. 只读取清单显式列出的 UTF-8 文本文件。
4. 允许扩展名固定为 `.md`、`.yml`、`.yaml`、`.sql`、`.py`。
5. 单文件最大 256,000 bytes，超限直接失败。
6. `resolve()` 后必须仍位于工作区根目录内，拒绝绝对路径、`..` 和符号链接逃逸。
7. 拒绝 `.env`、凭据、证书、私钥、`.git`、`.venv`、`node_modules` 和二进制文件。
8. 规范化 CRLF 为 LF，API 与 Trace 只使用相对 POSIX 路径。
9. 对排序后的清单与全部 Source 正文计算稳定 `source_hash`。
10. 不访问 PostgreSQL、SQLite、OpenAI、DeepSeek、Databricks 或网络。

工作区内容发生兼容增加时升级 MINOR，业务含义改变时升级 MAJOR，文字或字段说明修正时升级 PATCH。Registry
记录 Hash，但阶段 6 不建立跨 Git 提交的版本数据库，因此版本升级由内容测试和代码评审约束。

## 12. 确定性上下文选择

### 12.1 产品常量

以下行为跨环境一致，定义为代码常量，不进入 `.env`：

```text
WORKSPACE_ROOT = examples/workspaces
WORKSPACE_SOURCE_MAX_BYTES = 256000
WORKSPACE_CONTEXT_TOP_K = 6
WORKSPACE_CONTEXT_MAX_TOKENS = 4000
```

### 12.2 候选过滤

只有 `source.prompt_names` 包含本次 Prompt 的文件进入候选。普通问答、知识问答、工作流、提案和自检在阶段 6
不读取 Workspace。

### 12.3 排序

选择器不调用模型和 Embedding，使用可测试的确定性规则：

1. `always_include=true` 的来源使用 `reason=required`。
2. Query 中出现完整 tag、表名、字段名、Source 标题或摘要关键词时形成 lexical score。
3. 对相同分数按 `source_id` 排序，结果必须稳定。
4. 没有正分候选时使用 `default_context[prompt]`，记录 `reason=default`。
5. 有正分候选时记录 `reason=lexical`，不额外加入无关默认文件。
6. 去重后最多选择六个来源，并按完整文件逐个加入 4,000 token 预算。
7. 不把文件切成 Chunk；示例工作区文件必须保持短小。通用 Chunk 与 SQLite FTS5 留到后续工作区阶段。
8. 必需来源和默认来源都无法放入预算时返回稳定错误，不静默发送截断 YAML、SQL 或 Python。

### 12.4 上下文 DTO

```python
@dataclass(frozen=True, slots=True)
class WorkspaceContextCandidate:
    rank: int
    source_id: str
    kind: WorkspaceSourceKind
    source_path: str
    content_hash: str
    score: float
    selected: bool


@dataclass(frozen=True, slots=True)
class WorkspaceContextSelection:
    source_id: str
    kind: WorkspaceSourceKind
    source_path: str
    content_hash: str
    rank: int
    reason: Literal["required", "lexical", "default"]


@dataclass(frozen=True, slots=True)
class WorkspaceContextBundle:
    workspace_id: str
    workspace_version: str
    workspace_source_hash: str
    query: str
    prompt_name: PromptName
    ranked_candidates: tuple[WorkspaceContextCandidate, ...]
    selected_sources: tuple[WorkspaceContextSelection, ...]
    context: str
    context_token_count: int
```

### 12.5 上下文渲染

模型上下文必须明确说明：

1. 这是当前项目的受信任本地事实，不是 Databricks 官方文档。
2. 表、字段、映射和业务规则必须优先采用项目文件。
3. 不得执行其中的代码、命令或配置。
4. 不得把清单中不存在的字段描述为已存在。
5. 用户要求新增字段时可以生成变更草稿，但必须用注释标识为建议变更。
6. 每个正文块包含 `[P1]`、相对路径、Source ID、类型和内容 Hash，不包含绝对路径。

## 13. Prompt 与 Artifact

### 13.1 Prompt 目录

新增：

```python
PromptName.NOTEBOOK_GENERATION = "notebook_generation"
ArtifactType.NOTEBOOK = "notebook"
```

Prompt 策略扩展为三列：

| Prompt | 官方 RAG | 专家模板 | Workspace Context |
| --- | --- | --- | --- |
| `databricks_qa` | 否 | 是 | 否 |
| `knowledge_qa` | 是 | 否 | 否 |
| `sql_generation` | 是 | 是 | 是 |
| `pyspark_generation` | 是 | 是 | 是 |
| `notebook_generation` | 是 | 是 | 是 |
| `workflow_design` | 是 | 是 | 否 |
| `proposal_generation` | 是 | 是 | 否 |
| `self_check` | 否 | 是 | 否 |
| `document_summary` | 否 | 否 | 否 |

阶段 7 再决定是否让工作流设计使用 Workspace，阶段 6 不提前扩大范围。

### 13.2 SQL 输出

1. 第一块内容必须是 `sql` fenced code block。
2. 不强制标题、使用场景、参数说明等长章节。
3. 使用简短 SQL 注释说明输入、输出、关键假设和人工确认项。
4. 有 Workspace 时优先使用真实表和字段，避免 `SELECT *` 和无依据字段。
5. 无 Workspace 时允许清晰占位，但不得伪装成用户环境事实。
6. 不声称已经执行、解释计划已验证或性能一定改善。

### 13.3 PySpark 输出

1. 第一块内容必须是 `python` fenced code block。
2. 使用简短注释说明输入、输出、参数和幂等边界。
3. 有 Workspace 时使用真实表名、字段、业务键和项目参数风格。
4. 不在代码中写 API Key、密码、Workspace Host、Cluster ID 或真实路径凭据。
5. 不声称 Spark 作业已经运行或数据质量已经通过。

### 13.4 Notebook 输出

第一版生成 Git 友好的 Python source 格式 Notebook 草稿：

```python
# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # Notebook 标题

# COMMAND ----------
# Python 代码
```

Artifact 仍作为 Markdown 中的 `python` fenced code block返回，不写入 `.py` 文件。Prompt 要求首行 marker 和
cell separator，但运行时 Artifact Parser 不新增 Notebook 深度解析或阻断逻辑；格式正确性由测试和真实验收
检查。

### 13.5 专家模板扩展

增加一个简短的 `code.databricks_notebook_python` 通用代码模式，并把 `notebook_generation` 加入相关 PySpark
代码模板的 `prompt_names`。`generic` 与 `retail_sales_demo` Profile 都提供 Notebook 默认模板。模板同步仍使用
阶段 5 原子同步流程，数量从 37 增加到 38 左右。

## 14. 会话与 API

### 14.1 创建会话

`POST /api/chat/sessions` 增加可选字段：

```json
{
  "title": "零售每日销售 SQL",
  "expert_profile": "retail_sales_demo",
  "workspace_id": "retail_sales_demo"
}
```

`workspace_id` 可空。未知 ID 返回 HTTP 422：

```json
{
  "code": "workspace_not_found",
  "message": "项目工作区不存在。",
  "details": null
}
```

Session 创建后不提供修改 `workspace_id` 的 API。历史 Session 迁移为 NULL。

### 14.2 工作区列表

新增只读：

```text
GET /api/workspaces
```

返回 ID、名称、说明、版本、cloud 和 Mock 标识，不返回工作区根路径、Source 正文或文件绝对路径。不提供详情、
注册、刷新、同步、删除或打开路径 API。

### 14.3 消息 API

继续使用：

```text
POST /api/chat/sessions/{session_id}/messages
```

请求不增加路径、项目文件、Source ID 或表结构字段。用户通过 `prompt` 选择：

```text
sql_generation
pyspark_generation
notebook_generation
```

成功响应继续返回 Artifact 元数据和 assistant message，不返回内部 Workspace 候选或选择详情。

## 15. PostgreSQL 数据设计

新增 Alembic 迁移 `0008_workspace_code_generation`，不新增项目内容表。

迁移同时更新现有 `messages` 表的 `ck_messages_artifact_type`，把 `notebook` 加入允许值；否则 Notebook
assistant message 无法写入 PostgreSQL。downgrade 把 Notebook message 的 Artifact 元数据映射为 `pyspark`，
保留消息正文和记录，再恢复阶段 5 原约束。

### 15.1 `sessions`

```text
workspace_id VARCHAR(100) NULL
```

历史记录保持 NULL。值来自启动 Registry，不使用数据库枚举或外键，因为阶段 6 工作区唯一真源是 Git 文件。

### 15.2 `model_calls`

新增：

```text
workspace_id VARCHAR(100) NULL
workspace_version VARCHAR(20) NULL
workspace_source_hash VARCHAR(64) NULL
workspace_context_selections JSONB NULL
```

历史记录保持 NULL。阶段 6 新调用始终保存会话 `workspace_id`；只有实际使用 Workspace Context 时写 version、
Hash 和选择数组。未使用时 `workspace_context_selections` 写空数组。

每个选择元素固定包含：

```json
{
  "source_id": "contract.tables",
  "kind": "schema",
  "source_path": "contracts/tables.yml",
  "content_hash": "64位sha256",
  "rank": 1,
  "reason": "lexical"
}
```

数据库不保存 Source 正文、绝对路径或项目 Embedding。实际发送给模型的完整内容只存在于模型请求和开发期本地
Trace 中。

## 16. ChatService 数据流

```text
读取 session.expert_profile 与 session.workspace_id
-> 解析 PromptSpec
-> 保存 user message
-> 按 PromptSpec 检查官方、专家和 Workspace 三类上下文需求
-> 官方 / 专家需要时只生成一次查询 Embedding
-> Workspace 使用本地确定性选择，不生成 Embedding
-> 组装 system、历史、专家、官方、Workspace、当前 user
-> ModelGateway 执行请求级模型选择与 fallback
-> 每次尝试写 model_calls 与 Trace 1.6
-> Markdown Artifact 现有结构校验
-> 保存 assistant message 和官方 source_citations
```

固定消息顺序：

```text
system Prompt
-> 会话历史
-> 专家模板上下文
-> Databricks 官方资料上下文
-> Workspace 项目上下文
-> 当前用户消息
```

Workspace 放在当前用户消息之前，使项目事实靠近本轮需求；system Prompt 和 Workspace 自身仍必须明确各领域的
权威边界。fallback 复用完全相同的消息，不重复读取文件、检索或生成 Embedding。

如果 Prompt 支持 Workspace 但 Session 没有 `workspace_id`，继续通用代码生成，不报错。如果 Session 已绑定
Workspace，但上下文无法构建，则在调用聊天模型前返回错误；已保存 user message 保留。

## 17. Trace 1.6 与审计

Trace 从 1.5 升级到 1.6，保持 OpenAI Chat Completions 超集：

```json
{
  "schema_version": "1.6",
  "protocol": "openai.chat.completions",
  "trace": {
    "workspace_id": "retail_sales_demo"
  },
  "retrieval": {},
  "expert_templates": {},
  "workspace_context": {
    "status": "selected",
    "workspace_version": "1.0.0",
    "workspace_source_hash": "64位sha256",
    "latency_ms": 4,
    "context_token_count": 2780,
    "candidates": [
      {
        "rank": 1,
        "source_id": "contract.tables",
        "kind": "schema",
        "source_path": "contracts/tables.yml",
        "content_hash": "64位sha256",
        "score": 8.0,
        "selected": true
      }
    ],
    "selected": [
      {
        "source_id": "contract.tables",
        "kind": "schema",
        "source_path": "contracts/tables.yml",
        "content_hash": "64位sha256",
        "rank": 1,
        "reason": "lexical"
      }
    ]
  },
  "request": {},
  "response": {},
  "error": null
}
```

`request.messages` 保存实际发送的完整 Mock 项目上下文。Trace 不得包含工作区绝对路径、API Key、密码或真实
PII。未来读取真实项目时，完整模型输入日志会包含命中的项目代码，因此桌面版本必须继续保留本地开关、忽略
规则和用户提示；该隐私控制不在阶段 6 用 Mock 数据时展开。

模型调用前发生的 Registry 或上下文错误没有 `model_call_id`，只写结构化应用日志，不伪造模型调用记录。

## 18. 错误边界

| Code | HTTP | 场景 |
| --- | ---: | --- |
| `workspace_not_found` | 422 | 创建会话时工作区未注册 |
| `workspace_context_not_found` | 404 | 已绑定工作区但没有来源能进入上下文预算 |
| `workspace_registry_invalid` | 启动失败 | 清单、路径、Hash、默认来源或文件编码无效 |

现有官方索引、专家索引、Embedding、模型网关和 Artifact 错误保持原语义。Workspace 错误不得触发模型 fallback。

## 19. 运行时代码校验边界

阶段 6 不增加 SQL AST、Python AST、Spark 分析器或字段级阻断校验，原因是：

1. Agent 不执行代码，无法确认用户实际 Runtime、Catalog 权限和数据状态。
2. 仅靠静态规则很容易把有效 Databricks SQL、Notebook magic 或动态表名误判为错误。
3. 用户已确认 SQL 与 PySpark 应保持直接、简短，不需要人为制造长篇验证报告。

运行时继续只校验 Markdown Artifact 的首个 fenced code block 和语言。质量通过 Prompt 约束、项目上下文、固定
测试、真实模型冒烟和人工审查保证。Notebook marker、关键表名和禁止伪造执行结果属于验收检查，不作为生产 API
的额外拒绝条件。

## 20. 测试与评估

### 20.1 单元测试

1. 清单严格字段、SemVer、Source ID、Prompt、默认映射和 Hash。
2. 绝对路径、`..`、符号链接逃逸、禁止扩展名、超大文件和非 UTF-8 拒绝。
3. 16 张表、关键字段、业务键、映射、规则和 DDL 表名集合一致。
4. Workspace Source 过滤、tag 匹配、稳定排序、默认来源、去重和 4,000 token 预算。
5. 无 Workspace 时不构建上下文，有 Workspace 且非代码 Prompt 时也不构建。
6. SQL、PySpark、Notebook Prompt 与 Artifact 类型和模板版本。
7. Notebook 输出的 source marker 与 cell separator 验收样例。
8. 演示数据生成器为新增 Notebook Artifact 生成合法 Python source 围栏。
9. Workspace 审计 payload 和 Trace 1.6 序列化。

### 20.2 集成测试

1. Alembic 0008 upgrade / downgrade，历史值保持 NULL。
2. 创建 generic 无 Workspace 会话和 retail Workspace 会话。
3. 未知 Workspace 422，Workspace 创建后不可修改。
4. `GET /api/workspaces` 不泄露路径和正文。
5. 三类代码 Prompt 的上下文顺序、官方 / 专家 Embedding 复用和 Workspace 无 Embedding。
6. fallback 每次尝试保存相同 Workspace 版本、Hash 和选择数组。
7. assistant `source_citations` 仍只来自官方知识库。
8. 普通问答、知识问答、工作流和提案不误用 Workspace Context。

### 20.3 固定上下文评估

新增 `tests/evals/workspace_context.yml`，至少 18 条中文问题，覆盖：

1. 每日销售 Gold SQL。
2. 商品表现聚合 SQL。
3. 库存健康 SQL。
4. 客户渠道 SQL。
5. DMS 客户 CDC PySpark。
6. POS Auto Loader PySpark。
7. Kinesis 电商事件 Notebook。
8. PII 脱敏和 SCD 代码。

指标固定为：

1. `Recall@4 >= 90%`。
2. Source 选择必须属于请求 Prompt。
3. 默认选择必须稳定且无重复。
4. 无 Workspace 或非代码 Prompt 的上下文选择数必须为 0。

### 20.4 真实冒烟

使用 `deepseek-v4-flash`、`expert_profile=retail_sales_demo`、`workspace_id=retail_sales_demo` 完成：

1. 生成 `gold.daily_sales` Databricks SQL。
2. 生成 DMS 客户 CDC 到 `silver.dim_customer` 的 PySpark。
3. 生成 Kinesis 到 `bronze.ecommerce_events_raw` 的 Python source Notebook 草稿。

人工核对实际表名、字段名、业务键、Notebook marker、代码注释、官方引用、专家模板选择、Workspace Source
选择和 Trace 1.6。不得清理三个验收 Session、消息、model_calls 或 Trace。

## 21. 最终本地 SQLite 方向

该部分是后续架构约束，不是阶段 6 实现任务。

最终桌面客户端选择目录后，应用建立：

```text
%LOCALAPPDATA%\DatabricksZhExpert\workspaces\<workspace_hash>\index.db
```

SQLite 预计保存：

1. 工作区 ID、规范化根路径 Hash 和最近索引时间。
2. 文件相对路径、类型、大小、mtime 和内容 Hash。
3. 解析出的表、字段、函数、类、依赖关系和业务术语。
4. 检索 Chunk、FTS5 全文索引和索引版本。
5. 可选向量索引的抽象引用；具体 SQLite 向量方案后续评估。

SQLite 可以随时删除并从源文件重建，不是项目事实来源。项目文件夹只保存用户源码和可提交 Git 的
`.databricks-expert/project.yml`；索引数据库默认不写进项目目录。

未来实现 `SQLiteWorkspaceContextProvider` 时，必须返回阶段 6 已固定的 `WorkspaceContextBundle`。ChatService
不关心上下文来自内置 Registry 还是本地 SQLite。

## 22. 质量约束

1. Python 固定 3.12.10，依赖继续由项目内 uv 管理。
2. 阶段 6 不新增第三方依赖、环境变量、Docker 服务或数据库实例。
3. Workspace 限制、token 预算和固定目录是跨环境产品行为，定义为代码常量。
4. 所有新增文档、Mock 业务说明、API 描述和错误消息使用中文。
5. 代码标识符、Prompt ID、Workspace ID、字段名、表名和命令使用英文。
6. Mock 内容不得包含真实姓名、邮箱、电话、凭据、客户名或运行结果。
7. README 没有新增启动步骤时保持不变。
8. 修改 Python 后运行 Ruff、Pyright/Pylance 和聚焦 pytest。
9. 数据模型变更通过 Alembic upgrade、downgrade、current 和 check。
10. 阶段收尾运行完整 pytest 与覆盖率，覆盖率不得低于当前 80% 门禁。
11. 不降低阶段 4 Recall@5 或阶段 5 Recall@3 评估门禁。
12. 所有真实验收数据与 Trace 必须保留。

## 23. 完成定义

阶段 6 只有同时满足以下条件才完成：

1. `retail_sales_demo` 以真实文件夹结构存在并通过严格启动预检。
2. 16 张表、字段、映射、业务规则和 DDL 一致且明确标记为 Mock。
3. Workspace 与 Expert Profile 在领域、API 和数据库中保持独立。
4. 历史 Session 无 Workspace 仍可正常读取和聊天。
5. SQL、PySpark 和 Notebook Prompt 均可在有或无 Workspace 时工作。
6. 有 Workspace 时模型请求包含相关项目文件，而不是整个项目目录。
7. Workspace 选择不调用模型或 Embedding，固定评估 Recall@4 >= 90%。
8. SQL 与 PySpark 保持直接代码输出，不增加固定长篇章节或严格运行时语法拦截。
9. Notebook 生成符合 Python source 草稿格式，并明确未创建 Databricks Notebook。
10. `model_calls` 可恢复 Workspace ID、版本、Hash、相对路径和选择原因。
11. Trace 1.6 包含完整实际 Workspace Context，但不包含绝对路径和凭据。
12. 三次 DeepSeek 真实冒烟成功，所有验收数据保留。
13. Ruff、Pyright/Pylance、pytest、覆盖率和 Alembic 检查全部通过。
14. 本阶段没有 SQLite、任意目录扫描、文件上传、代码执行或 Databricks 连接。

## 24. 待确认事项

当前没有待确认产品问题。实现中如果发现示例工作区无法在 4,000 token 内提供足够字段上下文，应先拆短
项目文件或调整清单，不得静默引入向量数据库、SQLite、LLM 文件选择或全目录上下文。

## 25. 参考资料

1. [Databricks：Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles)
2. [Databricks：开发 Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/work-tasks)
3. [Databricks：Notebook 格式](https://docs.databricks.com/aws/en/notebooks/notebook-format)
4. [Databricks：导入和导出 Notebook](https://docs.databricks.com/aws/en/notebooks/notebook-export-import)
