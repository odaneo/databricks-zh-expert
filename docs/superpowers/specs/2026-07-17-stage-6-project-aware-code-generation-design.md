# 阶段 6：全新项目代码与 Schema 提案设计

## 1. 背景

本阶段明确只处理一个**尚未建设 Databricks 目标层的全新项目**。用户拥有业务需求和源系统结构，但还没有可作为
项目事实的 Bronze、Silver、Gold DDL，也没有正式源到目标 Mapping。

因此输入与输出的边界固定为：

```text
用户输入：业务需求 + 已确认业务规则 + 源系统 SQL DDL
Agent 输出：Databricks DDL 提案 + Mapping 提案 + SQL/PySpark/Notebook 草稿
```

Databricks DDL 和 Mapping 不再要求用户提前提供。Agent 生成的内容始终标记为“提案、待确认”，在用户明确批准
并保存回项目之前，不得作为项目事实参与后续检索。

阶段 6 仍是顾问型 Agent，不连接源数据库或 Databricks，不导出 Schema，不执行代码，不修改用户项目目录。

## 2. 阶段目标

1. 固定全新项目需要提供的最小目录和文件格式。
2. 直接读取源数据库 Schema-only SQL 导出。
3. 让 Agent 生成 Databricks Bronze/Silver/Gold DDL 提案。
4. 让 Agent 生成固定 CSV 格式的源到目标 Mapping 提案。
5. 基于相同源上下文生成 Databricks SQL、PySpark 和 Python source Notebook 草稿。
6. 区分“用户事实”和“Agent 提案”，禁止生成结果自动升级为事实。
7. 在 Session、`model_calls` 和 Trace 1.7 中审计 Workspace、选中来源和提案状态。
8. 为未来桌面客户端的人工确认、导出和本地 SQLite 索引保留接口。

## 3. 已确认边界

1. 阶段 6 只支持从需求、规则和源 Schema 开始设计的新项目。
2. 阶段 6 只支持内置 `retail_sales_demo`，不提供任意本地目录注册。
3. 用户输入目录只包含需求、规则和源 Schema，不包含 Databricks 目标 DDL、Mapping、Bundle 或项目源码。
4. PostgreSQL 不保存用户项目源文件正文或项目索引。
5. Agent 输出继续作为消息 Artifact 保存；它不是 Workspace Context。
6. 同一会话的历史提案可以被模型看到，但系统必须明确其“未确认”状态。
7. 阶段 6 不实现提案批准、版本发布、写回项目或跨会话设计状态。
8. 不执行或验证生成的 SQL、PySpark、Notebook 或 DDL。
9. `expert_profile` 与 `workspace_id` 保持独立。
10. 真实冒烟数据不得清理。

## 4. 用户必须提供的目录

```text
<project-root>/
  .databricks-expert/                                [全部由用户提供]
    project.yml                                      [YAML，固定文件名]
    requirements.md                                  [Markdown，固定文件名]
    source-schema/
      <source-id>.sql                                [源系统 DDL，至少一个]
    business-rules.md                                [Markdown，固定文件名]
```

只有这一棵目录属于阶段 6 输入。不存在 Databricks DDL、Mapping、`databricks.yml`、`resources/`、`src/`、
`tests/` 或其他可选输入目录。

所有清单路径相对于 `.databricks-expert/`。清单禁止引用输入包外文件，程序不得在项目目录中创建索引、缓存、日志
或生成结果。

## 5. `project.yml` 契约

完整第一版格式：

```yaml
schema_version: 1
id: retail_sales_demo
display_name: AWS 零售销售分析 Demo
description: 从源系统 Schema 开始设计 Databricks Lakehouse 的零售销售项目。
version: 1.0.0
cloud: aws

documents:
  requirements: requirements.md
  business_rules: business-rules.md

source_schemas:
  - id: rds_postgresql
    dialect: postgresql
    files:
      - source-schema/rds-postgresql.sql
  - id: pos_parquet
    dialect: spark_sql
    files:
      - source-schema/pos-parquet.sql
  - id: kinesis_events
    dialect: spark_sql
    files:
      - source-schema/kinesis-events.sql
```

### 5.1 字段规则

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 固定为整数 `1`，不兼容阶段 6 旧清单 |
| `id` | 小写英文、数字和下划线，全 Registry 唯一 |
| `display_name` | 中文显示名称 |
| `description` | 中文说明 |
| `version` | 严格 `MAJOR.MINOR.PATCH` |
| `cloud` | 阶段 6 固定为 `aws` |
| `documents` | 固定登记需求和业务规则两个 Markdown |
| `source_schemas` | 至少一个来源；每项包含唯一 ID、方言和非空 SQL 文件列表 |

清单中不存在 Databricks Schema、Mapping、Prompt、Source tags、`default_context` 或生成结果路径。

### 5.2 路径与文件规则

1. 路径相对于 `.databricks-expert/`，使用 POSIX `/`。
2. 禁止绝对路径、反斜杠、`.`、`..` 和符号链接逃逸。
3. Documents 只允许 `.md`，源 Schema 只允许 `.sql`。
4. 文件必须存在、为普通文件、使用 UTF-8。
5. 同一文件不能重复登记。
6. 未知字段直接失败；YAML 使用 `yaml.safe_load()` 和 Pydantic `extra="forbid"`。
7. 单 SQL 文件最大 2 MiB，整个输入包最大 20 MiB。

## 6. `requirements.md` 契约

固定路径：`.databricks-expert/requirements.md`。

```markdown
# 项目需求

## 业务目标
要解决的问题、使用者和成功标准。

## 源系统
每个来源的用途、数据负责人角色、批流方式和到达频率。

## 期望数据产品
需要交付的报表、指标、分析主题或 Gold 数据产品，不提前规定物理字段。

## 摄取需求
全量、增量、CDC、文件和实时流的期望处理方式。

## 数据量与 SLA 假设
容量、延迟、批次窗口、新鲜度和恢复目标；未确认值明确标记为假设。

## 治理与安全
PII、保留、权限、脱敏和审计要求。

## 技术约束
AWS 服务、Databricks 能力、成本和禁止使用的 Preview 功能。

## 待确认事项
尚未由业务、治理或平台团队确认的问题。
```

需求文档描述“希望得到什么”，不得伪装成已经存在的 Databricks 表结构。

## 7. 源 Schema SQL 契约

目录：`.databricks-expert/source-schema/`。

1. PostgreSQL、MySQL 等数据库使用 Schema-only 导出 SQL。
2. Parquet、JSON、Kinesis 等非关系来源用逻辑 `CREATE TABLE` 表达字段和类型。
3. 允许 `CREATE TABLE`、`CREATE TYPE`、`CREATE SEQUENCE`、约束、索引、注释和必要的结构设置。
4. 禁止真实数据以及 `INSERT`、`UPDATE`、`DELETE`、`MERGE`、`COPY ... FROM STDIN` 和批量 `VALUES`。
5. 新增直接依赖 `sqlparse`，使用 `sqlparse.split()` 拆分语句，保留原始 SQL，不改写方言。
6. 每条 SQL 语句成为独立上下文单元，避免整份数据库导出一次进入模型。

示例：

```sql
CREATE TABLE public.customer (
    customer_id varchar(64) NOT NULL,
    email varchar(320),
    loyalty_tier varchar(32),
    updated_at timestamptz,
    PRIMARY KEY (customer_id)
);
```

源 DDL 对源表名、源字段名、类型和约束负责，是源系统物理结构的最高优先级事实。

## 8. `business-rules.md` 契约

固定路径：`.databricks-expert/business-rules.md`。

```markdown
# 已确认业务与数据规则

## 源数据粒度与业务键
每个来源记录的粒度、主键、业务键和幂等键。

## CDC 与去重
操作语义、提交时间、排序字段和重复处理。

## 事件时间与迟到数据
时区、水位、迟到边界、重放和业务日期。

## 指标口径
金额、退货、取消、库存和客户指标的已确认定义。

## 空值与数据质量
必填字段、隔离、质量门和失败处理。

## PII 与权限
敏感字段、脱敏、保留和发布边界。

## 待确认规则
尚未批准、只能作为 Agent 假设的规则。
```

该文件只记录已知规则和明确的待确认项，不包含预先设计好的 Bronze/Silver/Gold 表。

## 9. AWS 零售销售 Demo 输入

```text
examples/workspaces/retail_sales_demo/
  .databricks-expert/
    project.yml
    requirements.md
    source-schema/
      rds-postgresql.sql
      pos-parquet.sql
      kinesis-events.sql
    business-rules.md
```

三个源 SQL 分别表达：

1. RDS PostgreSQL 的 customer、product、store、inventory。
2. POS Parquet 销售明细。
3. Kinesis 订单、支付和行为事件。

`requirements.md` 只提出每日销售、商品表现、库存健康、客户与渠道四类期望数据产品，以及
RDS PostgreSQL → AWS DMS → S3 Parquet → Auto Loader 和 Kinesis 实时摄取要求。

Demo 不包含任何预制 Databricks DDL 或 Mapping。旧 `docs/`、`contracts/`、`sql/`、`databricks.yml`、
`resources/`、`src/` 全部删除。

## 10. Workspace 领域契约

### 10.1 Source 类型

```python
class WorkspaceSourceKind(StrEnum):
    REQUIREMENT = "requirement"
    SOURCE_DDL = "source_ddl"
    RULE = "rule"
```

Registry 确定性生成：

```text
requirements
rules
source_ddl.<source-id>.<file-stem>
```

用户不维护 Source ID、tags、summary、Prompt 列表或默认上下文。

### 10.2 Workspace Definition

`WorkspaceDefinition` 至少包含：

```text
workspace_id
display_name
description
version
cloud
source_hash
sources
```

API 和 Trace 只暴露输入包相对路径，不暴露绝对路径。

## 11. Registry 启动预检

1. 严格解析 `project.yml`。
2. 校验两个 Markdown 的固定标题和章节。
3. 校验源 SQL 文件、方言、大小、UTF-8 和目录边界。
4. 使用 `sqlparse` 拆分 SQL 并拒绝数据 DML。
5. 规范化 CRLF 为 LF，对清单和全部正文计算稳定 SHA-256。
6. 错误使用中文，不返回绝对路径或文件正文。
7. 不访问 PostgreSQL、SQLite、OpenAI、DeepSeek、Databricks 或网络。

## 12. Workspace Context

### 12.1 上下文单元

1. Markdown 项目文件按二级和三级标题切分；三级标题保留父标题作为完整标题。
2. 只有标题、没有正文的二级父章节不生成单元；后续三级标题仍保留原章节序号，避免 Unit ID 无意义漂移。
3. 源 SQL 按语句切分。

每个单元包含 Source ID、kind、方言、输入包相对路径、标题、正文、Hash 和稳定顺序。

### 12.2 选择策略

1. 支持 `ddl_generation`、`mapping_generation`、`sql_generation`、`pyspark_generation`、
   `notebook_generation`。
2. Query 对 Source ID、文件名、标题和正文做确定性词法匹配。
3. 完整源表名和字段名匹配权重最高；普通词使用文档频率和内容长度归一化，降低宽泛长章节对精确子章节的挤占。
4. 标题、父标题、子标题关键词分别加权；相同分数按 Source ID 和原章节顺序排序。
5. 首轮结果限制同一普通 Markdown 来源重复占位；源 DDL 允许多张明确命中的表同时进入。
6. 按 Prompt 的事实类型配额补足最相关的 DDL、规则、架构、质量、治理或数据产品单元；固定 seed 只在相关性足够时优先。
7. `mapping_generation` 和 `pyspark_generation` 首轮最多选择 4 个词法单元，其余提案 Prompt 首轮最多选择 3 个。
8. 最终最多选择 8 个完整单元，总预算 8,000 token。
9. 单元不截断；预算不足时跳过并继续。
10. 无匹配时按 Prompt 固定回退到有正文的需求、相关源 DDL 和规则子章节。
11. 不调用 LLM、Embedding、rerank 或 LangGraph。

### 12.3 三类上下文检索对比

| 数据来源 | 检索方式 | 是否使用 Embedding | 数据位置 |
| --- | --- | --- | --- |
| Databricks 官方文档 | pgvector 向量检索 + PostgreSQL 全文检索 + 混合排序 | 是 | PostgreSQL |
| 专家模板库 | 向量检索 + 全文检索 + Profile/Layer 规则 | 是 | PostgreSQL |
| Workspace 项目文件 | 本地确定性关键词加权匹配 | 否 | 本地文件和进程内存 |

三类检索都遵循“拆分数据、生成候选、计算相关性、排序、按 Token 预算选择、拼入模型上下文”的流程，
但 Workspace 面向规模较小且表名、字段名精确匹配优先的用户项目，不建立 Embedding 或数据库知识索引。
Workspace 正文只从本地项目文件读取；PostgreSQL 仅保存会话绑定、选中单元元数据和 Hash，本地 Trace 的
`request.messages` 则保留实际发送给模型的完整上下文。

### 12.4 权威顺序

1. 本轮用户明确要求。
2. 源 DDL 的物理表和字段。
3. 已确认业务规则。
4. 项目需求。
5. Databricks 官方 RAG 的产品语法和限制。
6. Expert Template 的设计方法。
7. 历史 Assistant 提案只能作为未确认参考，不能覆盖前述事实。

## 13. Agent 提案输出

### 13.1 Prompt 与 Artifact

| Prompt | Artifact | 输出责任 |
| --- | --- | --- |
| `ddl_generation` | `sql` | Bronze/Silver/Gold Databricks DDL 提案 |
| `mapping_generation` | `csv` | 源字段到提议目标字段的 Mapping |
| `sql_generation` | `sql` | Databricks SQL 草稿 |
| `pyspark_generation` | `pyspark` | PySpark 草稿 |
| `notebook_generation` | `notebook` | Python source Notebook 草稿 |

新增 `ArtifactType.CSV`。CSV Artifact 只检查单个 `csv` 代码围栏和固定表头，不做容易误报的深层业务校验。

Mapping 提案表头固定为：

```csv
mapping_id,source_table,source_column,target_table,target_column,transformation,join_condition,filter_condition,aggregation,notes
```

### 13.2 提案状态

1. 五类输出统一标记 `project_fact_status=proposal`。
2. 提案保存在 Assistant Message 和 `model_calls` 审计中。
3. 提案不会写入 `.databricks-expert/`，也不会加入 Workspace Context。
4. 同一 Session 的后续模型调用可以看到历史提案，但 Prompt 必须写明“未确认”。
5. 当前阶段没有“批准”按钮、批准表或自动发布动作。
6. 未来用户明确批准并导出后，才可能进入后续已有项目模式。

### 13.3 输出约束

1. DDL、SQL、PySpark 保持代码为主，避免固定长篇说明。
2. Notebook 使用 `# Databricks notebook source` 和 `# COMMAND ----------`。
3. 不执行、不编译、不保存到项目、不声称已验证。
4. 目标表和字段是提议值，必须通过注释或 Artifact 元数据体现待确认状态。

## 14. 会话、API 与数据库

### 14.1 会话

`sessions.workspace_id` 可空，创建后不可变。Workspace 模式由 Registry 决定，不由 API 请求覆盖。

### 14.2 API

```text
GET  /api/workspaces
GET  /api/workspaces/{workspace_id}
POST /api/chat/sessions
POST /api/chat/sessions/{session_id}/messages
```

Workspace API 返回 ID、名称、说明、版本、云、Source 数、Hash 和相对路径，
不返回正文或绝对路径。

### 14.3 PostgreSQL

保存：

1. `sessions.workspace_id`。
2. `model_calls.workspace_id`。
3. `model_calls.workspace_version`。
4. `model_calls.workspace_source_hash`。
5. `model_calls.workspace_context`：实际选中的输入单元。
6. Artifact 类型和 `project_fact_status=proposal`。

不创建项目 DDL、Mapping 或项目文件内容表。

## 15. Trace 1.7

```json
{
  "trace": {
    "workspace_id": "retail_sales_demo",
    "workspace_version": "1.0.0",
    "workspace_source_hash": "<sha256>",
    "project_fact_status": "proposal"
  },
  "context": {
    "workspace": {
      "selected": [
        {
          "source_id": "source_ddl.rds_postgresql.rds-postgresql",
          "unit_id": "source_ddl.rds_postgresql.rds-postgresql:1",
          "kind": "source_ddl",
          "source_path": ".databricks-expert/source-schema/rds-postgresql.sql",
          "rank": 1,
          "reason": "lexical"
        }
      ]
    }
  }
}
```

Trace 继续保留实际发送给模型的完整 Prompt 和输出，便于查看源 DDL、需求和规则如何进入调用。

## 16. 程序生成数据

未来本地索引仍放：

```text
%LOCALAPPDATA%/DatabricksZhExpert/
  workspaces/
    <workspace-key>/
      workspace.sqlite3
```

SQLite 只索引用户输入事实，不把 Agent 提案混入同一索引。阶段 6 不实现此数据库。

## 17. 安全

1. 输入包不得包含凭据、连接串、私钥、真实数据或真实 PII 值。
2. SQL 只包含结构，不包含数据。
3. Registry 不读取输入包外文件。
4. API、数据库元数据和 Trace 不包含绝对路径。
5. Agent 不执行输入 SQL 或输出代码。

## 18. 评估

固定检索问题：

1. 根据 RDS Customer Schema 设计客户 CDC DDL。
2. 根据 POS 字段设计销售事实和每日销售 Gold DDL。
3. 根据 Kinesis 事件设计 Bronze 流式摄取 Notebook。
4. 生成源到目标 Mapping CSV。
5. 对不存在的源字段明确报缺失，不编造为源事实。

固定门禁：

```text
Workspace Context Recall@5 >= 90%
```

真实冒烟使用 `deepseek-v4-flash`，至少保留 DDL、Mapping、PySpark 和 Notebook 四个提案调用。

## 19. 当前代码迁移

下一次代码修改必须整体移除旧契约：

1. 删除旧 `project.yml.sources/default_context`。
2. 删除 `tables.yml`、`mappings.yml`、预制业务目标 DDL 和 11 Source 设计。
3. 删除 Demo 的 `docs/`、`contracts/`、`sql/`、`databricks.yml`、`resources/`、`src/`。
4. 只保留 `requirements.md`、`business-rules.md` 和三个源 Schema SQL。
5. Registry Source 类型缩减为 requirement/source_ddl/rule。
6. 重写当前未提交的 Context Builder，使其只选择用户事实。
7. 新增 DDL 和 Mapping Prompt，并增加 CSV Artifact。
8. 不重写 Git 历史，通过普通提交完成迁移。

## 20. 不包含

1. Databricks 目标 DDL 或 Mapping 作为用户输入。
2. 提案批准、写回项目、导出文件和跨会话设计状态。
3. LangGraph 自动串联“DDL → Mapping → Code”流程。
4. 任意本地目录选择、文件监听和 SQLite 实现。
5. 扫描源码仓库、Notebook、Bundle、Terraform 或测试目录。
6. 项目 Embedding、向量检索或 LLM 文件分类。
7. SQL/PySpark/Notebook 执行、部署或下载。
8. 数据库连接、Schema 自动导出或真实数据采样。

## 21. 完成定义

1. Demo 只包含需求、规则和源 Schema。
2. Registry 严格加载 `greenfield` 新契约并拒绝旧契约。
3. Workspace Context 只包含用户事实，不包含 Agent 历史提案。
4. DDL、Mapping、SQL、PySpark、Notebook 五类输出全部标为 proposal。
5. API、数据库和 Trace 可审计 Workspace、输入单元和提案状态。
6. 固定评估、全量 pytest、Ruff、Pyright、Alembic 和真实冒烟通过。
7. 不清理任何真实验收数据。
