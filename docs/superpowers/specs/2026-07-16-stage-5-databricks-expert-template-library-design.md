# 阶段 5：Databricks 专家模板库设计

## 1. 背景

阶段 1 至阶段 4 已完成 FastAPI 后端、会话持久化、模型网关、Prompt Registry、Markdown
Artifact，以及 Databricks 官方 Docs 与 API 文档的全量 RAG。系统现在已经能够回答官方知识问题、生成
代码和方案草稿，并保存模型调用、引用与检索 Trace。

阶段 4 解决的是“官方事实从哪里来”，但官方文档不会替项目团队完成业务假设、架构取舍、交付结构、
检查清单和代码模式选择。仅依赖官方 RAG 时，模型仍然容易输出正确但泛化的说明，缺少真实项目交付所需的
决策上下文。

阶段 5 建设一套受 Git 管理、可版本化、可检索、可审计的 Databricks 专家模板库。第一版采用
“通用核心层 + AWS 零售销售项目覆盖层”。项目覆盖层提供内部设计基线，不得冒充真实客户案例、官方结论或
已经验证的性能数据。

本阶段仍然是顾问型 Agent，不连接或操作 Databricks 与 AWS，不执行 SQL、PySpark、Notebook、Job、
Pipeline 或基础设施命令。

## 2. 阶段目标

1. 在当前 Git 仓库内建立 Markdown + YAML Front Matter 专家资产格式。
2. 提供通用核心层和一个贯穿全流程的 `retail_sales_demo` AWS 零售项目覆盖层。
3. 建立可扩展的会话级 `expert_profile`，默认使用 `generic`。
4. 将专家模板正文、版本、Chunk、Embedding 和同步状态保存到独立 PostgreSQL 表。
5. 保持专家模板与 `kb_documents`、`kb_chunks` 官方知识数据完全分离。
6. 根据 Prompt、Profile、标签、向量和全文结果自动选择专家模板，不要求用户传模板 ID。
7. 在代码与方案生成场景中组合官方事实与专家模板，并保持两类上下文的权威边界。
8. 在 `model_calls` 和 Trace 1.5 中记录实际选择的 Profile、模板、版本、排名和继承关系。
9. 使用固定评估集验证模板选择 `Recall@3 >= 90%`，跨 Profile 误用必须为 0。
10. 建立约 35 个短而具体的专家资产，使 Demo 输出接近真实项目交付物。

## 3. 已确认的产品决策

以下决策已由用户于 2026-07-16 确认，实施时不再作为开放问题：

1. 模板库采用“通用核心层 + 项目经验覆盖层”。
2. 第一版项目经验来自内部零售销售项目基线，不声称具有真实客户来源。
3. 项目覆盖层使用一个贯穿所有相关阶段的 AWS 零售销售项目，不创建多个互不关联的小案例。
4. 数据源同时包含 S3 日批、RDS PostgreSQL CDC 和 Kinesis 实时事件流。
5. RDS CDC 基准架构固定为 `RDS PostgreSQL -> AWS DMS -> S3 Parquet -> Auto Loader`。
6. 不采用处于 Preview 或 Experimental 状态的 Databricks 或 AWS 功能。
7. Medallion 转换主框架使用 Lakeflow Spark Declarative Pipelines 的稳定能力。
8. 零售销售项目采用平衡型 SLA，不追求秒级实时。
9. Gold 层覆盖每日销售、商品表现、库存健康、客户与渠道四个数据产品。
10. 零售销售项目包含示例 PII 字段和 Unity Catalog 权限治理场景。
11. 用户不选择具体模板；系统自动检索，模板选择必须进入日志和数据库审计。
12. 会话创建时选择可选 `expert_profile`，默认值为 `generic`，会话创建后不可修改。
13. 同一 Git 仓库、同一 PostgreSQL 实例和当前非 `public` Schema 中增加独立专家模板表。
14. 模板源文件使用单文件 Markdown + YAML Front Matter。
15. 覆盖层通过 `extends` 显式扩展通用模板，不执行隐式章节覆盖或 Markdown 深度合并。
16. 专家资产分为 `blueprint`、`decision_guide`、`code_pattern`、`checklist`、`deliverable` 五类。
17. 第一版建设约 35 个高质量资产；数量不是验收 KPI，不为凑数保留重复内容。
18. Git 文件是模板唯一真源；数据库只是可重建的检索和审计派生数据。
19. `messages.source_citations` 继续只代表官方来源，项目模板不进入官方引用。
20. 聊天响应不返回模板选择详情；开发者通过数据库和本地 Trace 查看。
21. Profile 由仓库内 YAML 注册，不写成 Python 枚举或环境变量。
22. 不新增模型调用进行意图分类、模板选择或 rerank。
23. 模板索引不就绪时不静默降级，返回稳定错误且不调用聊天模型。
24. Agent Skills 不进入阶段 5 第一版。
25. 不清理已有会话、消息、模型调用、真实验收 Trace 或知识库数据。

## 4. 零售销售项目定义

### 4.1 项目标识

```text
Profile ID: retail_sales_demo
项目名称：AWS 零售销售分析平台
数据平台：Databricks on AWS
性质：内部项目基线，不包含真实企业、客户、个人或商业数据
```

### 4.2 数据源

| 来源 | 项目假设 | 到达方式 | 主要用途 |
| --- | --- | --- | --- |
| Amazon S3 | 门店 POS 日销售文件、供应商商品文件 | 每日批处理 | 门店销售与商品主数据补充 |
| Amazon RDS for PostgreSQL | 客户、商品、门店、库存主数据 | AWS DMS CDC 写入 S3 Parquet | 主数据增量与库存状态 |
| Amazon Kinesis Data Streams | 电商订单、支付状态、用户行为事件 | Structured Streaming | 近实时订单与渠道分析 |

站外 AWS 服务只作为方案背景和模板内容，不由本项目代码连接、创建或验证。

### 4.3 处理架构

```text
S3 日批文件 -----------------------> Auto Loader -----------+
RDS PostgreSQL -> AWS DMS -> S3 Parquet -> Auto Loader ----+--> Lakeflow Pipelines
Kinesis Data Streams --------------> Structured Streaming --+         |
                                                                      v
                                                           Bronze / Silver / Gold
                                                                      |
                                                                      v
                                                       Lakeflow Jobs 调度与监控
```

所有目标表使用 Delta 表并由 Unity Catalog 管理。模板可以给出代码、表结构和配置草稿，但不得声称已经创建
Catalog、Schema、Table、Pipeline 或 Job。

### 4.4 基线 SLA

| 工作负载 | 目标 |
| --- | --- |
| Kinesis 电商事件 | 端到端延迟不超过 5 分钟 |
| RDS CDC | 进入 Bronze 层不超过 15 分钟 |
| 门店日批 | 每日 05:00 到达，07:00 前完成 Gold 更新 |
| Gold 报表 | 每日 07:30 前可查询 |
| 核心任务 | 基线月度成功率目标 99.5% |

这些数字只属于 `retail_sales_demo` 的项目假设。通用模板不得把它们描述为 Databricks 推荐值，用户在
本轮请求中给出的 SLA 可以覆盖这些默认值。

### 4.5 Gold 数据产品

1. 每日销售分析：按日期、门店、渠道和商品统计销售额、订单量与客单价。
2. 商品表现分析：销量、退货率、折扣影响和品类排名。
3. 库存健康分析：当前库存、缺货风险和库存周转。
4. 客户与渠道分析：新老客户、线上转化漏斗和渠道贡献。

阶段 5 只沉淀数据产品结构、字段假设、质量检查和交付模板，不实现 BI Dashboard。

### 4.6 PII 与权限

示例客户数据可以包含虚构姓名、邮箱、手机号和会员等级。治理边界固定为：

1. Bronze 原始客户数据只允许数据工程角色访问。
2. Silver 对联系方式进行标准化和脱敏，只保留受控关联标识。
3. Gold 不暴露原始姓名、邮箱、手机号或地址。
4. 数据工程、分析师、营销、财务和审计角色使用不同最小权限。
5. 所有示例值必须明显为虚构数据，不出现真实姓名、邮箱、电话号码或凭据。

## 5. 范围

### 5.1 包含

1. 同仓库的 Profile 清单和 37 个左右的中文专家资产。
2. YAML Front Matter 严格解析、Markdown 校验、继承校验和版本校验。
3. 共享 Markdown Chunk、Embedding、全文检索和 RRF 基础能力。
4. `expert_templates`、`expert_template_chunks`、`expert_template_sync_runs` 三张表。
5. `sessions.expert_profile` 和 `model_calls` 专家模板审计字段。
6. 显式增量同步、索引状态和固定检索评估 CLI。
7. Profile、模板元数据和专家索引状态只读 API。
8. Prompt 级官方 RAG 与专家模板检索策略。
9. ChatService 上下文组装、官方引用保存和 Trace 1.5。
10. 自动测试、固定评估、真实模型冒烟和保留验收数据。

### 5.2 不包含

1. 用户上传模板、在线模板编辑器、数据库直接编辑和热更新。
2. 独立 Git 仓库、远程模板市场、Git submodule 或外部内容服务。
3. Databricks Agent Skills、社区博客、客户资料或未标明来源的项目案例。
4. Preview、Experimental 或需要申请加入预览的功能。
5. LLM 意图分类、LLM rerank、LangGraph、反馈学习和自动模板生成。
6. 用户在消息请求中传递 `template_id`、覆盖模板正文或修改系统 Prompt。
7. 模板内容执行、SQL 验证、PySpark 运行、AWS 或 Databricks API 调用。
8. Terraform、Databricks Asset Bundles 或 CI/CD 的实际部署。
9. Word、PDF、Notebook 文件导出和 BI Dashboard。
10. 真实价格、性能基准、客户名称、SLA 承诺或运行结果。

## 6. 专家资产业务类型

### 6.1 Profile

```python
@dataclass(frozen=True, slots=True)
class ExpertProfile:
    id: str
    display_name: str
    description: str
    cloud: str
    layers: tuple[str, ...]
    prompt_defaults: Mapping[PromptName, tuple[str, ...]]
    is_default: bool
```

第一版固定两个文件配置的 Profile：

| ID | 层 | Cloud | 默认 |
| --- | --- | --- | --- |
| `generic` | `core` | `neutral` | 是 |
| `retail_sales_demo` | `core`, `retail_sales_demo` | `aws` | 否 |

Profile ID 是动态注册的受控字符串，不创建 Python `StrEnum`。`generic` 是跨环境一致的产品默认值，不进入
`.env`。

### 6.2 资产类型

```python
class ExpertTemplateKind(StrEnum):
    BLUEPRINT = "blueprint"
    DECISION_GUIDE = "decision_guide"
    CODE_PATTERN = "code_pattern"
    CHECKLIST = "checklist"
    DELIVERABLE = "deliverable"
```

### 6.3 业务分类

```python
class ExpertTemplateCategory(StrEnum):
    INGESTION = "ingestion"
    MEDALLION = "medallion"
    PIPELINE = "pipeline"
    WORKFLOW = "workflow"
    GOVERNANCE = "governance"
    DATA_QUALITY = "data_quality"
    SQL = "sql"
    PYSPARK = "pyspark"
    PERFORMANCE = "performance"
    COST = "cost"
    DELIVERY = "delivery"
```

`kind` 表示资产形式，`category` 表示 Databricks 业务领域。两者不可合并为同一个字段。

## 7. 文件结构

```text
knowledge/
  expert_templates/
    profiles.yml
    core/
      blueprints/
      decision_guides/
      code_patterns/
      checklists/
      deliverables/
    overlays/
      retail_sales_demo/
```

运行时代码位于独立包：

```text
src/databricks_zh_expert/
  expert_templates/
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
    markdown.py
    hybrid.py
```

`search` 只保存官方 RAG 和专家模板共同需要的确定性 Markdown Chunk、词法查询和 RRF 算法，不理解
Profile、官方 URL、引用或聊天。

## 8. Markdown 与 Front Matter 契约

### 8.1 单文件格式

```markdown
---
id: medallion.standard
name: 通用 Medallion 分层设计
summary: 定义 Bronze、Silver、Gold 的职责、输入输出和质量边界。
version: 1.0.0
kind: blueprint
category: medallion
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
tags:
  - bronze
  - silver
  - gold
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse/medallion
---

# 通用 Medallion 分层设计

## 适用场景

正文。
```

### 8.2 字段约束

| 字段 | 规则 |
| --- | --- |
| `id` | 小写英文、数字、点和下划线组成，最长 100 字符，全库唯一业务 ID |
| `name` | 中文显示名称，1 至 200 字符 |
| `summary` | 用于列表和检索的中文摘要，1 至 500 字符 |
| `version` | 严格 `MAJOR.MINOR.PATCH` |
| `kind` | 五种 `ExpertTemplateKind` 之一 |
| `category` | 固定业务分类之一 |
| `layer` | `core` 或已注册覆盖层 ID |
| `profile` | core 必须为空，覆盖层必须等于已注册 Profile ID |
| `cloud` | `neutral` 或 `aws`；第一版不接受 Azure、GCP |
| `prompt_names` | 至少一个已注册且可用的 `PromptName` |
| `tags` | 1 至 20 个规范化标签，单项最长 50 字符 |
| `extends` | 可空；只能引用 core 模板 ID，禁止循环和多级覆盖层继承 |
| `official_refs` | 可空 HTTPS URL 列表，只作为维护线索，不进入消息官方引用 |

未知字段直接报错。YAML 使用 `yaml.safe_load()`，不执行自定义标签、对象构造或模板表达式。

### 8.3 Markdown 约束

1. 文件必须使用 UTF-8 和 LF；加载时统一换行符。
2. YAML 结束后正文不能为空，最大 100,000 字符。
3. 正文必须有且只有一个 H1，且 H1 必须等于 `name`。
4. 禁止原始 HTML、Jinja 表达式和嵌套 Front Matter。
5. `code_pattern` 必须至少包含一个与类别匹配的 `sql` 或 `python` fenced code block。
6. 其他资产必须包含“适用场景”和至少一个决策、步骤、检查或交付章节。
7. 模板是提供给模型的参考数据，不做运行时变量替换或 Jinja 渲染。

### 8.4 内容与版本

1. 同一 `id + version` 的规范化内容 Hash 发生变化时，同步失败。
2. 内容变化必须升级 SemVer；修正文案使用 PATCH，兼容增加使用 MINOR，改变业务含义使用 MAJOR。
3. 新版本发布后，旧版本标记 inactive，但正文和 Chunk 保留用于历史审计。
4. Git 中删除当前模板后，下一次完整成功同步立即将数据库当前版本标记 inactive。
5. Git 同步不是网络目录发现，不使用阶段 4 的“两次缺失再禁用”规则。

## 9. Profile 清单

`profiles.yml` 使用严格结构：

```yaml
version: 1
profiles:
  - id: generic
    display_name: 通用 Databricks 顾问
    description: 只使用通用核心专家模板。
    cloud: neutral
    layers: [core]
    default: true
    prompt_defaults:
      databricks_qa: [medallion.standard]
      sql_generation: [code.delta_merge_sql]
  - id: retail_sales_demo
    display_name: AWS 零售销售 Demo
    description: 使用通用核心层和 AWS 零售销售项目覆盖层。
    cloud: aws
    layers: [core, retail_sales_demo]
    default: false
    prompt_defaults:
      workflow_design: [retail.end_to_end_architecture]
      proposal_generation: [retail.project_context]
```

完整文件必须为六个专家启用 Prompt 提供合理默认映射；只有启用专家模板的 Prompt 强制要求默认值。
清单只能有一个默认 Profile，且必须包含 `generic`。

## 10. 初始专家资产目录

### 10.1 通用核心层

| ID | Kind | Category | 作用 |
| --- | --- | --- | --- |
| `ingestion.s3_auto_loader` | blueprint | ingestion | S3 文件增量摄取 |
| `ingestion.dms_s3_cdc` | blueprint | ingestion | DMS CDC 到 S3 Parquet |
| `ingestion.kinesis_streaming` | blueprint | ingestion | Kinesis 流式摄取 |
| `medallion.standard` | blueprint | medallion | 通用 Bronze、Silver、Gold 边界 |
| `pipeline.lakeflow_sdp` | blueprint | pipeline | Lakeflow 声明式管道 |
| `workflow.lakeflow_jobs` | blueprint | workflow | Job 依赖、重试和调度 |
| `governance.unity_catalog` | blueprint | governance | Catalog、Schema 与权限层级 |
| `governance.pii_protection` | blueprint | governance | PII 分类、脱敏和访问边界 |
| `decision.ingestion_mode` | decision_guide | ingestion | 批处理、CDC、流处理选择 |
| `decision.pipeline_dataset_type` | decision_guide | pipeline | 流表与物化视图选择 |
| `decision.scd_type` | decision_guide | medallion | SCD Type 1 与 Type 2 选择 |
| `decision.incremental_replay_backfill` | decision_guide | workflow | 增量、重放和回填策略 |
| `code.autoloader_pyspark` | code_pattern | pyspark | 精简 Auto Loader PySpark 模式 |
| `code.dms_cdc_apply_pyspark` | code_pattern | pyspark | DMS CDC 解析与应用模式 |
| `code.kinesis_pyspark` | code_pattern | pyspark | Kinesis Structured Streaming 模式 |
| `code.quality_expectations_python` | code_pattern | data_quality | 稳定的数据质量规则模式 |
| `code.delta_merge_sql` | code_pattern | sql | Delta MERGE 模式 |
| `code.gold_aggregation_sql` | code_pattern | sql | Gold 聚合 SQL 模式 |
| `checklist.ingestion_and_schema` | checklist | ingestion | 摄取与 Schema 演进检查 |
| `checklist.data_quality` | checklist | data_quality | 完整性、一致性和隔离检查 |
| `checklist.workflow_monitoring` | checklist | workflow | 调度、重试、告警和 SLA 检查 |
| `checklist.unity_catalog_pii` | checklist | governance | 权限、PII 和审计检查 |
| `checklist.performance` | checklist | performance | 文件、分区、Shuffle 与 SQL 检查 |
| `checklist.cost` | checklist | cost | 计算、调度、存储和用量检查 |
| `checklist.production_readiness` | checklist | delivery | 上线前完整性检查 |
| `deliverable.architecture_design` | deliverable | delivery | 架构设计书结构 |
| `deliverable.table_design` | deliverable | delivery | 表定义书结构 |
| `deliverable.job_design` | deliverable | delivery | Job 设计书结构 |
| `deliverable.technical_proposal` | deliverable | delivery | 技术提案结构 |

### 10.2 `retail_sales_demo` 覆盖层

| ID | Kind | Category | Extends | 作用 |
| --- | --- | --- | --- | --- |
| `retail.project_context` | blueprint | delivery | 无 | 项目背景、范围和 SLA |
| `retail.source_contracts` | deliverable | ingestion | 无 | S3、DMS、Kinesis 输入契约 |
| `retail.end_to_end_architecture` | blueprint | pipeline | `pipeline.lakeflow_sdp` | AWS 端到端架构 |
| `retail.medallion_mapping` | blueprint | medallion | `medallion.standard` | 零售表分层与处理规则 |
| `retail.workflow_dag` | blueprint | workflow | `workflow.lakeflow_jobs` | Pipeline 与 Job 依赖图 |
| `retail.unity_catalog_access` | blueprint | governance | `governance.unity_catalog` | 环境、角色、PII 权限矩阵 |
| `retail.gold_data_products` | deliverable | medallion | `medallion.standard` | 四个 Gold 数据产品 |
| `retail.production_acceptance` | checklist | delivery | `checklist.production_readiness` | 零售项目验收清单 |

总计 37 个资产，属于“约 35 个”的确认范围。若实施时发现两个资产无法形成独立检索意图，应合并并在
规格变更记录中说明，不能用重复内容满足数量。

## 11. 数据库设计

新增 Alembic 迁移 `0007_expert_templates`。

### 11.1 `sessions`

增加：

```text
expert_profile VARCHAR(100) NOT NULL DEFAULT 'generic'
```

Profile 来自文件注册表，数据库不使用枚举 CheckConstraint。历史会话迁移为 `generic`；该值只影响迁移后的
新请求，不表示历史模型调用曾使用专家模板。

### 11.2 `model_calls`

增加两个可空审计字段：

```text
expert_profile VARCHAR(100) NULL
expert_template_selections JSONB NULL
```

历史记录保持 NULL。阶段 5 新调用始终写 `expert_profile`，并写空数组或实际选择数组。每个选择元素固定包含：

```json
{
  "template_id": "retail.workflow_dag",
  "version": "1.0.0",
  "content_hash": "64位sha256",
  "layer": "retail_sales_demo",
  "profile": "retail_sales_demo",
  "rank": 1,
  "reason": "semantic"
}
```

`reason` 只允许 `semantic`、`default`、`inherited`。不在 `model_calls` 重复保存模板正文。

### 11.3 `expert_templates`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | 不变的数据库记录 ID |
| `template_id` | VARCHAR(100) | Front Matter 业务 ID |
| `version` | VARCHAR(20) | SemVer |
| `name` | VARCHAR(200) | 中文显示名称 |
| `summary` | VARCHAR(500) | 检索与 API 摘要 |
| `kind` | VARCHAR(30) | 五种资产类型 |
| `category` | VARCHAR(50) | 业务分类 |
| `layer` | VARCHAR(100) | `core` 或覆盖层 ID |
| `profile_id` | VARCHAR(100) NULL | core 为空，覆盖层为 Profile ID |
| `cloud` | VARCHAR(20) | `neutral` 或 `aws` |
| `prompt_names` | JSONB | Prompt 名称数组 |
| `tags` | JSONB | 规范化标签数组 |
| `extends_id` | UUID NULL FK | 已解析的父模板记录 |
| `official_refs` | JSONB | 维护参考 URL |
| `source_path` | TEXT | 仓库相对 POSIX 路径 |
| `content` | TEXT | 规范化 Markdown 正文 |
| `content_hash` | VARCHAR(64) | 规范化元数据与正文 Hash |
| `status` | VARCHAR(20) | `active` 或 `inactive` |
| `chunk_count` | INTEGER | 当前版本 Chunk 数 |
| `created_at` | TIMESTAMPTZ | 首次入库时间 |
| `updated_at` | TIMESTAMPTZ | 状态更新时间 |
| `inactivated_at` | TIMESTAMPTZ NULL | 失活时间 |

唯一约束为 `(template_id, version)`；增加 `template_id` 当前 active 的部分唯一索引。`extends_id` 只能指向
core 模板，且父版本记录不能物理删除。

`extends_id` 是同步时解析的派生关系。core 发布新 active 版本时，可以在同一原子事务中把未变化的 active
覆盖模板重新指向新父版本；这不修改覆盖模板源码或 `content_hash`。每次模型调用仍必须把当时实际使用的父
模板 ID、版本和 Hash 写入 `model_calls` 与 Trace，历史审计不依赖当前 `extends_id`。

### 11.4 `expert_template_chunks`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | Chunk ID |
| `template_record_id` | UUID FK | 指向 `expert_templates.id` |
| `chunk_index` | INTEGER | 从 0 开始 |
| `heading_path` | JSONB | 标题路径 |
| `content` | TEXT | 用于检索的 Chunk 正文 |
| `content_hash` | VARCHAR(64) | Chunk Hash |
| `token_count` | INTEGER | token 数 |
| `embedding` | vector(1536) | OpenAI Embedding |
| `embedding_model` | VARCHAR(100) | 固定模型 ID |
| `search_vector` | TSVECTOR generated | PostgreSQL 全文检索 |
| `created_at` | TIMESTAMPTZ | 创建时间 |

向量检索继续使用精确余弦距离；全文列使用 `simple` 配置和 GIN 索引。第一版不增加 HNSW、IVFFlat 或新
向量服务。

### 11.5 `expert_template_sync_runs`

保存运行状态、源集合 Hash、Embedding 模型与维度，以及 discovered、inserted、activated、inactivated、
skipped、failed、chunk 数和错误摘要。状态只允许 `running`、`succeeded`、`failed`；模板同步采用原子发布，
不产生 `partial`。

## 12. Registry 与同步

### 12.1 启动预检

`ExpertTemplateRegistry.create_default()` 从固定目录加载 Profile 和全部 Markdown，在应用启动时执行：

1. YAML、Front Matter、Markdown 和字段校验。
2. Profile、Prompt、层、cloud 和默认模板引用校验。
3. 模板 ID、版本、路径和 H1 唯一性校验。
4. `extends` 存在性、core 所有权、循环和覆盖层深度校验。
5. 全部源文件集合 Hash 计算。

启动预检不访问数据库、不调用 OpenAI、不生成 Embedding。

### 12.2 显式同步

新增脚本：

```text
uv run databricks-zh-expert-templates sync
uv run databricks-zh-expert-templates sync --dry-run
uv run databricks-zh-expert-templates status
uv run databricks-zh-expert-templates evaluate
```

不提供 `--scope`、远程 URL、单文件同步或 Profile 白名单。每次同步都读取完整本地资产集合。

### 12.3 原子同步流程

```text
加载并校验全部源文件
-> 计算源集合 Hash
-> 对比数据库 active 版本
-> 拒绝“同版本不同 Hash”
-> 只为新增版本切分并生成 Embedding
-> 所有 Embedding 成功后开启数据库事务
-> 插入新版本和 Chunk
-> 解析并保存 extends_id
-> 激活新版本、失活旧版本和已删除模板
-> 完成同步运行
```

任何源校验、Embedding 或数据库错误都不改变当前 active 集合。失败运行保留错误摘要，便于开发调试。

### 12.4 索引就绪

专家索引只有同时满足以下条件才可查询：

1. 最新同步状态为 `succeeded`。
2. 最新 `source_hash` 等于启动 Registry 的当前源集合 Hash。
3. 至少存在一个 active 模板和一个 active Chunk。
4. 所有 active Chunk 只使用当前固定 Embedding 模型与 1536 维。
5. `generic` 和 `retail_sales_demo` 的 Prompt 默认模板均有 active 版本。

## 13. 检索与上下文

### 13.1 固定产品常量

以下值跨环境一致，定义为代码常量，不进入 `.env`：

```text
EXPERT_TEMPLATE_CHUNK_SIZE_TOKENS = 800
EXPERT_TEMPLATE_CHUNK_OVERLAP_TOKENS = 80
EXPERT_TEMPLATE_VECTOR_CANDIDATE_K = 20
EXPERT_TEMPLATE_LEXICAL_CANDIDATE_K = 20
EXPERT_TEMPLATE_TOP_K = 3
EXPERT_TEMPLATE_MAX_CONTEXT_TOKENS = 2500
EXPERT_TEMPLATE_MIN_VECTOR_SCORE = 0.30
```

Embedding 模型和维度复用阶段 4 固定的 `text-embedding-3-small` 与 1536 维，不新增环境变量。

### 13.2 预过滤

候选 Chunk 必须满足：

1. 模板版本为 active。
2. `prompt_names` 包含本次 Prompt。
3. 模板属于 Profile 声明的层。
4. `generic` 只允许 core；`retail_sales_demo` 允许 core 与零售覆盖层。
5. cloud 为 `neutral` 或与 Profile cloud 相同。
6. Embedding 模型等于当前固定模型。

### 13.3 混合排序

1. 对用户本轮问题只生成一次查询 Embedding。
2. 官方知识和专家模板需要同时检索时复用同一向量。
3. 专家检索分别获取 20 个向量候选和 20 个全文候选。
4. 使用与阶段 4 相同的 RRF `k=60` 融合。
5. 先按最佳 Chunk 聚合到模板，再按模板最高融合分排序。
6. 最多选择三个主要模板；覆盖模板命中时自动加入其 active core 父模板。
7. 实际交给模型的是受 token 预算限制的完整模板正文，不是孤立 Chunk 片段。
8. 无达到阈值的语义候选时，使用 Profile 中该 Prompt 的默认模板并记录 `reason=default`。

### 13.4 上下文渲染

专家上下文明确标记为“受信任的内部顾问参考，但只是默认建议”；官方上下文继续标记为不可信外部资料。
组装顺序为：

```text
system Prompt
-> 会话历史
-> 专家模板上下文
-> Databricks 官方资料上下文
-> 当前用户消息
```

正文中的优先级说明固定为：

```text
系统安全和产品边界
> 用户本轮明确要求
> Databricks 官方文档事实
> 项目覆盖层假设
> 通用模板默认建议
```

模板上下文不得要求模型声称执行成功，不得覆盖用户明确 SLA，不得覆盖官方功能状态。

## 14. Prompt 检索策略

| Prompt | 官方文档 RAG | 专家模板 |
| --- | --- | --- |
| `databricks_qa` | 否 | 是 |
| `knowledge_qa` | 是 | 否 |
| `sql_generation` | 是 | 是 |
| `pyspark_generation` | 是 | 是 |
| `workflow_design` | 是 | 是 |
| `proposal_generation` | 是 | 是 |
| `self_check` | 否 | 是 |
| `document_summary` | 否 | 否 |

策略作为 `PromptSpec` 的两个布尔产品字段保存：`use_official_knowledge` 与 `use_expert_templates`。模板自身的
`prompt_names` 决定专家候选范围，不在 Python 中维护模板 ID 白名单。

Prompt Jinja2 正文不因阶段 5 自动变化，因此不统一升级 Prompt 版本。若实施时确实修改模板正文，必须只为
受影响 Prompt 升级版本并保留历史审计值。

## 15. ChatService 数据流

```text
读取 session 和不可变 expert_profile
-> 解析 PromptSpec
-> 保存 user message
-> 根据 PromptSpec 判断需要的上下文来源
-> 检查官方与专家索引状态
-> 必要时生成一次查询 Embedding
-> 官方检索与专家模板检索
-> 按固定优先级组装模型 messages
-> ModelGateway 执行请求级模型选择与 fallback
-> 每次模型尝试写 model_calls、官方检索和模板选择审计
-> Trace 1.5 保存完整实际请求
-> Markdown Artifact 校验
-> 保存 assistant message 与官方 source_citations
```

专家索引不就绪、Profile 不存在或模板上下文无法构建时，在调用聊天模型前返回错误。已保存的 user message
继续保留，与阶段 4 的知识检索失败行为一致。

## 16. API

### 16.1 创建会话

`POST /api/chat/sessions` 请求增加：

```json
{
  "title": "零售销售设计",
  "expert_profile": "retail_sales_demo"
}
```

`expert_profile` 可省略，默认 `generic`。未知 Profile 返回 HTTP 422：

```json
{
  "code": "expert_profile_not_found",
  "message": "专家配置不存在。",
  "details": null
}
```

Session 列表、详情和创建响应增加 `expert_profile`。不提供修改 Profile 的 PATCH API。

### 16.2 Profile 列表

`GET /api/expert-profiles` 返回：

```json
{
  "default_profile": "generic",
  "profiles": [
    {
      "id": "retail_sales_demo",
      "display_name": "AWS 零售销售 Demo",
      "description": "通用核心层与 AWS 零售销售项目覆盖层。",
      "cloud": "aws"
    }
  ]
}
```

### 16.3 模板元数据列表

`GET /api/expert-templates` 支持 `profile`、`kind`、`category`、`limit`、`offset` 过滤，只返回 active 版本
元数据，不返回 Markdown 正文、Embedding、source path 或模型上下文。

### 16.4 索引状态

`GET /api/expert-templates/index/status` 返回最新运行、源 Hash 是否匹配、active 模板数、Chunk 数、模型、
维度和 `queryable`。`/health/ready` 同时检查数据库与专家模板索引；索引未就绪返回 HTTP 503。

### 16.5 消息响应

`POST /api/chat/sessions/{session_id}/messages` 请求和成功响应不增加 `template_id` 或选择详情。
`assistant_message.source_citations` 只在执行官方文档检索时返回官方来源。

## 17. Trace 1.5 与审计

Trace 顶层保持 OpenAI Chat Completions 超集，并从 1.4 升级为 1.5：

```json
{
  "schema_version": "1.5",
  "protocol": "openai.chat.completions",
  "trace": {
    "expert_profile": "retail_sales_demo"
  },
  "retrieval": {},
  "expert_templates": {
    "status": "selected",
    "embedding_model": "text-embedding-3-small",
    "latency_ms": 31,
    "context_token_count": 2140,
    "candidates": [
      {
        "template_id": "retail.workflow_dag",
        "version": "1.0.0",
        "rank": 1,
        "vector_rank": 1,
        "vector_score": 0.82,
        "lexical_rank": 2,
        "lexical_score": 0.17,
        "fused_score": 0.0325,
        "selected": true
      }
    ],
    "selected": [
      {
        "template_id": "retail.workflow_dag",
        "version": "1.0.0",
        "layer": "retail_sales_demo",
        "reason": "semantic",
        "extends": "workflow.lakeflow_jobs@1.0.0"
      }
    ]
  },
  "request": {},
  "response": {},
  "error": null
}
```

`request.messages` 保存实际发送的完整专家和官方上下文。API Key 继续由 Trace Sink 现有脱敏边界保护，不把
Front Matter 的本地绝对路径写入 Trace。

模型调用前发生的 Profile、Registry 或索引错误没有 `model_call_id`，只写结构化应用日志，不伪造模型调用
记录。

## 18. 错误边界

新增稳定错误：

| Code | HTTP | 场景 |
| --- | ---: | --- |
| `expert_profile_not_found` | 422 | 创建会话时 Profile 未注册 |
| `expert_template_index_not_ready` | 503 | 当前 Git Hash 与最新成功同步不一致或索引为空 |
| `expert_template_context_not_found` | 404 | 默认模板和检索结果都无法形成上下文 |
| `expert_template_sync_invalid` | CLI 2 | Profile、Front Matter、版本或继承无效 |
| `expert_template_embedding_failed` | CLI 1 / API 502 | Embedding 调用失败 |

`knowledge_qa` 保持现有官方知识错误。需要同时检索两类上下文时，任一必需索引失败都不调用聊天模型。

## 19. 安全与真实性

1. 模板来自受版本控制的可信本地文件，但仍只作为参考数据，不作为可执行代码。
2. 禁止在模板中保存 API Key、密码、连接字符串、真实姓名、真实邮箱和客户标识。
3. Front Matter 使用安全 YAML 解析，Markdown 不执行 HTML、Jinja、SQL、Python 或 shell。
4. 项目基线数值必须标注为项目假设，不可描述为 Databricks 官方推荐或真实基准。
5. 官方事实与模板冲突时，模型必须采用当前官方检索上下文并指出模板需要人工复核。
6. 站外 AWS 链接可以作为模板维护参考，但不自动抓取或转为 Databricks 官方引用。
7. 模板正文不通过 API 暴露，避免未来把内部项目经验当作公共内容服务。

## 20. 测试与评估

### 20.1 单元测试

1. Profile YAML、Front Matter、未知字段、SemVer、H1 和 Markdown 安全校验。
2. 模板 ID、版本、Profile、Prompt 默认值和继承关系校验。
3. 同版本不同 Hash 拒绝、版本升级、删除失活和同步原子性。
4. Markdown Chunk、Embedding 顺序、精确向量、全文检索和 RRF 排序。
5. Profile 预过滤、Prompt 预过滤、cloud 隔离、默认模板和继承加载。
6. 2,500 token 预算、完整模板选择和固定优先级上下文。
7. Prompt 检索策略矩阵和单次查询 Embedding 复用。
8. Trace 1.5、数据库 JSONB 审计与官方引用隔离。

### 20.2 集成测试

1. Alembic 0007 upgrade/downgrade 和模型字段。
2. PostgreSQL 三张专家表、generated tsvector、GIN 与 pgvector 精确检索。
3. 同步 CLI 的新增、跳过、升级、失活和失败回滚。
4. Profile、模板元数据、索引状态和 readiness API。
5. generic 与 retail 会话创建、不可修改 Profile 和历史会话兼容。
6. 八种 Prompt 的官方/专家检索策略和 `source_citations` 行为。
7. Fake ModelGateway 请求中的上下文顺序和完整正文。

### 20.3 固定检索评估

新增 `tests/evals/expert_templates.yml`，每条数据至少包含：

```yaml
- id: retail_workflow_design
  profile: retail_sales_demo
  prompt: workflow_design
  query: 为零售销售平台设计批处理、CDC 和 Kinesis 的工作流。
  expected_template_ids:
    - retail.workflow_dag
    - retail.end_to_end_architecture
  forbidden_layers: []
```

评估指标：

1. `Recall@3 >= 90%`。
2. `generic` 查询选中 `retail_sales_demo` 覆盖层的次数必须为 0。
3. 覆盖层命中时必须解析并记录 core 父模板。
4. 代码 Prompt 不应选中无关提案模板，治理 Prompt 不应选中无关 SQL 模板。

### 20.4 真实冒烟

1. 使用 `deepseek-v4-flash` 和 `retail_sales_demo` 生成一份完整 `workflow_design`。
2. 使用 `deepseek-v4-flash` 和 `retail_sales_demo` 生成一份 `proposal_generation`。
3. 使用 OpenAI Embedding 完成实际专家模板检索。
4. 核对官方引用只来自 `kb_*`，模板选择只来自专家表。
5. 核对 model_calls JSONB、Trace 1.5、完整请求和模型输出。
6. 保留真实会话、消息、model_calls、专家同步数据和 Trace，不执行验收清理。

## 21. 质量约束

1. Python 固定 3.12.10，依赖继续由项目内 uv 管理。
2. PyYAML、markdown-it-py、tiktoken、OpenAI、SQLAlchemy、pgvector 均复用现有直接依赖。
3. 不新增阶段 5 环境变量，不新增数据库或 Docker 服务。
4. 所有新增文档、模板正文、API 描述和错误消息使用中文。
5. 代码标识符、模板 ID、字段名、表名和命令使用英文。
6. README 只在专家索引成为启动必要步骤时增加一条同步命令，不添加内部架构说明。
7. 每次修改 Python 后运行 Ruff 与 Pyright/Pylance。
8. 每个任务运行聚焦测试，阶段收尾运行完整 pytest 和分支覆盖率。
9. 总覆盖率不得低于当前 80% 门禁。
10. 数据模型变更必须通过 Alembic current、upgrade、downgrade 和 check。
11. 真实验收数据与 Trace 必须保留。

## 22. 完成定义

阶段 5 只有同时满足以下条件才完成：

1. 37 个左右的模板文件全部通过 Registry 启动预检。
2. `generic` 和 `retail_sales_demo` 两个 Profile 可创建会话并保持不可变。
3. 专家模板可以增量、原子地同步到三张独立表。
4. 同版本不同正文会失败，升级和删除可以保留历史审计。
5. 官方知识和专家模板在数据、引用、上下文和 Trace 中清晰分离。
6. 八种 Prompt 严格遵循已确认检索矩阵。
7. ChatService 只生成一次查询 Embedding，并复用于需要的检索通道。
8. 模型调用的完整模板上下文、候选、选择和继承出现在 Trace 1.5。
9. `model_calls` 可以恢复 Profile、模板 ID、版本、Hash、层和选择原因。
10. 模板选择评估达到 `Recall@3 >= 90%` 且 Profile 泄漏为 0。
11. 两次 DeepSeek 真实冒烟成功，所有验收数据保留。
12. Ruff、Pyright、pytest、覆盖率和 Alembic 检查全部通过。

## 23. 待确认事项

当前没有待确认产品问题。若实施过程中发现稳定功能状态、现有代码接口或真实模型上下文行为与本规格冲突，
必须先记录事实和影响，再提交用户判断，不能静默改用 Preview 功能或改变 Profile、引用与错误边界。

## 24. 参考资料

1. [Databricks：连接 Amazon Kinesis](https://docs.databricks.com/aws/en/connect/streaming/kinesis)
2. [Databricks：Lakeflow Spark Declarative Pipelines](https://docs.databricks.com/aws/en/ldp/concepts)
3. [Databricks：Auto Loader](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/)
4. [AWS：使用 Amazon S3 作为 AWS DMS 目标](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html)
