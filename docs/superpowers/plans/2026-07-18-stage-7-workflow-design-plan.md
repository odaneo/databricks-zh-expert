# 阶段 7：工作流设计模块计划

> 所有文档、Prompt、API 描述和错误消息使用中文。实现阶段按任务执行 TDD；修改 Python 后必须运行 Ruff 和
> Pyright/Pylance。不得清理现有 Session、Message、ModelCall、同步记录或本地 Trace。

## 1. 目标

用户输入业务需求后，Agent 输出一份项目感知、结构稳定、可以继续加工为设计书的 Databricks 工作流 Markdown
提案。它需要说明数据分层、任务拆分、依赖、调度、重试、监控、风险和待确认事项，但不连接或操作 Databricks。

阶段 7 不重新实现聊天、RAG、专家模板或 Workspace。它在现有 `POST /api/chat/sessions/{session_id}/messages`
管线上，把已有的 `workflow_design` Prompt 升级为完整能力。

## 2. 当前基础

阶段 3 已经提供：

1. `workflow_design` Prompt 名称。
2. `workflow_design` Markdown Artifact 类型。
3. 11 个必需二级章节及顺序校验。

阶段 4、5、6 已经提供：

1. Databricks 官方文档混合 RAG。
2. 通用核心与 AWS 零售项目专家模板。
3. 本地 Workspace 事实读取和确定性上下文选择。
4. Session、Message、ModelCall 和 Trace 1.7 审计。

当前缺口是：`workflow_design` 尚未使用 Workspace Context，Prompt 任务说明过于简短，没有工作流专用回退策略、
项目提案标识、API 回归和完整的阶段评估。

## 3. 方案选择

### 方案 A：只扩写 Jinja2 Prompt

改动最少，但无法保证项目 DDL、需求和规则进入上下文，也无法建立可靠评估。只适合临时演示，不采用。

### 方案 B：增强现有 Chat 管线（采用）

保留单次模型调用，增加工作流专用 Workspace Context、固定输出契约、proposal 审计和评估。复用现有 RAG、专家模板、
Artifact、API 和 Trace，范围与阶段 7 匹配。

### 方案 C：引入 LangGraph 多步骤编排

可以拆成需求检查、检索、设计和自检节点，但会提前进入阶段 11，也会引入状态恢复和节点审计成本，本阶段不采用。

## 4. 用户流程

```text
创建 Session，可选绑定 Workspace
        |
        v
发送 workflow_design 请求
        |
        +--> 官方文档 RAG
        +--> 专家模板检索
        +--> Workspace 工作流上下文选择（绑定项目时）
        |
        v
一次模型调用生成 Markdown 工作流提案
        |
        v
结构校验、消息保存、ModelCall 审计、Trace 1.7
```

示例请求：

```json
{
  "content": "为每日销售、RDS CDC 和 Kinesis 订单事件设计 Databricks 工作流",
  "model": "deepseek-v4-flash",
  "prompt": "workflow_design"
}
```

## 5. 固定输出契约

保持现有 11 个二级章节，不增加新的 Artifact 类型：

| 顺序 | 章节 | 最低内容要求 |
| --- | --- | --- |
| 1 | 需求理解 | 目标、范围、SLA、已知事实、假设 |
| 2 | 数据源假设 | 来源、到达方式、频率、增量键、事实与待确认项 |
| 3 | Bronze 层设计 | 摄取方式、原始保留、Schema 演进、隔离和重放 |
| 4 | Silver 层设计 | 清洗、去重、CDC、业务键、质量规则 |
| 5 | Gold 层设计 | 数据产品、指标粒度、刷新依赖、消费方 |
| 6 | Notebook 拆分 | Notebook/脚本职责、输入、输出、参数 |
| 7 | Job 依赖关系 | 稳定 Task ID、任务类型、依赖、输入、输出、失败条件 |
| 8 | 调度建议 | 触发、并发、超时、重试、补数和回填 |
| 9 | 监控点 | 指标、阈值、告警、Owner、恢复入口 |
| 10 | 风险点 | 风险等级、影响、缓解措施 |
| 11 | 后续确认事项 | 缺失事实和需要人工决定的问题 |

`Job 依赖关系` 推荐同时给出任务表和 Mermaid DAG，但第一版不把 Mermaid 作为阻断性校验，避免模型格式细节导致
整份提案无效。Artifact 仍只阻断缺少标题、缺少章节、章节顺序错误、空内容、超长内容和原始 HTML。

## 6. 上下文与权威边界

工作流设计使用四类输入：

1. 本轮用户明确需求。
2. Workspace 中的需求、源 DDL 和已确认业务规则。
3. Databricks 官方 RAG 的产品能力、限制和引用。
4. 专家模板的设计模式、检查清单和项目覆盖层。

权威顺序固定为：

```text
本轮用户明确要求
> Workspace 源 DDL
> Workspace 已确认规则
> Workspace 项目需求
> Databricks 官方文档
> 专家模板
> 历史 Assistant 提案
```

历史 Assistant 输出只能作为未确认参考，不能覆盖用户事实。生成结果固定为
`project_fact_status=proposal`，不会写回 `.databricks-expert/`，也不会加入后续 Workspace Context。

## 7. Workspace 工作流检索策略

1. 在 `WorkspaceContextPurpose` 增加 `workflow_design`。
2. 继续使用本地确定性词法匹配，不调用 Embedding 或 LLM。
3. 精确表名、字段名、Source ID、文件名、标题和中文双字词继续参与评分。
4. 有关键词命中时先选择高分单元。
5. 工作流设计需要更广的事实覆盖，因此在高分单元后补充未重复的固定回退单元。
6. 回退优先覆盖业务目标、期望数据产品、摄取需求、相关源 DDL、CDC、事件时间、指标和数据质量规则。
7. 继续限制为最多 8 个完整单元、8,000 Token；单元不截断。
8. Trace 的 `candidates` 记录全部候选，`selected` 记录最终发给模型的单元及 `lexical/fallback` 原因。

其他五个代码生成 Prompt 的现有 Workspace 选择行为不改变。

## 8. API、数据库与 Trace

### API

不新增路由。继续使用：

```text
POST /api/chat/sessions
POST /api/chat/sessions/{session_id}/messages
GET  /api/prompts
```

阶段 7 的 API 变化：

1. `/api/prompts` 中 `workflow_design` 提升版本并保持可用。
2. 绑定 Workspace 的 Session 调用 `workflow_design` 时自动使用项目上下文。
3. 响应 `artifact.type=workflow_design`。
4. 响应 `artifact.project_fact_status=proposal`。
5. 未绑定 Workspace 时仍可使用官方 RAG 和专家模板生成通用工作流提案。

### 数据库

不新增表、不新增列、不创建迁移。继续复用：

1. `messages.content` 保存完整 Markdown 提案。
2. `messages.artifact_type=workflow_design`。
3. `model_calls` 保存 Prompt、专家模板、Workspace 版本、Hash、选择元数据和 proposal 状态。

Workspace 正文仍不进入 PostgreSQL。

### Trace

继续使用 Trace 1.7，不升级 Schema。完整模型请求保存在本地 Trace，数据库只保存 Workspace 选择元数据。

## 9. 明确不做

1. 不调用 Databricks Jobs、Pipelines、SQL Warehouse 或 Workspace API。
2. 不生成可直接部署的 Job JSON、Databricks Asset Bundle 或 `databricks.yml`。
3. 不执行 Notebook、SQL、PySpark 或工作流。
4. 不在一次请求内自动继续生成 DDL、SQL、PySpark 或 Notebook。
5. 不实现多轮缺失信息状态机；缺失信息只写入“后续确认事项”。
6. 不引入 LangGraph、多 Agent、工具调用或自动自检循环。
7. 不新增 Workflow CRUD、版本表、批准表或发布状态。
8. 不把提案写回项目目录，不提供 Markdown 下载；下载属于阶段 8。
9. 不实现图形化 DAG 编辑器；UI 属于后续阶段。
10. 不给出精确云费用，不声称工作流已部署、运行或验证。

## 10. 实施任务

### 任务 1：固定工作流 Prompt 与 Artifact 契约

**主要文件：**

- Modify: `src/databricks_zh_expert/prompts/registry.py`
- Modify: `src/databricks_zh_expert/prompts/templates/workflow_design.jinja2`
- Modify: `tests/unit/test_prompt_registry.py`
- Modify: `tests/unit/test_prompt_renderer.py`
- Modify: `tests/unit/test_markdown_artifact.py`
- Modify: `tests/integration/test_prompts_api.py`

**小目标：**

1. `workflow_design` 提升到 `1.1.0`。
2. 设置 `use_workspace_context=True` 和 `project_fact_status=proposal`。
3. 保留 11 个必需章节与顺序。
4. Prompt 明确事实、假设、提案和人工确认边界。
5. Prompt 要求任务表、依赖、调度、重试、监控和风险内容，但不新增脆弱的深层语义阻断。

**验证：**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py tests/unit/test_markdown_artifact.py tests/integration/test_prompts_api.py -q
uv run --locked ruff check src tests
uv run --locked pyright
```

---

### 任务 2：实现工作流专用 Workspace Context

**主要文件：**

- Modify: `src/databricks_zh_expert/workspace/types.py`
- Modify: `src/databricks_zh_expert/workspace/context.py`
- Modify: `tests/unit/test_workspace_context.py`
- Modify: `tests/evals/workspace_context.yml`
- Modify: `tests/unit/test_workspace_eval.py`

**小目标：**

1. 支持 `workflow_design` Purpose。
2. 高分词法匹配后补充工作流回退事实。
3. 保证当前零售示例在预算允许时覆盖需求、相关源 DDL 和规则。
4. 不改变 DDL、Mapping、SQL、PySpark 和 Notebook 的既有选择结果。
5. 候选、选择原因和 Token 计数保持可复现。

**验证：**

```powershell
uv run --locked pytest tests/unit/test_workspace_context.py tests/unit/test_workspace_eval.py -q
uv run --locked databricks-zh-expert-workspaces evaluate
uv run --locked ruff check src tests
uv run --locked pyright
```

---

### 任务 3：集成 ChatService、API、审计和 Trace

**主要文件：**

- Modify: `tests/unit/test_chat_context.py`
- Modify: `tests/unit/test_chat_service.py`
- Modify: `tests/unit/test_model_trace.py`
- Modify/Create: `tests/integration/test_workflow_design_messages_api.py`

预期主要复用现有生产代码；只有测试证明存在缺口时，才修改 `chat/context.py`、`chat/service.py` 或
`observability/model_trace.py`，不为“模块感”增加空抽象。

**小目标：**

1. Workspace、官方 RAG 和专家模板同时进入本次模型请求。
2. 普通无 Workspace 模式保持可用。
3. 成功和失败调用都保留 Prompt、专家模板和 Workspace 审计。
4. Assistant Message 保存完整工作流 Artifact。
5. API 返回 `workflow_design` 和 `proposal`。
6. Trace 1.7 能恢复候选、最终选择和完整模型请求。

**验证：**

```powershell
uv run --locked pytest tests/unit/test_chat_context.py tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_messages_api.py tests/integration/test_workflow_design_messages_api.py -q
uv run --locked ruff check src tests
uv run --locked pyright
```

---

### 任务 4：增加固定结构和上下文评估

**固定场景：**

1. 通用每日销售批处理 Workflow。
2. RDS PostgreSQL → DMS → S3 → Auto Loader CDC Workflow。
3. Kinesis 实时订单事件 Workflow。
4. 批处理、CDC、流处理和 Gold 刷新的混合 DAG。
5. 缺少 SLA、Owner 或补数规则时进入“后续确认事项”。

**门禁：**

1. Workspace 工作流 Context `Recall@5 >= 90%`。
2. 11 个章节存在且顺序正确。
3. Artifact 类型和 proposal 状态正确。
4. Workspace Context 不包含历史 Agent 提案。
5. 相对路径、Hash、候选和选择可审计。
6. 现有官方 RAG、专家模板和五类代码生成回归不下降。

---

### 任务 5：真实冒烟和阶段收尾

真实冒烟前必须先完成当前专家模板版本同步：

```powershell
uv run --locked databricks-zh-expert-templates sync
uv run --locked databricks-zh-expert-templates evaluate
```

该操作会把模板 Chunk 发送给 OpenAI Embedding。当前 Codex 执行环境可能阻止外部发送，届时由用户在本地终端执行；
不得伪造 Embedding 或手工改写同步状态。

使用 `deepseek-v4-flash`、`expert_profile=retail_sales_demo`、`workspace_id=retail_sales_demo` 保留真实验收数据：

1. 每日销售批处理工作流。
2. RDS CDC 与 Kinesis 混合工作流。
3. 缺失 SLA 和 Owner 的工作流提案。

**全量验证：**

```powershell
uv run --locked alembic current
uv run --locked alembic check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

不清理真实 Session、Message、ModelCall、模板同步记录或本地 Trace。

## 11. 完成标准

1. `workflow_design` 可以在有 Workspace 和无 Workspace 两种模式下生成有效 Markdown Artifact。
2. 项目模式能使用相关需求、源 DDL 和业务规则，不把历史提案当成事实。
3. 输出包含固定 11 个章节，并给出可执行到人工设计阶段的 Task、依赖、调度、重试、监控和风险方案。
4. API、数据库和 Trace 正确记录 `workflow_design`、Workspace 选择和 proposal 状态。
5. 不新增数据库迁移，不连接 Databricks，不执行或部署工作流。
6. 固定检索、结构回归、真实冒烟、Ruff、Pyright/Pylance 和全量测试通过。

## 12. 后续阶段接口

阶段 7 只产出并保存单次 Markdown 工作流提案。阶段 8 再负责把它整理、保存和下载为正式 Markdown 文档；阶段 11
再决定是否使用 LangGraph 将需求检查、检索、方案、代码、自检和文档输出串成固定流程。
