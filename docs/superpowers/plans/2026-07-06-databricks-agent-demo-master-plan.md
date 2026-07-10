# Databricks 顾问型 Agent Demo Implementation Plan

> **给后续 agentic workers 的说明：** 如果后续要按本文执行开发，请先使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，再把每个阶段拆成独立、可测试、可提交的小任务。

**目标：** 构建一个本地运行的 Databricks 顾问型 Agent Demo，能够回答 Databricks 问题、检索预置 Databricks 知识库、生成 SQL/PySpark/工作流设计草案，并以 Markdown 形式输出可交付内容。

**架构：** 第一版采用“单体后端 + 简单 Web UI/API 调试”的结构，先把模型调用、会话保存、Prompt 模板、RAG 和 Markdown 交付物跑通。Agent 不直接操作 Databricks，不执行 SQL，不提交 Job，只负责生成建议、代码草稿、设计文档和引用来源。

**技术栈：** Python 3.12.10、FastAPI、LiteLLM、PostgreSQL、pgvector、SQLAlchemy 2.x、Alembic、psycopg 3、LlamaIndex、pytest、ruff、Markdown。

---

## 1. Demo 版产品边界

### 1.1 第一版只做什么

Demo 版聚焦“顾问型输出”，不是自动化执行平台。

第一版支持：

1. Databricks 相关问答。
2. 预置 Databricks 知识库检索问答。
3. Databricks SQL 草稿生成。
4. PySpark 代码草稿生成。
5. Bronze / Silver / Gold 工作流设计草案。
6. Markdown 交付物生成。
7. 会话历史保存。
8. OpenAI / DeepSeek 模型切换和基础调用日志。
9. 固定评估问题集。

### 1.2 第一版明确不做什么

第一版不支持：

1. 直接连接 Databricks Workspace。
2. 自动执行 SQL、Notebook 或 Job。
3. 自动修改 Unity Catalog 权限。
4. 多用户账号系统。
5. 企业级权限、审计、租户隔离。
6. 完整桌面客户端。
7. 复杂 LangGraph 多节点编排。
8. 实时联网搜索官方文档。
9. 用户手动上传文档和实时建索引。

### 1.3 Demo 成功标准

当 Demo 完成时，应该能完成以下演示流程：

1. 用户打开本地服务。
2. 用户选择 OpenAI 或 DeepSeek 模型配置。
3. 用户发起 Databricks 咨询问题。
4. 系统返回结构化 Markdown 回答。
5. 系统已经提前构建 Databricks 知识库索引。
6. 用户基于 Databricks 知识库提问。
7. 系统返回答案，并附带知识库来源引用。
8. 用户输入业务需求。
9. 系统生成 Databricks 工作流设计草案。
10. 用户要求生成 SQL 或 PySpark。
11. 系统输出带前置条件、参数说明、代码、注意事项和人工确认提示的草稿。

---

## 2. 总体架构

### 2.1 推荐架构

采用本地单体服务架构：

```text
用户 / 简单 Web UI / API Client
        |
        v
FastAPI Backend
        |
        +-- Chat API
        +-- Artifact API
        +-- Knowledge API
        +-- Model Config API
        |
        +-- Prompt Registry
        +-- LiteLLM Gateway
        +-- RAG Service
        +-- Databricks Template Library
        +-- Evaluation Runner
        |
        +-- PostgreSQL + pgvector
        |     +-- 会话、消息和 Artifact
        |     +-- 模型调用与评估记录
        |     +-- 知识库元数据、Chunk 和 Embedding
        |
        +-- Local File Storage
              +-- 预置知识库原始 Markdown / YAML
              +-- 生成的 Markdown 文件
```

### 2.2 核心设计原则

1. 所有模型访问都经过 LiteLLM Gateway。
2. 所有专业输出都走 Prompt Registry。
3. 所有面向用户的结果都先统一成 Markdown Artifact。
4. RAG 只负责补充上下文和引用来源，不负责决定业务逻辑。
5. Databricks 专业价值沉淀在模板库、检查清单、示例和评估集中。
6. LangGraph 等流程编排工具后置，等业务流程稳定后再引入。
7. PostgreSQL 统一保存应用运行数据和解析后的知识库索引，避免 Demo 同时维护关系数据库和独立向量数据库。
8. 预置知识库原文件是内容来源，保存在本地目录；PostgreSQL 保存文件路径、内容哈希、版本、Chunk、元数据和 Embedding。
9. Demo 初期优先使用 pgvector 精确检索；数据量和性能测试证明有必要后，再增加 HNSW 索引。
10. 如果未来 pgvector 成为明确瓶颈，可以引入 Qdrant 作为可重建的检索索引，但 PostgreSQL 仍保留权威元数据。

---

## 3. 阶段路线图

## 阶段 1：项目初始化与最小聊天后端

### 小目标

建立可持续开发的基础工程结构，并完成一个稳定的聊天 API。第一阶段不引入复杂 Agent，只保证服务能启动、能调用模型、能保存会话、能返回 Markdown 文本。

### 技术栈

1. Python 3.12.10。
2. uv 0.11.28。
3. FastAPI。
4. Pydantic。
5. pydantic-settings + python-dotenv。
6. PostgreSQL + pgvector。
7. SQLAlchemy 2.x。
8. Alembic。
9. psycopg 3。
10. LiteLLM。
11. pytest。
12. ruff。

### 产出

1. Python 项目结构。
2. 依赖管理文件。
3. 基础配置文件。
4. 健康检查接口。
5. 聊天接口。
6. 会话历史保存。
7. 模型调用日志。
8. 最小测试用例。
9. PostgreSQL + pgvector 的 Docker Compose 配置。
10. 初始 Alembic 迁移。
11. 本地运行说明。

### 建议目录

```text
databricks-zh-expert/
  src/
    databricks_zh_expert/
      main.py
      api/
      core/
      db/
      chat/
      llm/
  tests/
  docs/
  knowledge/
    databricks/
  data/
    artifacts/
  evals/
  alembic/
  docker-compose.yml
  pyproject.toml
  README.md
  .env.example
```

### 核心能力

1. 创建会话。
2. 发送消息。
3. 保存用户消息和模型回复。
4. 返回 Markdown 文本。
5. 记录模型名称、耗时、token 统计和错误信息。

### API 草案

```text
GET  /health
POST /api/chat/sessions
GET  /api/chat/sessions
GET  /api/chat/sessions/{session_id}
POST /api/chat/sessions/{session_id}/messages
```

### 数据表草案

```text
sessions
  id
  title
  created_at
  updated_at

messages
  id
  session_id
  role
  content
  artifact_type
  created_at

model_calls
  id
  session_id
  provider
  model
  prompt_tokens
  completion_tokens
  latency_ms
  success
  error_message
  created_at
```

### 数据库配置草案

```text
DATABASE_URL=postgresql+psycopg://databricks_agent:databricks_agent@localhost:5432/databricks_agent
POSTGRES_DB=databricks_agent
POSTGRES_USER=databricks_agent
POSTGRES_PASSWORD=
```

`.env.example` 只提供占位值，不提交真实密码。应用启动时检查数据库连接；Alembic 初始迁移负责启用 `vector` 扩展并创建阶段 1 所需业务表。

### 完成标准

用户可以通过 Docker Compose 启动 PostgreSQL + pgvector，执行 Alembic 迁移，并通过 API 完成一轮聊天；服务端可以保存历史消息并记录一次模型调用日志。

---

## 阶段 2：LiteLLM 模型网关

### 小目标

把业务代码和具体模型供应商解耦，但 Demo 版只支持 OpenAI 和 DeepSeek。

### 技术栈

1. LiteLLM。
2. pydantic-settings。
3. PostgreSQL。

### 核心能力

1. 支持 OpenAI 配置。
2. 支持 DeepSeek 配置。
3. 暂不支持 Claude、Gemini、Azure OpenAI 或其他模型供应商。
4. 支持固定模型白名单：`gpt5.5`、`gpt5.4mini`、`deepseek-v4-flash`、`deepseek-v4-pro`。
5. 开发调试默认使用 `deepseek-v4-flash`。
6. 支持默认模型。
7. 支持 temperature 配置。
8. 支持 OpenAI 和 DeepSeek 之间的 fallback 模型列表。
9. 支持 token 统计。
10. 支持错误日志。
11. 启动时校验配置的模型名是否在白名单内。

### 配置草案

```text
PYTHON_VERSION=3.12.10
DEFAULT_MODEL=deepseek-v4-flash
DEV_MODEL=deepseek-v4-flash
DEFAULT_TEMPERATURE=0.2
SUPPORTED_OPENAI_MODELS=gpt5.5,gpt5.4mini
SUPPORTED_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro
FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini
LITELLM_TIMEOUT_SECONDS=60
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

### 完成标准

业务服务只调用一个内部 `ModelGateway`，在 OpenAI 和 DeepSeek 之间切换模型时不需要改 Chat API、RAG 或代码生成模块。

---

## 阶段 3：Prompt Registry 和 Markdown Artifact

### 小目标

让系统输出从一开始就像“交付物”，而不是普通闲聊文本。

### 技术栈

1. Jinja2 或 Python 字符串模板。
2. Markdown。
3. Pydantic。

### Prompt 分类

1. `databricks_qa`：Databricks 问答。
2. `sql_generation`：Databricks SQL 生成。
3. `pyspark_generation`：PySpark 生成。
4. `workflow_design`：工作流设计。
5. `knowledge_qa`：基于预置 Databricks 知识库问答。
6. `proposal_generation`：提案或设计书草案。
7. `self_check`：输出自检。

### Artifact 类型

```text
answer
sql
pyspark
workflow_design
document_summary
proposal
checklist
```

### Markdown 输出规则

所有专业输出尽量包含：

1. 标题。
2. 适用场景。
3. 前置条件。
4. 方案或代码。
5. 注意事项。
6. 风险点。
7. 人工确认事项。
8. 引用来源，如果有 RAG 上下文。

### 完成标准

同一个 Chat API 可以根据用户意图选择不同 Prompt，并输出结构化 Markdown。

---

## 阶段 4：预置 Databricks 知识库 RAG

### 小目标

提前整理 Databricks 知识材料并构建向量索引，用户提问时只检索已经存在的知识库，不要求用户每次手动上传文档。

### 技术栈

1. LlamaIndex。
2. PostgreSQL。
3. pgvector。
4. SQLAlchemy 2.x。
5. Alembic。
6. psycopg 3。
7. Markdown。
8. YAML。

### 知识库来源

1. 人工整理的 Databricks 官方文档摘要。
2. Databricks SQL 模板。
3. PySpark 模板。
4. Bronze / Silver / Gold 设计模板。
5. Workflow 设计模板。
6. Unity Catalog 权限建议。
7. 成本优化检查清单。
8. 性能优化检查清单。

### 知识库目录草案

```text
knowledge/
  databricks/
    summaries/
    sql_templates/
    pyspark_templates/
    medallion_templates/
    workflow_templates/
    unity_catalog/
    cost_optimization/
    performance_optimization/
```

知识库原文件保存在 `knowledge/databricks/`。解析后的文档记录、Chunk、Embedding 和检索元数据统一写入 PostgreSQL，不再维护独立向量数据库的数据目录。

### 核心流程

```text
整理 Databricks 知识材料
  -> 保存为 Markdown / YAML
  -> 切分 chunk
  -> 生成 embedding
  -> 写入 PostgreSQL 的 kb_documents / kb_chunks
  -> 通过 pgvector 保存并检索 embedding
  -> 保存知识来源元数据
  -> 用户提问
  -> 检索相关 chunk
  -> 拼接上下文
  -> 模型生成答案
  -> 返回引用来源
```

### API 草案

```text
GET  /api/knowledge/sources
GET  /api/knowledge/sources/{source_id}
GET  /api/knowledge/index/status
POST /api/rag/query
```

### 元数据草案

```text
kb_documents
  id
  title
  category
  source_path
  content_hash
  version
  status
  chunk_count
  created_at
  updated_at

kb_chunks
  id
  document_id
  chunk_index
  content
  source_ref
  metadata JSONB
  embedding VECTOR(<固定维度>)
  embedding_model
  created_at

kb_ingestion_runs
  id
  status
  document_count
  chunk_count
  error_message
  started_at
  completed_at
```

Embedding 模型与聊天模型分开配置。`kb_chunks.embedding` 的维度在选定 Embedding 模型后通过迁移固定；同一个向量索引内不得混用不同维度，切换 Embedding 模型时需要重建索引。

### 完成标准

Demo 启动前或初始化时已经构建好 Databricks 知识库索引。用户不需要上传文档，也可以基于预置知识库提问，回答里能看到来源引用。

### 后置能力

用户上传项目文档、导入本地文件夹、PDF / Word 解析和用户文档索引都放到后续版本，不进入第一版 Demo。

---

## 阶段 5：Databricks 专家模板库

### 小目标

把项目的专业价值沉淀为可复用知识资产。

### 技术栈

1. Markdown。
2. YAML。
3. Prompt Registry。

### 知识资产分类

1. 官方文档摘要。
2. 常用 Databricks SQL 模板。
3. 常用 PySpark 模板。
4. Bronze / Silver / Gold 设计模板。
5. Workflow 设计模板。
6. Unity Catalog 权限建议模板。
7. 成本优化检查清单。
8. 性能优化检查清单。
9. 常见项目交付文档结构。

### 推荐目录

```text
knowledge/
  databricks/
    summaries/
    sql_templates/
    pyspark_templates/
    medallion_templates/
    workflow_templates/
    unity_catalog/
    cost_optimization/
    performance_optimization/
```

### 完成标准

Agent 在回答时可以引用这些模板，使输出更像真实项目交付内容，而不是泛泛解释。

---

## 阶段 6：代码生成模块

### 小目标

支持生成 Databricks SQL、PySpark 和 Notebook 草稿。

### 技术栈

1. Prompt Registry。
2. LiteLLM Gateway。
3. Markdown Artifact。

### 输出结构

每次生成代码都包含：

1. 使用场景。
2. 输入参数。
3. 前置条件。
4. 代码。
5. 代码说明。
6. 注意事项。
7. 人工确认提示。

### 代码生成范围

第一版支持：

1. SELECT / JOIN / 聚合 SQL。
2. Delta 表读写 SQL。
3. 基础性能优化建议。
4. PySpark 读取、清洗、转换、写入 Delta。
5. Notebook Markdown 大纲。

第一版不支持：

1. 自动连接数据库验证 SQL。
2. 自动运行 PySpark。
3. 自动创建 Databricks Notebook。
4. 自动部署 Job。

### 完成标准

给定一个业务需求，系统能生成可人工审查的 Databricks SQL 或 PySpark 草稿。

---

## 阶段 7：工作流设计模块

### 小目标

输入业务需求，输出固定结构的 Databricks 工作流设计草案。

### 技术栈

1. Prompt Registry。
2. Databricks 模板库。
3. Markdown Artifact。

### 输出结构

```text
1. 需求理解
2. 数据源假设
3. Bronze 层设计
4. Silver 层设计
5. Gold 层设计
6. Notebook 拆分
7. Job 依赖关系
8. 调度建议
9. 监控点
10. 风险点
11. 后续确认事项
```

### 完成标准

输入“设计一个每日销售分析 Workflow”这类需求后，系统可以输出一份结构完整、能继续修改成设计书的 Markdown 草案。

---

## 阶段 8：Markdown 文档生成

### 小目标

将聊天回答、方案、代码和工作流设计统一沉淀为 Markdown 文档。

### 技术栈

1. Markdown。
2. FastAPI 文件下载接口。
3. PostgreSQL 元数据。

### 核心能力

1. 将单次回答保存为 Markdown。
2. 将一个会话整理为 Markdown 文档。
3. 支持设计书草案。
4. 支持提案草案。
5. 支持作业设计书草案。
6. 支持表定义书草案。

### API 草案

```text
POST /api/artifacts
GET  /api/artifacts
GET  /api/artifacts/{artifact_id}
GET  /api/artifacts/{artifact_id}/download
```

### 完成标准

用户可以把一次生成结果保存成 Markdown，并下载或复制到后续文档流程中。

---

## 阶段 9：固定评估集

### 小目标

不要等产品复杂后再评估，从 Demo 期就开始固定回归问题。

### 技术栈

1. pytest。
2. YAML 或 JSON。
3. LiteLLM Gateway。
4. 简单评分脚本。

### 初始评估问题

1. 设计一个每日销售分析 Workflow。
2. 生成 Bronze / Silver / Gold 表设计。
3. 生成 PySpark 清洗代码。
4. 解释 Unity Catalog 权限设计。
5. 优化一个慢 SQL。
6. 根据预置 Databricks 知识库回答字段治理或权限设计问题。
7. 为 Delta 表设计数据质量检查。
8. 生成一份 Databricks 项目提案草案。

### 评估维度

1. 输出结构是否完整。
2. 是否符合 Databricks 场景。
3. 是否有明确前置条件。
4. 是否有风险和人工确认提示。
5. 如果使用 RAG，是否包含引用来源。
6. 代码是否避免声称已执行或已验证。

### 完成标准

每次修改 Prompt、模型配置或 RAG 流程后，可以跑一次固定评估集，快速发现输出质量退化。

---

## 阶段 10：简单 Web UI

### 小目标

为 Demo 提供一个轻量可演示界面。

### 技术栈候选

优先方案：

1. React。
2. Vite。
3. TypeScript。
4. Tailwind CSS 或普通 CSS。
5. Markdown 渲染组件。

简化方案：

1. FastAPI Jinja2 模板。
2. 原生 HTML/CSS/JavaScript。

### 第一版页面

1. 聊天页面。
2. 知识库状态页面。
3. 模型配置页面。
4. 会话历史页面。
5. Markdown 预览区域。

### 完成标准

不用 Postman 或 curl，也能完整演示聊天、预置 Databricks 知识库 RAG 问答和 Markdown 输出。

---

## 阶段 11：LangGraph 后置引入

### 小目标

等核心能力稳定后，再用 LangGraph 固化流程。

### 技术栈

1. LangGraph。
2. 现有 ModelGateway。
3. 现有 RAG Service。
4. 现有 Prompt Registry。

### 候选流程

```text
理解需求
  -> 判断任务类型
  -> 检查缺失信息
  -> 检索预置知识库或模板
  -> 生成方案
  -> 生成代码或设计文档
  -> 自检
  -> 输出 Markdown Artifact
```

### 引入条件

满足以下条件后再引入：

1. Chat API 稳定。
2. RAG 稳定。
3. Prompt 模板稳定。
4. 输出结构稳定。
5. 评估集已经存在。

### 完成标准

LangGraph 不改变用户可见能力，只把已经验证过的流程变得更可控、更容易调试。

---

## 4. 推荐优先级

### 最高优先级

1. FastAPI 后端骨架。
2. LiteLLM 模型网关。
3. PostgreSQL 会话保存。
4. Prompt Registry。
5. Markdown Artifact 输出。

### 第二优先级

1. 预置 Databricks 知识库 RAG。
2. Databricks 模板库。
3. SQL / PySpark 生成。
4. 工作流设计输出。

### 第三优先级

1. 固定评估集。
2. 简单 Web UI。
3. Markdown 文件下载。
4. LangGraph 流程固化。

### 暂缓

1. 桌面客户端。
2. Word 导出。
3. PDF 导出。
4. 多用户系统。
5. Databricks API 直连。
6. 企业权限与审计。

---

## 5. 建议的开发顺序

后续开发只按 11 个阶段推进，不再额外使用“第几个 Demo”的并行分组。

1. 阶段 1：项目初始化与最小聊天后端。
2. 阶段 2：LiteLLM 模型网关。
3. 阶段 3：Prompt Registry 和 Markdown Artifact。
4. 阶段 4：预置 Databricks 知识库 RAG。
5. 阶段 5：Databricks 专家模板库。
6. 阶段 6：代码生成模块。
7. 阶段 7：工作流设计模块。
8. 阶段 8：Markdown 文档生成。
9. 阶段 9：固定评估集。
10. 阶段 10：简单 Web UI。
11. 阶段 11：LangGraph 后置引入。

---

## 6. 后续需要进一步细化的小计划

后续建议按以下顺序继续拆小计划：

1. 项目初始化与最小聊天后端计划。
2. LiteLLM 模型网关计划。
3. Prompt Registry 和 Markdown Artifact 计划。
4. 预置 Databricks 知识库 RAG 计划。
5. Databricks 专家模板库计划。
6. 代码生成模块计划。
7. 工作流设计模块计划。
8. Markdown 文档生成计划。
9. 固定评估集计划。
10. 简单 Web UI 计划。
11. LangGraph 后置引入计划。

---

## 7. 风险和取舍

### 风险 1：过早引入复杂 Agent 框架

如果太早引入 LangGraph、多 Agent 或复杂工具调用，Demo 会被框架复杂度拖慢。

当前取舍：先做稳定的“生成与检索管线”，等流程稳定后再编排。

### 风险 2：RAG 文档质量不足

如果知识库材料太散，RAG 只会把无关内容拼进上下文。

当前取舍：先使用少量高质量 Databricks 材料和自己的模板库，验证输出质量。

### 风险 3：代码生成被误解为可直接执行

Agent 生成的 SQL 和 PySpark 可能存在环境差异，不能默认可执行。

当前取舍：所有代码输出必须包含前置条件、人工确认提示和注意事项，不声称已经运行验证。

### 风险 4：Demo 范围膨胀

文档导出、桌面端、多用户、Databricks API 直连都很容易吸引注意力。

当前取舍：第一版只保证本地顾问输出能力，不做执行型系统。

### 风险 5：过早拆分关系数据库和向量数据库

如果同时使用 PostgreSQL 和 Qdrant，需要处理双写、删除同步、版本一致性和备份恢复，会明显增加 Demo 复杂度。

当前取舍：第一版统一使用 PostgreSQL + pgvector。只有在真实数据量和性能测试证明 pgvector 不满足需求时，才把 Qdrant 作为可重建的派生索引引入。

### 风险 6：Embedding 模型切换导致索引不兼容

不同 Embedding 模型的向量维度和语义空间可能不同，不能把它们直接写入同一个索引并混合检索。

当前取舍：聊天模型和 Embedding 模型独立配置；第一版固定一个 Embedding 模型、维度和距离算法，切换模型时全量重建预置知识库索引。

---

## 8. 近期最推荐的下一步

下一步建议先细化“阶段 1：项目初始化与最小聊天后端计划”，目标是拿到第一个可以运行的 FastAPI 后端。

这个小计划应该覆盖：

1. 项目目录。
2. 依赖文件。
3. 配置加载。
4. 健康检查接口。
5. 聊天接口。
6. PostgreSQL 会话保存与 Alembic 迁移。
7. 模型调用日志。
8. 测试框架。
9. 本地启动命令。
10. README。

完成这个小计划后，再继续拆 LiteLLM 模型网关。

阶段 1 的详细设计和实施步骤见：

1. `docs/superpowers/specs/2026-07-10-stage-1-backend-design.md`。
2. `docs/superpowers/plans/2026-07-10-stage-1-backend-plan.md`。
