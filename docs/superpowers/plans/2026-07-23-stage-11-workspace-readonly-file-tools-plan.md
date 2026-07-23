# 阶段 11：Workspace 只读文件检索与工具系统实施计划

> **执行说明：** 本阶段先建立独立、可测试的只读工具基础设施，再接入有界模型工具调用。
> 阶段 10 已冻结的结果继续作为对照基线，不覆盖任何历史评估、Trace 或日志；生产主流程不再保留
> Workspace Context 加权匹配或失败回退。

**目标：** 解决一次性 Workspace Context 容易漏掉精度、字段、分层和运维约束的问题，让 Agent 能在生成
SQL、PySpark 和 Workflow 前，按需搜索并读取已注册项目文件，最终输出可追溯到文件和行号的 Workspace
证据。

**架构：** 使用应用侧 Function Tool，而不是 OpenAI 托管 File Search。模型首先接收最小 Workspace
身份信息和工具定义，再自主决定搜索、读取或解析哪些已注册文件；工具统一由 `ToolRegistry` 校验、执行和
审计。主流程不再预先计算或注入加权 `candidates`。完成证据收集后，仍由现有 Prompt、LiteLLM Gateway
和 Markdown Artifact 流程生成最终结果。

**技术栈：** Python 3.12.10、Pydantic 2、LiteLLM Chat Completions Function Calling、现有
Workspace Registry、`sqlparse`、tiktoken、PostgreSQL JSONB、Alembic、pytest、Ruff、Pyright。
本阶段不新增运行时依赖。

---

## 1. 为什么做这一阶段

阶段 10 的六份人工抽查暴露了两类问题：

1. 一次性加权 Context 只选择最多 8 个单元，遗漏了金额精度、Silver 到 Gold、AUTO CDC、Checkpoint、
   重试和超时等关键事实。
2. 即使部分事实已经进入 Prompt，模型也可能没有稳定遵守，且当前无法区分“没有检索到”和“检索到了但没有
   使用”。

阶段 11 只解决第一类问题，并为第二类问题提供完整证据。语义级 Artifact 硬约束校验不混入本阶段。

## 2. 选型结论

采用“受控本地工具 + 原生 Function Calling + 有界证据循环”。Function Calling 直接取代阶段 6
的 Workspace Context 加权选择，不把两套 Workspace 检索机制串联使用。

不采用以下方案：

1. **保留或继续修改静态业务权重：** 无法覆盖用户问题不断变化的跨文件检索需求，还会产生两套互相竞争的
   Workspace 证据来源。
2. **现在直接引入 LangGraph：** 工具契约和评估尚未稳定，会把检索问题与编排问题混在一起。
3. **使用 Prompt 文本解析 Thought/Action：** 格式脆弱，也不应保存或展示模型隐藏思维过程。
4. **使用 OpenAI 托管 File Search：** 项目文件必须留在本地，而且 DeepSeek 也需要使用同一套工具。
5. **调用 Shell 或 ripgrep 子进程：** 当前注册包不超过 20 MB，Python 确定性扫描足够，也更容易控制权限。

借鉴《Hello Agents》第 4 章和第 7 章的以下设计：

1. 统一 Tool 抽象和 Tool Registry。
2. 名称、描述、参数 Schema 和执行逻辑分离。
3. 使用原生 Function Calling，不依赖自由文本 Action 解析。
4. 把工具结果作为 Observation 交回模型。
5. 使用最大轮数、错误处理和完整日志避免无限循环。

本项目进一步增加严格 Pydantic 参数、路径沙箱、内容预算、结构化错误和证据审计。

这里不等于取消所有排序。只取消“按文件类别、Prompt 类型和人工业务权重预选 Context”的机制。工具内部
为了限制返回数量，仍使用轻量、确定性的稳定顺序：

1. `list_files` 按规范相对路径排序。
2. `search_text` 只返回真实文本命中，按完全短语命中、规范相对路径和行号排序。
3. `find_references` 使用标识符边界匹配，按规范相对路径和行号排序。
4. `inspect_sql_schema` 保持源 DDL 中表和字段的原始顺序。
5. 不计算业务相关性分数，不使用文件类别加权，也不做二次 Top-K Context 预选。

## 3. 第一版工具

| 工具 | 用途 | 核心输出 |
|---|---|---|
| `list_files` | 查看当前 Workspace 已注册文件 | 相对路径、类型、大小、Hash |
| `search_text` | 搜索字段、短语、数值和配置项 | 匹配文件、行号、上下文、Hash |
| `read_file` | 分段读取指定文件 | 带行号正文、范围、Hash、截断状态 |
| `inspect_sql_schema` | 检查已注册源 DDL | 表、字段、类型、约束、来源行号 |
| `find_references` | 查找表、字段或配置项的跨文件引用 | 按文件分组的精确引用位置 |

具体约束：

1. `search_text` 只接受普通文本，不接受模型提供的正则表达式。
2. `find_references` 使用标识符边界匹配，不把 `order_id` 错配到更长标识符中。
3. `read_file` 必须提供规范 POSIX 相对路径和明确行号范围。
4. `inspect_sql_schema` 只解析 Registry 已登记的 `source_ddl`。
5. 所有结果都返回 Workspace ID、版本、Source Hash、文件 Hash 和行号。
6. 工具结果仅做去重、截断和上述稳定排序，不经过阶段 6 的加权选择器。

## 4. 权限和预算

第一版只允许读取 `WorkspaceDefinition.sources` 中已经由 `project.yml` 注册并通过启动预检的文件。
不扫描未注册文件，也不读取 `upstream`、`.git`、`.env` 或工作区外内容。

固定代码常量如下，不放入 `.env`：

```text
WORKSPACE_TOOL_MAX_ROUNDS = 3
WORKSPACE_TOOL_MAX_CALLS = 6
WORKSPACE_TOOL_TIMEOUT_SECONDS = 5
WORKSPACE_TOOL_MAX_TOTAL_BYTES = 65536
WORKSPACE_TOOL_MAX_READ_LINES = 200
WORKSPACE_TOOL_MAX_SEARCH_RESULTS = 20
WORKSPACE_TOOL_MAX_CONTEXT_TOKENS = 8000
```

所有环境使用相同安全边界，因此这些值属于代码契约，不属于部署配置。

必须拒绝：

1. 绝对路径、反斜杠路径、`..` 和非规范路径。
2. 未注册文件、符号链接逃逸和跨 Workspace 路径。
3. 二进制、非 UTF-8、超大文件和不支持的文件类型。
4. Shell、任意 Python、写文件、删除、重命名、网络、数据库执行和 Databricks 操作。
5. 超过轮数、调用次数、行数、字节数、token 或耗时预算的请求。

## 5. 调用流程

```text
POST Chat Message
  -> 解析 Session、Prompt、Model 和 Workspace
  -> Workspace Tool Planning（只接收最小 Workspace 身份信息，不接收静态 candidates）
       -> 模型接收五个严格工具 Schema
       -> 第一轮要求至少调用一个工具
       -> 应用校验参数并执行只读工具
       -> 结构化结果作为 Tool Observation 返回
       -> 最多 3 轮、6 次调用
  -> 汇总 Workspace Evidence
  -> 按调用顺序去重、截断并生成证据 Context，不进行加权重排
  -> 官方 RAG 与专家模板按原流程独立检索
  -> 最终模型调用禁用工具，只生成 Markdown Artifact
  -> 保存 Assistant、文件证据、ModelCall 和 Trace
```

调用规则：

1. 仅在 Session 已绑定 Workspace 且 Prompt 声明 `use_workspace_context=true` 时启用工具循环。
2. 普通 `databricks_qa` 和 `knowledge_qa` 不调用 Workspace 工具。
3. 工具规划阶段只提供 Workspace ID、名称、版本、Source Hash、可用工具和用户请求；不注入
   `context.workspace.candidates`、官方 RAG 或专家模板。
4. 最终生成阶段才组合官方知识、专家模板和 Workspace Evidence。
5. Workspace Evidence 对项目字段、类型、业务口径和项目配置具有最高优先级。
6. 官方文档只决定 Databricks 产品行为；专家模板只提供默认方法和示例。
7. 工具参数错误会作为结构化 Observation 返回，允许模型在剩余轮次内修正。
8. 工具循环耗尽、预算超限或模型不支持工具时，终止本次项目型生成并返回
   `workspace_tool_unavailable`，不使用静态加权 Context 继续生成。
9. 最终 Artifact 仍只返回提案，不执行、不写回项目目录。
10. 阶段 10 的历史结果只用于离线对比，不在阶段 11 生产请求中重新执行旧加权选择器。

## 6. 模型协议

继续使用现有 LiteLLM Chat Completions，不迁移到单一供应商 API。

需要扩展内部模型协议以支持：

1. `tools`、`tool_choice` 和 `parallel_tool_calls=false`。
2. Assistant `tool_calls`。
3. `tool` role、`tool_call_id` 和结构化工具结果。
4. 一次响应包含零个、一个或多个 Tool Call。
5. 工具调用响应允许 `content=null`。
6. OpenAI 和 DeepSeek 使用相同内部类型与 Tool Schema。
7. 最终生成调用设置 `tool_choice=none`。

五个工具全部使用严格 JSON Schema，拒绝额外字段。模型返回的 JSON 参数必须先经过对应 Pydantic Model
验证，不能直接传给文件系统函数。

## 7. 证据与持久化

### PostgreSQL

新增 Alembic `0010_workspace_file_tools.py`，不增加独立工具表：

```text
model_calls
  call_phase          # workspace_tool_planning / artifact_generation
  tool_loop_id        # 同一 Chat Turn 的工具规划和最终生成分组
  tool_calls JSONB    # 参数、状态、证据元数据、耗时和错误，不保存完整文件正文

messages
  workspace_citations JSONB
```

`workspace_citations` 保存：

1. Workspace ID、版本和 Source Hash。
2. 相对路径、起止行和文件 Hash。
3. Tool Call ID、工具名和证据内容 Hash。
4. 是否截断。

完整项目正文仍只存在于本地 Workspace。数据库不复制文件全文。

### Trace 1.8

Trace 新增顶层 `tools`：

```text
tools
  loop_id
  status
  failure_reason
  rounds
  calls[]
    call_id
    tool_name
    arguments
    result
    evidence[]
    latency_ms
    error
  evidence_context_token_count
```

本地 Trace 保存实际交给模型的完整 Tool Result，继续脱敏并由 Git 忽略。数据库只保存可查询的摘要审计。
不保存模型隐藏思维过程。

## 8. API 变化

现有请求保持不变：

```text
POST /api/chat/sessions/{session_id}/messages
```

不增加让用户直接执行工具的 HTTP API，也不增加请求模式开关。

响应和历史消息增加：

```text
workspace_citations
context.workspace
  workspace_id
  version
  source_hash
context.workspace_tools
  status
  call_count
  evidence
```

新的 `context.workspace` 只保留 Workspace 身份与版本信息，不再返回 `candidates`、匹配分数或选择原因。
已保存的阶段 10 历史消息保持原样，不做数据回写。工具规划失败时返回结构化错误，不返回缺少 Workspace
证据的 Artifact。

## 9. 实施任务

### 任务 1：固定工具契约和安全常量

**新增：**

- `src/databricks_zh_expert/tools/types.py`
- `src/databricks_zh_expert/tools/constants.py`
- `src/databricks_zh_expert/tools/errors.py`
- `tests/unit/test_tool_types.py`

定义 `ToolSpec`、`ToolCall`、`ToolResult`、`ToolEvidence`、错误分类和固定预算。

### 任务 2：实现 Workspace 文件目录与访问策略

**新增：**

- `src/databricks_zh_expert/tools/workspace_catalog.py`
- `tests/unit/test_workspace_tool_catalog.py`

从 `WorkspaceDefinition.sources` 构建只读文件目录，统一完成路径、编码、大小、Hash 和 Workspace 身份校验。

### 任务 3：实现 list_files 和 read_file

**新增：**

- `src/databricks_zh_expert/tools/workspace_files.py`
- `tests/unit/test_workspace_file_tools.py`

返回稳定排序、带行号和可截断的结构化结果。

### 任务 4：实现 search_text 和 find_references

**新增：**

- `src/databricks_zh_expert/tools/workspace_search.py`
- `tests/unit/test_workspace_search_tools.py`

支持中文短语、ASCII 标识符、大小写归一化、跨文件引用和结果上限，不支持任意正则。

### 任务 5：实现 inspect_sql_schema

**新增：**

- `src/databricks_zh_expert/tools/sql_schema.py`
- `tests/unit/test_sql_schema_tool.py`

复用现有 `sqlparse` 和 Workspace DDL 契约，输出表、列、类型、约束与来源行号；解析失败返回结构化错误，
不猜测 Schema。

### 任务 6：实现 ToolRegistry、Executor 和 Evidence Builder

**新增：**

- `src/databricks_zh_expert/tools/registry.py`
- `src/databricks_zh_expert/tools/executor.py`
- `src/databricks_zh_expert/tools/evidence.py`
- `tests/unit/test_tool_registry.py`
- `tests/unit/test_tool_executor.py`
- `tests/unit/test_workspace_evidence.py`

统一注册五个工具，校验参数，执行预算，去重证据并生成最高 8,000 token 的 Workspace Evidence Context。
Evidence Builder 保持工具调用顺序，只去除重复证据并按预算截断，不再调用 Workspace 加权选择器或计算
业务相关性分数。

### 任务 7：扩展 LiteLLM Function Calling 协议

**修改：**

- `src/databricks_zh_expert/llm/client.py`
- `src/databricks_zh_expert/llm/litellm_client.py`
- `src/databricks_zh_expert/llm/gateway.py`
- `tests/unit/test_litellm_client.py`
- `tests/unit/test_model_gateway.py`

增加严格工具 Schema、Tool Call、Tool Message 和无文本响应支持。使用 Fake Completion 覆盖 OpenAI 和
DeepSeek 的统一归一化，不在业务代码中写供应商特例。

### 任务 8：接入 ChatService、数据库、API 和 Trace 1.8

**新增：**

- `src/databricks_zh_expert/tools/orchestrator.py`
- `alembic/versions/0010_workspace_file_tools.py`
- `tests/integration/test_workspace_tool_messages_api.py`

**修改：**

- `src/databricks_zh_expert/chat/service.py`
- `src/databricks_zh_expert/chat/context.py`
- `src/databricks_zh_expert/chat/repository.py`
- `src/databricks_zh_expert/chat/schemas.py`
- `src/databricks_zh_expert/db/models.py`
- `src/databricks_zh_expert/observability/model_trace.py`
- `src/databricks_zh_expert/api/chat.py`

实现有界工具循环、失败即停止、证据持久化、历史恢复和 Trace；移除 ChatService 对阶段 6 Workspace
加权选择器的生产调用，并停止在新响应中生成 `context.workspace.candidates`。

### 任务 9：建立固定文件检索评估

**新增：**

- `tests/evals/workspace_file_retrieval.yml`
- `src/databricks_zh_expert/tools/evaluation.py`
- `tests/unit/test_workspace_file_retrieval_eval.py`

**修改：**

- `src/databricks_zh_expert/workspace/cli.py`

覆盖：

1. Northwind 表和字段定位。
2. 金额精度与 HALF_UP 顺序。
3. Bronze、Silver、Gold 层级。
4. DMS 字段、AUTO CDC、Managed File Events 和 Checkpoint。
5. 日终调度、重试、超时、通知和保留策略。
6. 跨文件引用、同名字段、无结果和截断。
7. 绝对路径、`..`、未注册文件和跨 Workspace 拒绝。
8. 断言项目型请求不会调用旧 Workspace 加权选择器，工具证据不会经过业务权重重排。

### 任务 10：双模型真实验收和阶段收尾

1. 先运行全部离线检查。
2. 使用独立 Run ID 运行 `deepseek-v4-flash`。
3. 使用独立 Run ID 运行 `deepseek-v4-pro`。
4. 重新生成 SQL、PySpark、Workflow 六份代表性输出。
5. 保留所有 Session、Message、ModelCall、Trace、JSON、Markdown 和本地日志。
6. 直接使用已冻结的 `stage10-final-20260723` 结果作为控制组，比较证据覆盖、Hard/Soft、模型调用
   次数、token、延迟和人工问题数，不重新执行旧加权算法。
7. 不删除或覆盖阶段 9、阶段 10 及开发期间的任何验收数据。

## 10. 评估门禁

阶段开始实现前固定以下门禁：

1. 文件检索固定集 `Recall@5 >= 95%`。
2. 阶段 10 六个代表性 Case 的必需 Workspace 证据覆盖率为 `100%`。
3. 越权、路径穿越、未注册文件和预算超限测试拒绝率为 `100%`。
4. 跨 Workspace 内容泄漏为 `0`。
5. 每条最终 Workspace Citation 都能还原到文件、行号和 Hash。
6. 工具异常时返回 `workspace_tool_unavailable`，不生成缺少项目证据的 Artifact；普通非 Workspace
   请求行为不变。
7. 阶段 11 双模型端到端 Hard Pass 不低于阶段 10 对应基线。
8. 六份人工输出必须重新审核；如果证据已完整但答案仍违反事实，明确归类为“模型遵循或语义校验问题”，
   不再归咎于检索。

## 11. 验证指令

```powershell
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
uv run --locked databricks-zh-expert-workspaces evaluate-files
uv run --locked databricks-zh-expert-evals validate
```

真实模型运行必须在离线验证全部通过后进行。

## 12. 阶段边界

本阶段不做：

1. LangGraph、Plan-and-Solve 或 Reflection 编排。
2. AI 关键词提取、查询改写或上下文自动压缩。
3. 任意用户目录扫描、文件监听或 SQLite 工作区索引。
4. 用户上传文件和实时向量化。
5. Shell、代码执行、文件写入、网络搜索和 Databricks API 操作。
6. 官方 Databricks RAG 重构或专家模板内容重写。
7. SQL、PySpark 和 Workflow 语义级自动修复。
8. Web UI、桌面客户端、Word 或 PDF 导出。
9. 阶段 6 Workspace Context 业务权重调优或双轨生产检索。

## 13. 用户需要准备什么

用户不需要再准备 Workspace 文件。阶段 10 已冻结的 `northwind_psql` `2.0.0` 直接作为开发和评估输入。

用户只在任务 10 完成后审核 Flash 和 Pro 各一份 SQL、PySpark、Workflow，共六份输出。

## 14. 完成标准

1. 五个只读工具具有统一 Schema、Registry、预算、错误和审计。
2. 所有工具只能访问当前 Session 绑定 Workspace 的已注册文件。
3. OpenAI 和 DeepSeek 均能通过同一内部协议完成有界 Function Calling。
4. Chat API 无需新增请求参数即可自动获取 Workspace 文件证据。
5. 历史消息可以恢复当时的文件 Citation，Trace 可以查看完整工具输入输出。
6. 固定检索、安全和端到端评估达到第 10 节门禁。
7. 生产请求不再执行 Workspace Context 加权匹配，也不返回新的加权 `candidates`。
8. 阶段 10 冻结基线和全部历史数据保持不变。
9. Ruff、Pyright/Pylance、pytest、覆盖率和 Alembic 检查全部通过。

## 15. 参考

1. 《Hello Agents》第一章至第七章，重点参考第 4.2 节 ReAct 工具循环、第 7.4.5 节
   FunctionCallAgent 和第 7.5 节工具系统。
2. OpenAI Function Calling：
   `https://developers.openai.com/api/docs/guides/function-calling`
3. OpenAI Tools：
   `https://developers.openai.com/api/docs/guides/tools`
