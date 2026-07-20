# 阶段 9：Northwind 项目端到端固定评估实施计划

> **执行要求：** 实施时使用 `superpowers:executing-plans` 在当前会话中顺序执行，不使用子智能体。每个任务按
> TDD 完成并独立验收；修改 Python 后必须运行 Ruff 和 Pyright/Pylance。所有真实 Session、Message、ModelCall、
> Trace 和评估报告均保留，不清理或伪造。

**目标：** 用公开的 `northwind_psql` PostgreSQL Schema 建立唯一内置项目 Workspace，并增加一套通过正式 Chat API
验证最终模型输出质量的固定评估能力。

**架构：** `northwind_psql` 提供项目事实，Northwind 基线使用 `generic` 专家 Profile，Databricks 官方知识库提供产品
事实。`retail_sales_demo` 只保留在专家模板库并由既有专家模板评估独立验证，不再冒充 Northwind 项目事实。评估分为
不调用模型的确定性检索门禁和手动触发的真实模型端到端门禁；不使用 LLM-as-a-Judge，不比较整段标准答案。

**技术栈：** Python 3.12.10、FastAPI、Pydantic、PyYAML、HTTPX ASGI Transport、PostgreSQL、pytest、Ruff、Pyright。

## 全局约束

1. 不新增业务 API、数据库表、字段或 Alembic 迁移。
2. 不连接或操作 Databricks，不执行生成的 SQL、PySpark、Notebook 或工作流。
3. 不在应用运行时访问 GitHub；用户提供的 Northwind 上游原件完整归档，应用只读取派生的 Schema-only 文件。
4. 上游固定为 `pthom/northwind_psql` commit `cd0ef28d66369fbe177778e604e4be0f153c9e5c`；用户已提供的
   `northwind.sql` SHA-256 为 `0EE30C01BA282F7194F38BF7F99CD6BE0470B7EE5F67D0F7CA41FB058D735E0C`，
   与该 commit 的原始文件完全一致。
5. 原件包含 3,362 条 `INSERT`，不得直接注册为 Workspace Source。实际上下文只收录 14 张表的 Schema、14 个主键和
   13 个外键，不收录 `INSERT`、`DROP TABLE`、会话 `SET`、图片或 Docker 配置。
6. 保留完整 Microsoft Public License 和来源说明；许可证原文是第三方法律文本，不翻译、不改写。
7. `retail_sales_demo` 从 `examples/workspaces` 移除，但 `knowledge/expert_templates/overlays/retail_sales_demo`
   完整保留。
8. 内置项目评估固定使用 `workspace_id=northwind_psql` 和 `expert_profile=generic`。零售 Profile 的继承、覆盖和
   隔离继续由 `tests/evals/expert_templates.yml` 验证，不混入 Northwind 基线。
9. 真实验收固定运行 `deepseek-v4-flash` 和 `deepseek-v4-pro` 两轮，每轮 16 道题；发生 fallback 时保留记录，
   但对应 Case 判定失败。
10. 本地评估报告写入已忽略的 `.local/evaluations/`，README 不增加非启动步骤。

---

## 1. 阶段边界

阶段 9 解决两个问题：

1. 用独立公开 Schema 替换为测试答案定制的零售 Workspace。
2. 从“检索是否命中”继续验证到“最终模型回答是否遵守项目事实和交付契约”。

阶段 9 不重新实现 RAG、专家模板、Workspace、Prompt、Artifact 或模型网关。现有三套固定评估继续保留：

| 评估集 | 当前题数 | 验证对象 |
| --- | ---: | --- |
| `tests/evals/databricks_rag.yml` | 28 | 官方知识检索 |
| `tests/evals/expert_templates.yml` | 30 | 专家模板检索与 Profile 隔离 |
| `tests/evals/workspace_context.yml` | 8 | 项目事实选择与上下文泄漏 |

新增的端到端评估验证正式链路：

```text
固定问题
→ 创建带 expert_profile/workspace_id 的 Session
→ 官方 RAG + 专家模板 + Workspace Context
→ 指定模型生成回答
→ Artifact 校验和消息保存
→ ModelCall / Trace 审计
→ 确定性规则评分
→ 本地 JSON 和 Markdown 报告
```

---

## 2. 用户准备与已确认决策

用户不需要从零编写资料。Northwind SQL 原件已经准备并验证；Agent 负责提取 Schema、起草项目资料和评估题，用户负责
确认业务含义和质量标准。

### 2.1 已确认内容（2026-07-20）

| 内容 | 已确认决定 |
| --- | --- |
| 目标架构 | AWS RDS PostgreSQL → AWS DMS → S3 Parquet → Databricks Auto Loader |
| 数据产品 | 每日销售、客户价值、商品与品类表现、员工销售表现、配送表现 |
| 固定评估题 | 采用本计划第 5 节 16 道题和确定性硬门禁 |
| 真实模型 | `deepseek-v4-flash` 和 `deepseek-v4-pro` 各完整运行 16 道题，共 32 次主调用 |
| 日志与结果 | 每个模型独立保存 Trace、JSON、Markdown，并生成跨模型对比报告 |
| 人工验收 | 每个模型审核 SQL、PySpark、Workflow 各 1 份，共 6 份 |

以上内容已经确认，不需要用户继续准备实施资料，也不要求用户撰写完整标准答案。真实运行结束后，用户只需要完成
计划内的 6 份人工结果审核。

### 2.2 已确认业务口径

1. 行毛额为 `unit_price * quantity`。
2. 行折扣金额为 `unit_price * quantity * discount`。
3. 行净销售额为 `unit_price * quantity * (1 - discount)`。
4. 订单净销售额是同一 `order_id` 下全部明细净额之和。
5. 每日销售使用 `orders.order_date` 归属日期。
6. `freight` 单独作为运费指标，不计入净销售额。
7. `shipped_date > required_date` 表示延期发货。
8. Northwind 没有取消、退货和币种字段，不虚构相关口径、不做汇率换算；金额标记为源系统金额。
9. 默认统计全部订单；是否只统计已发货订单继续作为业务待确认事项。

### 2.3 用户不需要准备

1. `northwind.sql` 已提供并验证，不需要重新下载或手工清理。
2. 不需要提供 PostgreSQL 数据库或导入 Northwind 样例数据。
3. 不需要提供 Databricks Workspace、Token、Warehouse 或 Cluster。
4. 不需要为每道题写一篇标准回答。
5. 不需要提供新的向量数据库或 Embedding 配置。
6. OpenAI 和 DeepSeek API Key 已存在，无需新增供应商配置。

### 2.4 可选增强材料

如果以后有真实项目资料，可以替换或扩展：

1. 真实业务指标口径和 SLA。
2. 企业命名规范、Catalog/Schema 规范和权限要求。
3. 团队认可的 SQL、PySpark 或工作流样例。
4. 人工标注过的优质回答和失败回答。

这些材料不是阶段 9 完成的前置条件。

---

## 3. Northwind Workspace 固定结构

```text
examples/workspaces/northwind_psql/
├── upstream/
│   └── northwind.sql                   # 用户提供的上游原件，完整保留且不进入模型上下文
├── UPSTREAM.md                         # 中文来源、固定 commit、Hash、提取范围和更新规则
├── LICENSE.northwind                   # 上游 Ms-PL 原文，不进入模型上下文
└── .databricks-expert/
    ├── project.yml                     # Workspace manifest
    ├── requirements.md                 # 用户项目需求输入
    ├── business-rules.md               # 已确认规则与待确认项
    └── source-schema/
        └── northwind-schema.sql        # 14 张表、PK、FK；无 INSERT
```

职责固定为：

| 文件 | 性质 | 是否发送给模型 |
| --- | --- | --- |
| `project.yml` | 项目输入清单 | 只发送版本、Hash 等审计元数据 |
| `requirements.md` | 用户提供的项目事实 | 按检索结果发送 |
| `business-rules.md` | 用户确认的业务规则 | 按检索结果发送 |
| `northwind-schema.sql` | 从已验证原件提取的源 DDL 等价物 | 按表和 SQL 语句拆分后发送 |
| `upstream/northwind.sql` | 用户提供的完整上游原件 | 不发送 |
| `UPSTREAM.md` | 仓库维护与来源说明 | 不发送 |
| `LICENSE.northwind` | 第三方许可证 | 不发送 |

`northwind-schema.sql` 从 `upstream/northwind.sql` 确定性提取，必须包含以下 14 张表：

```text
categories
customer_customer_demo
customer_demographics
customers
employees
employee_territories
order_details
orders
products
region
shippers
suppliers
territories
us_states
```

提取结果固定为 14 条 `CREATE TABLE` 和 27 条添加主外键的 `ALTER TABLE`，同时保留组合主键和自引用
`employees.reports_to`。禁止为了评估方便增加 `store_id`、`order_line_id`、`event_ts`、`email` 等不存在字段。
原件本身不改写；更新上游版本时必须重新核对 commit、原件 Hash、提取差异和许可证。

---

## 4. 端到端评估方式

### 4.1 两类运行模式

**离线门禁：**

1. 在 pytest 中运行，不调用 OpenAI 或 DeepSeek。
2. 校验数据集、评分规则、Workspace 选择、Artifact 和报告生成。
3. 使用 Fake Gateway 覆盖成功、fallback、结构失败和 API 错误。

**真实模型门禁：**

1. 通过新的 CLI 手动触发。
2. 使用当前 `.env`、开发数据库、真实官方知识库和专家模板索引。
3. 通过应用内 ASGI Transport 调用正式 Chat API，不复制 ChatService 业务逻辑。
4. 每个 Case 创建独立 Session，标题带评估 Run ID。
5. Session、Message、ModelCall 和 Trace 保留；不在评估结束后删除。
6. 评估某个模型时，发生 fallback 记为该 Case 失败，但完整 fallback 审计继续保留。
7. 两个模型使用同一个数据集版本和 Workspace Hash，分别运行并分别记录，不共享模型响应。

### 4.2 分模型输出结构

```text
.local/evaluations/<run-id>/
├── deepseek-v4-flash/
│   ├── trace.jsonl
│   ├── result.json
│   └── report.md
├── deepseek-v4-pro/
│   ├── trace.jsonl
│   ├── result.json
│   └── report.md
└── comparison.md
```

每个模型目录只保存该模型对应的 16 个 Case。`comparison.md` 对比通过率、失败题目、Artifact、项目事实错误、引用、
Token、延迟和 fallback，不用主观总分掩盖硬门禁失败。

### 4.3 评分边界

自动评分只检查可以稳定验证的事实：

1. HTTP 状态、Prompt、模型、Artifact 类型和 proposal 状态。
2. 官方引用数量、URL 域名和结构化引用是否保存。
3. Workspace ID、版本、Hash、预期源文件和上下文单元是否进入审计。
4. 固定 Markdown 章节或代码围栏是否存在。
5. 必需表名、字段名和关系是否出现。
6. 禁止字段、部署完成声明、执行成功声明是否出现。
7. 是否把 Workspace 事实、官方事实和专家建议混为一谈。

第一版不自动判断自然语言方案的“审美”和“最佳实践优劣”，也不让另一个 LLM 给答案打分。主观质量由人工抽查表记录。

### 4.4 通过门禁

1. 16 个 Case 全部完成，不允许未分类异常。
2. 硬门禁通过率必须为 100%。
3. Artifact 结构通过率必须为 100%。
4. 需要官方依据的 Case 引用通过率必须为 100%。
5. Workspace Case 的预期源选择通过率必须为 100%。
6. 不存在字段和虚假执行声明的违规数量必须为 0。
7. 允许的非阻断建议项得分不低于 90%。
8. Flash 和 Pro 各自的 SQL、PySpark、Workflow 三份人工抽查结果均为“可继续评审”，共审核 6 份。

---

## 5. 第一版固定评估集合

### 5.1 Northwind 项目感知 Case（12 个）

| ID | Prompt | 核心问题 | 主要硬门禁 |
| --- | --- | --- | --- |
| `nw_ddl_orders_bronze` | `ddl_generation` | 根据 `orders` 生成 Bronze DDL | 必须使用真实字段；禁止 `store_id` |
| `nw_ddl_sales_silver` | `ddl_generation` | 为 `orders` 与 `order_details` 设计 Silver | 保留订单和商品业务键；不虚构行 ID |
| `nw_mapping_order_sales` | `mapping_generation` | 生成订单销售 Mapping | 引用 `orders`、`order_details`、`products` |
| `nw_sql_daily_sales` | `sql_generation` | 生成每日销售聚合 SQL | 使用折扣口径和真实连接键 |
| `nw_sql_customer_value` | `sql_generation` | 生成客户价值 SQL | 正确连接 `customers.customer_id` |
| `nw_sql_missing_field` | `sql_generation` | 请求不存在的 `orders.store_id` | 必须明确字段不存在，不得静默生成 |
| `nw_pyspark_order_cleaning` | `pyspark_generation` | 生成订单明细清洗代码 | 使用真实列并处理数量、价格、折扣 |
| `nw_pyspark_referential_quality` | `pyspark_generation` | 检查订单、商品外键质量 | 使用真实 PK/FK，不声称已执行 |
| `nw_notebook_dms_bronze` | `notebook_generation` | 生成 DMS S3 文件摄取 Notebook 草稿 | Auto Loader 参数化、无凭据、不声称已连接 |
| `nw_notebook_sales_quality` | `notebook_generation` | 生成订单销售质量检查 Notebook | 使用真实列、外键和折扣范围 |
| `nw_workflow_daily_sales` | `workflow_design` | 设计每日销售工作流 | 11 章、稳定 Task ID、proposal |
| `nw_workflow_customer_product` | `workflow_design` | 设计客户与商品分析 DAG | 使用相关表、列出 SLA/Owner 待确认项 |

### 5.2 通用 Databricks Case（4 个）

| ID | Prompt | 核心问题 | 主要硬门禁 |
| --- | --- | --- | --- |
| `generic_unity_catalog` | `knowledge_qa` | 解释 Unity Catalog 最小权限设计 | 必须返回官方引用 |
| `generic_delta_slow_sql` | `databricks_qa` | 分析 Delta 慢 SQL | 明确前置数据，禁止声称已执行 |
| `generic_project_proposal` | `proposal_generation` | 生成 Databricks 项目提案 | Artifact 为 proposal，事实与假设分离 |
| `generic_self_check` | `self_check` | 审查请求中给定的错误 SQL | 输出检查清单，不依赖 Workspace 隐式事实 |

题集不保存完整模型答案，只保存输入、结构化预期、禁止项和人工评分问题。

---

## 6. 文件结构

### Northwind Workspace

- Move: `examples/workspaces/northwind_psql/.databricks-expert/source-schema/northwind.sql` →
  `examples/workspaces/northwind_psql/upstream/northwind.sql`
- Create: `examples/workspaces/northwind_psql/UPSTREAM.md`
- Create: `examples/workspaces/northwind_psql/LICENSE.northwind`
- Create: `examples/workspaces/northwind_psql/.databricks-expert/project.yml`
- Create: `examples/workspaces/northwind_psql/.databricks-expert/requirements.md`
- Create: `examples/workspaces/northwind_psql/.databricks-expert/business-rules.md`
- Create: `examples/workspaces/northwind_psql/.databricks-expert/source-schema/northwind-schema.sql`
- Delete: `examples/workspaces/retail_sales_demo/.databricks-expert/**`

### 统一评估模块

- Create: `src/databricks_zh_expert/evaluation/__init__.py`
- Create: `src/databricks_zh_expert/evaluation/types.py`
- Create: `src/databricks_zh_expert/evaluation/dataset.py`
- Create: `src/databricks_zh_expert/evaluation/rules.py`
- Create: `src/databricks_zh_expert/evaluation/runner.py`
- Create: `src/databricks_zh_expert/evaluation/report.py`
- Create: `src/databricks_zh_expert/evaluation/cli.py`
- Create: `tests/evals/end_to_end.yml`
- Modify: `pyproject.toml`

### 测试和现有评估迁移

- Rename: `tests/unit/test_retail_workspace_content.py` → `tests/unit/test_northwind_workspace_content.py`
- Modify: `tests/unit/test_workspace_registry.py`
- Modify: `tests/unit/test_workspace_context.py`
- Modify: `tests/unit/test_workspace_eval.py`
- Modify: `tests/unit/test_chat_context.py`
- Modify: `tests/integration/test_workspaces_api.py`
- Modify: `tests/integration/test_sessions_api.py`
- Modify: `tests/integration/test_workspace_code_generation_messages_api.py`
- Modify: `tests/integration/test_expert_template_messages_api.py`
- Modify: `tests/evals/workspace_context.yml`
- Create: `tests/unit/test_evaluation_dataset.py`
- Create: `tests/unit/test_evaluation_rules.py`
- Create: `tests/unit/test_evaluation_report.py`
- Create: `tests/unit/test_evaluation_cli.py`
- Create: `tests/integration/test_end_to_end_evaluation.py`

`knowledge/expert_templates/overlays/retail_sales_demo/**` 不修改、不删除。

---

## 7. 实施任务

### 任务 1：把已确认决策写入 Northwind 项目输入

**小目标：**

1. 根据第 2 节已确认决定编写 Northwind `requirements.md`、`business-rules.md` 和 16 道端到端题。
2. AWS 摄取链路、5 类数据产品和销售口径必须逐项写入，不得引入未确认的门店、渠道、退货或币种事实。
3. 本任务只生成项目输入和评估数据，不运行真实模型；真实调用统一留到任务 7。

**验收：**

1. 项目需求中的已知事实、项目决定、设计假设和待确认项有明确标记。
2. 评估题不依赖未写入 Workspace 的隐藏知识。
3. 文件内容与第 2 节六项已确认结果完全一致，用户不需要再提供完整标准答案。

---

### 任务 2：用 Northwind 替换内置 Workspace

**TDD 顺序：**

1. 先修改 Registry、内容和 API 测试，要求只能发现 `northwind_psql`。
2. 运行测试，确认因 Workspace 不存在而失败。
3. 把用户提供的原件原样移动到 `upstream/northwind.sql`，移动前后 SHA-256 必须一致。
4. 从原件提取 14 条 `CREATE TABLE` 和 27 条主外键 `ALTER TABLE`，生成 `northwind-schema.sql`。
5. 提交固定 commit、原件 Hash、Schema、许可证、来源和项目输入。
6. 删除零售 Workspace 输入目录，但保留零售专家模板。
7. 运行 Workspace、Session 和 API 测试。

**验收：**

1. `/api/workspaces` 返回 `northwind_psql`，不返回 `retail_sales_demo`。
2. 归档原件与固定 commit 的 SHA-256 完全一致，并且不在 `project.yml` 中注册。
3. Schema 恰好包含 14 张表、14 个主键和 13 个外键。
4. `northwind-schema.sql` 不包含 `INSERT INTO`、`DROP TABLE`、会话 `SET`、样例行或凭据。
5. 来源 commit、原始 URL、原件 Hash、提取规则和许可证完整可审计。
6. Workspace 版本和 source hash 可复现，Context 候选中不出现 INSERT 数据。

---

### 任务 3：迁移 Workspace 固定检索门禁

**TDD 顺序：**

1. 把 `tests/evals/workspace_context.yml` 的 8 道零售题替换成 Northwind 题。
2. 固定 `orders`、`order_details`、`products`、`customers` 和关系约束的期望单元。
3. 加入 `store_id`、`order_line_id` 和 `email` 等禁止字段泄漏测试。
4. 调整 Context 回退种子时，只允许使用 Northwind 需求、规则和 DDL，不为题目硬编码表名。
5. 运行 `databricks-zh-expert-workspaces evaluate`。

**门禁：**

```text
Recall@5 = 100%
context_leak_count = 0
```

---

### 任务 4：固定端到端数据集契约和评分规则

**主要接口：**

```python
class EvaluationCase: ...
class EvaluationDataset: ...
class EvaluationRuleResult: ...
class EvaluationCaseResult: ...
class EvaluationRunResult: ...

def load_evaluation_dataset(path: Path) -> EvaluationDataset: ...
def score_case(case: EvaluationCase, evidence: EvaluationEvidence) -> EvaluationCaseResult: ...
```

**小目标：**

1. 使用严格 Pydantic 模型加载 `tests/evals/end_to_end.yml`。
2. 数据集固定为 16 个唯一 Case，不允许未知字段和重复 ID。
3. 规则分成 hard gate、soft check 和 manual review 三类。
4. 所有正则和包含规则在加载时编译预检。
5. 评分器只消费结构化 API、数据库和 Trace 证据，不读取模型内部状态。

**验收：**

1. 非法 Prompt、模型别名、Workspace、规则或阈值在调用模型前失败。
2. 同一证据重复评分得到相同结果。
3. 不使用 LLM-as-a-Judge。

---

### 任务 5：实现真实 Chat API 评估 Runner 和 CLI

**CLI：**

```powershell
uv run --locked databricks-zh-expert-evals validate
uv run --locked databricks-zh-expert-evals run --run-id stage9-baseline --model deepseek-v4-flash
uv run --locked databricks-zh-expert-evals run --run-id stage9-baseline --model deepseek-v4-pro
uv run --locked databricks-zh-expert-evals run --run-id stage9-debug --model deepseek-v4-flash --case nw_sql_daily_sales
uv run --locked databricks-zh-expert-evals compare --run-id stage9-baseline
```

**小目标：**

1. `validate` 只预检数据集、Workspace、Prompt、模型和索引状态，不调用模型。
2. `run` 使用 `create_app()`、应用 lifespan 和 HTTPX ASGI Transport 调用正式 API。
3. 每个 Case 使用独立 Session，并保存 Run ID、Case ID 和模型到标题。
4. 从 API 响应、Session、ModelCall 和 Trace 汇总评分证据。
5. 请求失败、Artifact 失败和 fallback 都形成可解释结果，不中断后续 Case。
6. CLI 最终按门禁返回 `0` 或非零退出码。
7. 同一个 Run ID 下两个模型使用独立目录和独立 `trace.jsonl`；`compare` 只读取已经完成的两份结果。

**验收：**

1. pytest 使用 Fake Gateway，不产生外部请求。
2. 真实 CLI 使用正式 OpenAI Embedding 和指定聊天模型。
3. 真实数据和 Trace 保留，不提供自动清理命令。

---

### 任务 6：生成本地评估报告

**输出：**

```text
.local/evaluations/<run-id>/<model>/trace.jsonl
.local/evaluations/<run-id>/<model>/result.json
.local/evaluations/<run-id>/<model>/report.md
.local/evaluations/<run-id>/comparison.md
```

**报告内容：**

1. 数据集版本和 Hash。
2. 模型、Prompt 版本、Workspace 版本和 source hash。
3. 总调用数、成功数、fallback 数、Token 和延迟。
4. 每个 Case 的 hard gate、soft check、人工检查项和失败原因。
5. Session ID、ModelCall ID 和 Trace 关联键。
6. 单模型最终通过状态和未通过 Case 列表。
7. 对比报告中的两模型通过率、错误类型、Token 和延迟差异。

报告只保存摘要和定位信息，不复制 API Key，也不额外复制完整模型上下文。

---

### 任务 7：真实评估和阶段收尾

**执行前检查：**

```powershell
uv run --locked databricks-zh-expert-kb evaluate
uv run --locked databricks-zh-expert-templates evaluate
uv run --locked databricks-zh-expert-workspaces evaluate
uv run --locked databricks-zh-expert-evals validate
```

**真实验收：**

```powershell
uv run --locked databricks-zh-expert-evals run --run-id stage9-baseline --model deepseek-v4-flash
uv run --locked databricks-zh-expert-evals run --run-id stage9-baseline --model deepseek-v4-pro
uv run --locked databricks-zh-expert-evals compare --run-id stage9-baseline
```

用户从 Flash 和 Pro 两份报告中分别人工审核：

1. `nw_sql_daily_sales`，共 2 份。
2. `nw_pyspark_order_cleaning`，共 2 份。
3. `nw_workflow_daily_sales`，共 2 份。

自动规则失败时，先判断是 Prompt、检索、模型输出还是规则本身的问题。不得为了得到满分而降低事实性硬门禁。

**全量验证：**

```powershell
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked alembic current
uv run --locked alembic check
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
git diff --check
```

---

## 8. 完成标准

1. `retail_sales_demo` 只存在于专家模板 Profile，不再是 Workspace。
2. `northwind_psql` 是唯一内置项目 Workspace，来源、许可证、固定 commit 和原件 Hash 可审计。
3. 用户提供的 Northwind 原件完整归档且不进入上下文；Schema-only 文件完整保留 14 张表及关系，不包含样例数据。
4. 三套现有固定评估继续通过，Workspace 评估已迁移到 Northwind。
5. 16 道端到端题可以通过统一 CLI 校验并运行。
6. 真实模型结果使用正式 Chat API、数据库和 Trace 链路，不使用测试捷径。
7. 自动评分只评价稳定事实，主观质量由用户抽查，不引入 LLM-as-a-Judge。
8. `deepseek-v4-flash` 和 `deepseek-v4-pro` 的独立 Trace、结果、报告及对比报告全部生成并保留，硬门禁全部通过。
9. 无新业务 API、数据库迁移、Databricks 连接或代码执行能力。

## 9. 后续接口

阶段 10 Web UI 可以读取现有 Chat API 展示 Session、Markdown 和引用；阶段 9 的本地报告只服务开发验收，第一版不增加
评估页面。原阶段 8 的 Markdown 预览与下载能力合并到阶段 10，不单独建设 Artifact CRUD。

---

## 10. 执行结果（2026-07-20）

### 10.1 实现状态

任务 1 至任务 7 已全部实现并执行。阶段 9 没有增加业务 API、数据库表、字段或 Alembic 迁移；真实评估通过正式
Chat API 创建独立 Session，并完整保留 Message、ModelCall、Trace 和本地报告。

Northwind 上游原件、Schema-only 输入、项目需求、业务规则、Workspace Registry、16 道端到端题、确定性评分器、
真实 Runner、CLI 和双模型对比报告均已落地。`retail_sales_demo` 已从 Workspace 移除，只保留为专家模板 Profile。

### 10.2 固定门禁

| 门禁 | 结果 |
| --- | --- |
| Databricks 官方知识库 | `Recall@5=92.86%`，通过 |
| 专家模板 | `Recall@3=100%`，Profile 泄漏 `0`，通过 |
| Northwind Workspace | `Recall@5=100%`，上下文泄漏 `0`，通过 |
| 端到端预检 | 数据集、模型配置、知识索引和专家模板索引均通过 |
| 数据集 Hash | `486f6814733387bf86a7c7fcfacd5e8108b78d2fdc2adc39b075523f5b9d9899` |
| Workspace Source Hash | `1ccd08bf4eea92bdd40533ab68c86b186f448c47d0fa1dc89b113629701a1c92` |

### 10.3 真实双模型基线

最终 Run ID 为 `stage9-final-v2-20260720`，输出保存在
`.local/evaluations/stage9-final-v2-20260720/`。此前的冒烟、诊断和规则校准 Run 也全部保留，没有清理。

| 模型 | Case | Hard Pass | Soft 平均 | Fallback | 自动门禁 | 总延迟 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `deepseek-v4-flash` | 16 | 100.00% | 96.88% | 0 | 通过 | 327,666 ms |
| `deepseek-v4-pro` | 16 | 87.50% | 89.58% | 0 | 未通过 | 698,983 ms |

Pro 的两个 Hard 失败均为真实模型输出问题，不是评分误判：

1. `nw_mapping_order_sales` 漏掉用户明确要求的 `products` 来源。
2. `nw_sql_missing_field` 已识别 `store_id` 不存在，但仍生成 `NULL AS store_id` 的可执行 `SELECT`。

Pro 另有两个非事实性 Soft 未达标：`nw_workflow_daily_sales` 和 `generic_delta_slow_sql`。对比报告已经区分
`Hard` 与 `Soft` 原因，不用单一通过率掩盖失败类型。

### 10.4 人工抽查状态

Flash 和 Pro 的 SQL、PySpark、Workflow 共 6 份输出均已生成。用户已于 `2026-07-20` 完成人工抽查并全部批准，
评价为“很完美”。人工审核记录保存在
`.local/evaluations/stage9-final-v2-20260720/manual-review.md`。技术预审结论：

1. 两份每日销售 SQL 均正确使用连接键、日期和净销售额口径，可继续评审。
2. 两份 PySpark 都需要人工确认 NULL 处理；当前布尔条件可能使含 NULL 的业务字段同时落在 valid/invalid 之外。
3. Pro 的 PySpark 还需确认隔离表重复写入和重跑幂等性。
4. 两份 Workflow 的稳定 Task ID 和依赖结构基本完整，但调度时间、阈值、容量、Owner、SLA 和回填策略仍是提案。

### 10.5 工程验收

1. Ruff format 和 lint 通过。
2. Pyright/Pylance 为 `0 errors, 0 warnings`。
3. Alembic 位于 `0009_drop_classification_fields (head)`，`alembic check` 无新增操作。
4. 完整测试为 `525 passed`，覆盖率 `87.88%`。

因此，阶段 9 的功能实现、真实运行、人工抽查和审计材料已经完成；Flash 满足自动门禁，Pro 如实保留为未通过基线。
原完成标准中“两个模型均通过自动门禁”尚未满足，不能标记为全模型自动质量验收通过。
