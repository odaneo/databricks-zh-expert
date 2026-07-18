# 阶段 6：全新项目代码与 Schema 提案实施计划

> 所有文档、项目内容、API 描述和错误消息使用中文。每个任务先写失败测试，再做最小实现；修改 Python 后必须
> 运行 Ruff 和 Pyright/Pylance。按用户要求不使用子智能体，不清理任何验收数据。

## 目标

用户只提供业务需求、已确认业务规则和源系统 Schema。Agent 负责生成 Databricks DDL、字段 Mapping、SQL、
PySpark 和 Notebook 提案，不连接或操作 Databricks。

详细设计见：

`docs/superpowers/specs/2026-07-17-stage-6-project-aware-code-generation-design.md`

## 核心边界

```text
用户事实输入
  requirements.md
  business-rules.md
  source-schema/*.sql
          |
          v
Workspace Context
          |
          v
Agent 提案输出
  Databricks DDL
  Mapping CSV
  SQL
  PySpark
  Notebook
```

1. Workspace 输入固定为需求、规则和源 Schema。
2. Databricks DDL 和 Mapping 是输出，不是输入。
3. 所有输出固定标记 `project_fact_status=proposal`。
4. 提案不会自动写入项目，也不会加入 Workspace Context。
5. 同一 Session 历史可以显示提案，但不得把它伪装成已确认事实。
6. 阶段 6 不实现批准、导出、写回或 LangGraph 自动串联。

## 用户必须提供的目录

```text
<project-root>/
  .databricks-expert/
    project.yml                                      [YAML，必需]
    requirements.md                                  [Markdown，必需]
    source-schema/
      <source-id>.sql                                [源 Schema，至少一个]
    business-rules.md                                [Markdown，必需]
```

没有 Databricks DDL、Mapping、Bundle、源码或其他可选输入目录。

## `project.yml`

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
    files: [source-schema/rds-postgresql.sql]
  - id: pos_parquet
    dialect: spark_sql
    files: [source-schema/pos-parquet.sql]
  - id: kinesis_events
    dialect: spark_sql
    files: [source-schema/kinesis-events.sql]
```

路径相对于 `.databricks-expert/`。清单中不存在目标 DDL、Mapping、Source tags、Prompt 列表或生成结果路径。

## 固定输入格式

### `requirements.md`

固定章节：

```text
业务目标
源系统
期望数据产品
摄取需求
数据量与 SLA 假设
治理与安全
技术约束
待确认事项
```

### `source-schema/*.sql`

1. 关系数据库使用 Schema-only 导出 SQL。
2. Parquet、JSON、Kinesis 使用逻辑 `CREATE TABLE` SQL 表达字段。
3. 允许结构注释、类型、约束和索引。
4. 禁止真实数据和 `INSERT/UPDATE/DELETE/MERGE/COPY FROM STDIN`。
5. 使用 `sqlparse` 按语句拆分后进入上下文。

### `business-rules.md`

固定章节：

```text
源数据粒度与业务键
CDC 与去重
事件时间与迟到数据
指标口径
空值与数据质量
PII 与权限
待确认规则
```

## 固定提案输出

| Prompt | Artifact | 输出 |
| --- | --- | --- |
| `ddl_generation` | `sql` | Databricks Bronze/Silver/Gold DDL |
| `mapping_generation` | `csv` | 源字段到提议目标字段 Mapping |
| `sql_generation` | `sql` | Databricks SQL 草稿 |
| `pyspark_generation` | `pyspark` | PySpark 草稿 |
| `notebook_generation` | `notebook` | Python source Notebook 草稿 |

Mapping CSV 固定表头：

```csv
mapping_id,source_table,source_column,target_table,target_column,transformation,join_condition,filter_condition,aggregation,notes
```

五类输出全部是 proposal，不能直接成为项目事实。

## Demo 最终目录

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

必须删除旧 Demo 的：

```text
docs/
contracts/
sql/
databricks.yml
resources/
src/
```

## 程序生成目录

阶段 6 不创建 SQLite。最终索引位置仍固定为：

```text
%LOCALAPPDATA%/DatabricksZhExpert/
  workspaces/
    <workspace-key>/
      workspace.sqlite3
```

SQLite 只索引用户事实，不索引 Agent 提案。

## 当前状态

阶段 6 的八个任务已经完成实现。旧 `project.yml.sources`、预制 Databricks DDL、`tables.yml` 和 Mapping 输入
已由 greenfield 契约替代；示例 Workspace 现在只保存需求、业务规则和三类源 Schema，目标层内容始终由 Agent 作为
proposal 生成。

## 全局约束

1. 阶段 6 只支持内置 `retail_sales_demo`。
2. 输入目录只包含需求、规则和源 Schema。
3. PostgreSQL 不保存源文件正文、项目 Chunk 或项目 Embedding。
4. Workspace 选择不调用 LLM、Embedding、rerank 或 LangGraph。
5. 不执行 SQL、PySpark、Notebook、Databricks CLI、SDK 或 AWS 操作。
6. `expert_profile` 与 `workspace_id` 保持独立。
7. SQL/PySpark 输出保持短代码围栏，Notebook 使用 Python source。
8. CSV Artifact 只校验围栏和表头，不做深层业务阻断。
9. 不降低 80% 覆盖率、阶段 4 Recall@5 或阶段 5 Recall@3 门禁。
10. 不清理任何 Session、消息、`model_calls`、知识库、模板或真实 Trace。
11. README 没有新增启动步骤时不修改。

## 技术栈

1. Python 3.12.10、uv。
2. FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL。
3. PyYAML：严格解析 `project.yml`。
4. `sqlparse`：新增直接依赖，拆分源 DDL。
5. `markdown-it-py`：处理需求和规则章节。
6. Python 标准库 `csv`：校验 Mapping 输出表头。
7. `tiktoken`：Workspace token 预算。
8. pytest、Ruff、Pyright/Pylance。

## 基线

执行任务 1 前：

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

记录当前未提交任务 3 文件，不回退已有改动。

## 任务顺序

1. 重构 greenfield 清单、依赖和 Registry。
2. 重建只含源事实的 AWS 零售销售 Demo。
3. 重构确定性 Workspace Context。
4. 增加 DDL/Mapping 提案和五类 Artifact。
5. 创建会话迁移和只读 Workspace API。
6. 集成 ChatService、提案审计和 Trace 1.6。
7. 增加固定评估和 API 回归。
8. 执行数据库升级、真实冒烟和阶段收尾。

---

## 任务 1：重构 greenfield 清单、依赖和 Registry

### 文件

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/databricks_zh_expert/workspace/constants.py`
- Modify: `src/databricks_zh_expert/workspace/types.py`
- Modify: `src/databricks_zh_expert/workspace/registry.py`
- Modify: `src/databricks_zh_expert/workspace/__init__.py`
- Replace: `tests/fixtures/workspaces/valid/retail_sales_demo/`
- Modify: `tests/unit/test_workspace_registry.py`

### 小目标

1. 新增直接依赖 `sqlparse`，版本在 `pyproject.toml` 和 `uv.lock` 可见。
2. 删除旧 `sources/default_context` 清单模型。
3. 新建固定 documents 和 source_schemas 模型。
4. Source 类型缩减为 `requirement/source_ddl/rule`。
5. 路径相对于 `.databricks-expert/`，只允许 `.md` 和 `.sql`。
6. 使用 `sqlparse.split()` 校验 DDL 并拒绝数据 DML。
7. 使用 `markdown-it-py` 校验两个 Markdown 的固定章节。
8. 单 SQL 文件最大 2 MiB，输入包最大 20 MiB。
9. 对清单和全部正文计算稳定 `source_hash`。
10. 错误使用中文，不泄露绝对路径或正文。

### 测试

1. 完整 greenfield 输入包正常加载。
2. 旧清单、非 greenfield 模式、目标 DDL 或 Mapping 字段直接失败。
3. 缺失需求、规则或源 DDL 失败。
4. 未知字段、重复文件、错误扩展名、绝对路径、`..` 和逃逸符号链接失败。
5. 非 UTF-8、过大文件、缺失 Markdown 章节失败。
6. SQL 含数据 DML 或无法拆分时失败。

验证：

```powershell
uv lock --check
uv run --locked pytest tests/unit/test_workspace_registry.py -q
uv run --locked ruff format src/databricks_zh_expert/workspace tests/unit/test_workspace_registry.py
uv run --locked ruff check src/databricks_zh_expert/workspace tests/unit/test_workspace_registry.py
uv run --locked pyright
```

建议提交：

```text
refactor: adopt greenfield workspace contract
```

---

## 任务 2：重建只含源事实的 AWS 零售销售 Demo

### 文件

- Replace: `examples/workspaces/retail_sales_demo/`
- Modify: `tests/unit/test_retail_workspace_content.py`
- Modify: `tests/unit/test_workspace_registry.py`

### 小目标

1. 删除旧 `docs/`、`contracts/`、`sql/`、`databricks.yml`、`resources/` 和 `src/`。
2. 创建 `requirements.md`，描述四类期望数据产品但不预定义目标字段。
3. 创建 RDS PostgreSQL Schema-only DDL。
4. 创建 POS Parquet 和 Kinesis 事件逻辑 DDL。
5. 创建 `business-rules.md`，保存源键、CDC、事件时间、质量和 PII 规则。
6. 删除 `tables.yml`、Mapping 输入和全部预制 Databricks DDL。
7. 重写 `project.yml` 为 greenfield 清单。

### 内容测试

1. 输入包只包含 6 个文件：清单、两份 Markdown、三份源 SQL。
2. RDS DDL 包含 customer/product/store/inventory。
3. POS DDL 包含销售行字段，Kinesis DDL 包含订单/支付/行为事件字段。
4. Requirements 包含八个章节和四类期望 Gold 产品。
5. Business Rules 包含七个章节。
6. 不存在 Bronze/Silver/Gold `CREATE TABLE`、Mapping 文件、真实数据或凭据。
7. 旧目录全部不存在。

验证：

```powershell
uv run --locked pytest tests/unit/test_workspace_registry.py tests/unit/test_retail_workspace_content.py -q
uv run --locked ruff check tests/unit/test_retail_workspace_content.py
uv run --locked pyright
```

建议提交：

```text
refactor: rebuild retail demo as greenfield input
```

---

## 任务 3：重构确定性 Workspace Context

### 文件

- Modify: `src/databricks_zh_expert/workspace/types.py`
- Modify: `src/databricks_zh_expert/workspace/context.py`
- Modify: `src/databricks_zh_expert/workspace/constants.py`
- Modify: `src/databricks_zh_expert/workspace/__init__.py`
- Replace: `tests/unit/test_workspace_context.py`

### 小目标

1. Requirements 和 Rules 按二级标题形成单元。
2. 源 SQL 按 `sqlparse.split()` 语句形成单元。
3. 单元包含稳定 ID、Source ID、kind、方言、相对路径、正文、Hash 和顺序。
4. 删除旧 tags、summary、`always_include` 和 `default_context` 评分。
5. 支持五个提案 Prompt 的确定性词法选择。
6. 完整源表和字段匹配权重最高。
7. 最多选择 8 个完整单元，总预算 8,000 token。
8. 无匹配时按 Prompt 固定回退到需求、源 DDL 和规则。
9. Workspace Context 永远不包含历史 Assistant 提案。
10. 不调用数据库、网络、Embedding 或 LLM。

### 测试

1. Customer CDC 请求选择 RDS DDL 与 CDC 规则。
2. POS DDL/Mapping 请求选择 POS Schema、数据产品需求和金额规则。
3. Kinesis Notebook 请求选择事件 DDL、摄取需求和迟到规则。
4. 五个 Prompt 回退顺序稳定。
5. 同分和重复输入结果稳定。
6. 单元不截断，预算不足时跳过。
7. 普通非提案 Prompt 不生成 Workspace Context。

验证：

```powershell
uv run --locked pytest tests/unit/test_workspace_context.py -q
uv run --locked ruff format src/databricks_zh_expert/workspace tests/unit/test_workspace_context.py
uv run --locked ruff check src/databricks_zh_expert/workspace tests/unit/test_workspace_context.py
uv run --locked pyright
```

建议提交：

```text
feat: build greenfield workspace context
```

---

## 任务 4：增加 DDL/Mapping 提案和五类 Artifact

### 文件

- Modify: `src/databricks_zh_expert/prompts/registry.py`
- Create: `src/databricks_zh_expert/prompts/templates/ddl_generation.jinja2`
- Create: `src/databricks_zh_expert/prompts/templates/mapping_generation.jinja2`
- Modify: `src/databricks_zh_expert/prompts/templates/sql_generation.jinja2`
- Modify: `src/databricks_zh_expert/prompts/templates/pyspark_generation.jinja2`
- Create: `src/databricks_zh_expert/prompts/templates/notebook_generation.jinja2`
- Modify: `src/databricks_zh_expert/artifacts/types.py`
- Modify: `src/databricks_zh_expert/artifacts/parser.py`
- Modify: `src/databricks_zh_expert/devtools/seed_demo_data.py`
- Modify/Create: Prompt、Artifact 和 seed 测试

### 小目标

1. 注册 `ddl_generation` 和 `mapping_generation`。
2. 新增 `ArtifactType.CSV`。
3. CSV Artifact 只校验一个 `csv` 围栏和固定表头。
4. 五个 Prompt 使用 Workspace Context。
5. Prompt 明确区分源事实和未确认目标提案。
6. DDL 生成 Bronze/Silver/Gold 提议结构。
7. Mapping 只引用源 DDL 中真实存在的源字段。
8. SQL/PySpark/Notebook 未获得确认目标结构时必须注明目标字段为提议值。
9. 所有输出设置 `project_fact_status=proposal`。
10. 输出保持代码或 CSV 为主，不增加固定长篇章节。

验证：

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/unit/test_seed_demo_data.py tests/integration/test_prompts_api.py -q
uv run --locked ruff check src tests
uv run --locked pyright
```

---

## 任务 5：创建会话迁移和只读 Workspace API

### 文件

- Create: `alembic/versions/0008_workspace_code_generation.py`
- Modify: `src/databricks_zh_expert/db/models.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/chat/schemas.py`
- Modify: `src/databricks_zh_expert/api/chat.py`
- Create: `src/databricks_zh_expert/api/workspace_schemas.py`
- Create: `src/databricks_zh_expert/api/workspaces.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/main.py`
- Modify/Create: 迁移、模型、Session API 和 Workspace API 测试

### 小目标

1. `sessions.workspace_id` 可空且创建后不可变。
2. `model_calls` 增加 Workspace ID、版本、source Hash、选择元数据和提案状态。
3. 创建 Session 时校验内置 Workspace。
4. Workspace API 返回项目元数据和用户输入相对路径。
5. API 不返回正文、绝对路径或 SQLite 路径。
6. 不创建项目内容、目标 DDL或 Mapping 数据表。

验证：

```powershell
uv run --locked pytest tests/unit/test_models.py tests/unit/test_errors.py tests/integration/test_migrations.py tests/integration/test_sessions_api.py tests/integration/test_workspaces_api.py -q
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked ruff check alembic src tests
uv run --locked pyright
```

---

## 任务 6：集成 ChatService、提案审计和 Trace 1.7

### 文件

- Modify: `src/databricks_zh_expert/chat/context.py`
- Modify: `src/databricks_zh_expert/chat/service.py`
- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/api/dependencies.py`
- Modify: `src/databricks_zh_expert/observability/model_trace.py`
- Modify/Create: Chat、Trace 和消息 API 测试

### 小目标

1. 仅五个提案 Prompt 构建 Workspace Context。
2. Prompt 顺序固定为系统、官方 RAG、专家模板、用户事实 Workspace、历史消息、本轮消息。
3. 历史 Assistant Artifact 明确标注未确认，不进入 Workspace Context。
4. 保存实际选中的单元和 `project_fact_status=proposal`。
5. Trace 记录 Workspace ID、版本、source Hash、选择元数据和提案状态。
6. 成功和失败调用都保存 Workspace 与提案审计。
7. 未选择 Workspace 时保持通用生成行为。

验证：

```powershell
uv run --locked pytest tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_workspace_code_generation_messages_api.py -q
uv run --locked ruff check src tests
uv run --locked pyright
```

---

## 任务 7：增加固定评估和 API 回归

### 固定问题

1. 根据 RDS Customer Schema 生成客户 CDC Databricks DDL。
2. 根据 POS Schema 生成销售事实和每日销售 Gold DDL。
3. 生成源到目标 Mapping CSV。
4. 生成 Kinesis Bronze PySpark 与 Notebook。
5. 请求不存在源字段时明确报缺失。

### 门禁

```text
Workspace Context Recall@5 >= 90%
```

同时验证：

1. Workspace Context 只含用户事实。
2. DDL、Mapping、SQL、PySpark、Notebook 全部标记 proposal。
3. API 和 Trace 只出现输入包相对路径。
4. 普通 Prompt 和无 Workspace 的选择数为 0。
5. 阶段 4、阶段 5 和现有 API 回归不下降。

---

## 任务 8：数据库升级、真实冒烟和阶段收尾

### 全量验证

```powershell
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

### 真实冒烟

使用 `deepseek-v4-flash`、`expert_profile=retail_sales_demo`、`workspace_id=retail_sales_demo`：

1. 生成 Databricks DDL 提案。
2. 生成 Mapping CSV 提案。
3. 生成 Customer CDC PySpark 提案。
4. 生成 Kinesis Bronze Notebook 提案。

检查 Assistant Message、`model_calls` 和 Trace，确认所有输出为 proposal，并保留全部验收数据。

### 完成标准

1. Demo 只存在 requirements、business rules 和 source schema。
2. 不存在预制 Databricks DDL、Mapping 输入或旧目录。
3. Registry、Context、Prompt、API、审计和 Trace 使用同一 greenfield 契约。
4. 五类提案输出均可生成且不会自动成为项目事实。
5. 全量测试、Ruff、Pyright/Pylance、Alembic 和 Recall 门禁通过。

### 实施结果（2026-07-18）

1. Alembic 已升级到 `0009_drop_classification_fields (head)`，`alembic check` 无新增迁移差异。
2. 示例 Workspace 只包含 `project.yml`、`requirements.md`、`business-rules.md` 和三份 `source-schema/*.sql`。
3. Workspace 固定评估共 5 个问题、6 个期望单元，`Recall@5 = 100%`。
4. 专家模板已补齐五类提案 Prompt 覆盖并完成版本化同步；30 个固定问题的 `Recall@3 = 96.67%`，Profile
   泄漏和继承缺失均为 0。
5. DDL、Mapping、PySpark 和 Notebook 四条真实 API 链路均生成有效 Artifact，全部保存
   `project_fact_status=proposal`、Workspace 版本、source Hash、相对路径选择和专家模板选择。
6. Mapping 首次 DeepSeek 调用超时后由 fallback 状态机切换到 `gpt5.4mini` 并成功；成功和失败尝试都保留在
   `model_calls` 与历史 Trace 1.6 中；新调用使用 Trace 1.7。
7. 所有真实会话、消息、模型调用、模板同步记录和本地 Trace 均保留，没有清理验收数据。
8. Python 3.12.10 下全量测试 `494 passed`，覆盖率 `88.48%`；Ruff 全部通过，Pyright/Pylance 为 0 错误、
   0 警告。
