# Databricks 顾问型 Agent Demo Implementation Plan

> **给后续 agentic workers 的说明：** 如果后续要按本文执行开发，请先使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，再把每个阶段拆成独立、可测试、可提交的小任务。

**目标：** 构建一个本地运行的 Databricks 顾问型 Agent，能够回答 Databricks 问题、检索预置 Databricks 知识库和受控 Workspace 文件、生成 SQL/PySpark/工作流设计草案，并以 Markdown 形式输出可交付内容。

**架构：** 采用本地单体后端和 API 调试优先的结构。阶段 1 至阶段 9 已完成模型调用、会话保存、Prompt、RAG、专家模板、Workspace 上下文、Markdown 交付物和固定评估；后续先重建更真实的 Workspace 基准，再增加只读文件检索与工具系统，用 LangGraph 编排复杂顾问流程，最后补充 AI 关键词提取和上下文自动压缩。Agent 不直接操作 Databricks，不执行 SQL，不提交 Job，只负责生成建议、代码草稿、设计文档和引用来源。桌面客户端后置。

**技术栈：** Python 3.12.10、FastAPI、LiteLLM、PostgreSQL、pgvector、SQLAlchemy 2.x、Alembic、
psycopg 3、OpenAI Embeddings、httpx、Beautiful Soup、markdown-it-py、Pydantic、SQL 结构化解析、
受控本地文件检索、LangGraph（阶段 12）、结构化 AI 查询理解、token-aware 上下文压缩、pytest、Ruff、
Pyright、Markdown。

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
6. 本项目不建设浏览器前端；开发调试使用 OpenAPI/Swagger 或 API Client，最终用户界面只考虑桌面客户端。
7. 基础 Demo 不包含复杂 LangGraph 多节点编排，阶段 12 在核心能力和评估稳定后引入。
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
11. 系统输出使用项目字段或明确假设、带必要注释且可人工审查的代码草稿。

---

## 2. 总体架构

### 2.1 推荐架构

采用本地单体服务架构：

```text
用户 / API Client / 最终桌面客户端
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
        +-- Workspace Registry / Context Provider
        +-- Workspace File Retrieval / Tool Registry
        +-- Generation Orchestrator
        |     +-- Direct Orchestrator
        |     +-- LangGraph Orchestrator
        +-- Evaluation Runner
        |
        +-- PostgreSQL + pgvector
        |     +-- 会话、消息和 Artifact
        |     +-- 模型调用与评估记录
        |     +-- 知识库元数据、Chunk 和 Embedding
        |
        +-- Local File Storage
              +-- 预置知识库原始 Markdown / YAML
              +-- 注册且受控的项目工作区
              +-- 用户提供的项目事实文件
              +-- 程序生成的 Markdown 交付物
              +-- SQLite 可重建工作区索引（桌面端阶段）
```

### 2.2 核心设计原则

1. 所有模型访问都经过 LiteLLM Gateway。
2. 所有专业输出都走 Prompt Registry。
3. 所有面向用户的结果都先统一成 Markdown Artifact。
4. RAG 只负责补充上下文和引用来源，不负责决定业务逻辑。
5. Databricks 专业价值沉淀在模板库、检查清单、示例和评估集中。
6. 当前直接生成流程始终保留为快速路径和评估控制组；LangGraph 只编排需要分支、循环、人工确认或多次工具调用的复杂任务。
7. PostgreSQL 统一保存应用运行数据和解析后的知识库索引，避免 Demo 同时维护关系数据库和独立向量数据库。
8. 预置知识库原文件是内容来源，保存在本地目录；PostgreSQL 保存文件路径、内容哈希、版本、Chunk、元数据和 Embedding。
9. Demo 初期优先使用 pgvector 精确检索；数据量和性能测试证明有必要后，再增加 HNSW 索引。
10. 如果未来 pgvector 成为明确瓶颈，可以引入 Qdrant 作为可重建的检索索引，但 PostgreSQL 仍保留权威元数据。
11. 每次修改 Python 代码后，完成当前任务前必须运行 Ruff 格式检查、Ruff lint、Pyright 和 pytest；仅修改 Markdown 等文档时不强制运行 Pyright 和 pytest。
12. 具体项目的源代码、DDL 和配置始终以用户本地工作区文件为准；数据库只保存可重建索引和调用审计。
13. 阶段 10 和阶段 11 先使用 Git 内置、人工校订的 Northwind Workspace 验证文件检索；最终桌面端再实现本地文件夹选择、增量扫描和 SQLite 工作区索引。
14. Workspace 文件检索默认只读，只能访问已注册根目录；不得读取密钥文件、越过根目录、执行命令或修改项目文件。
15. Workspace、检索算法、Prompt、模型或编排流程发生实质变化后，必须重新运行阶段 9 固定评估，并保留旧数据集、结果、Trace 和日志作为历史基线。
16. Agent 可审计性来自结构化计划、工具请求、工具结果、节点状态和最终输出，不持久化模型隐藏思维过程。
17. AI 提取的关键词只用于查询扩展、过滤和排序，不替代用户原问题，也不能作为新的项目事实。
18. 上下文压缩只生成可追溯的派生摘要；原始消息、来源、代码、业务公式、约束和引用不得被覆盖或删除。

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
13. Pyright。

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
6. 每次消息请求可指定固定业务模型别名，省略时使用默认模型。
7. 支持全局 temperature 配置；模型不支持自定义值时不发送该参数。
8. 支持 OpenAI 和 DeepSeek 之间的 fallback 模型列表。
9. 支持 token 统计。
10. 支持 Trace 1.2 调用日志，并保留脱敏后的供应商原始错误。
11. 启动时校验配置的模型名是否在白名单内。

### 配置草案

```text
PYTHON_VERSION=3.12.10
DEFAULT_MODEL=deepseek-v4-flash
FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini
DEFAULT_TEMPERATURE=0.2
MODEL_REQUEST_TIMEOUT_SECONDS=60
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

四个业务别名、供应商和实际 LiteLLM ID 固定在代码模型目录中；默认模型和 fallback 顺序由各环境
分别配置。

### 完成标准

业务服务只调用一个内部 `ModelGateway`；Chat API 可按请求选择业务模型别名，切换 OpenAI、DeepSeek 或 fallback 顺序时不需要修改 RAG、代码生成等下游模块。

---

## 阶段 3：Prompt Registry 和 Markdown Artifact

### 小目标

让系统输出从一开始就像“交付物”，而不是普通闲聊文本。

### 技术栈

1. Jinja2 固定版本模板。
2. markdown-it-py 和 CommonMark AST 校验。
3. Pydantic API 契约。

### Prompt 分类

1. `databricks_qa`：Databricks 问答。
2. `sql_generation`：Databricks SQL 生成。
3. `pyspark_generation`：PySpark 生成。
4. `workflow_design`：工作流设计。
5. `document_summary`：当前会话文档或文本摘要。
6. `knowledge_qa`：基于预置 Databricks 知识库问答，阶段 4 前注册但不可用。
7. `proposal_generation`：提案或设计书草案。
8. `self_check`：输出自检。

消息请求通过可选 `prompt` 别名显式选择任务；省略时使用 `databricks_qa`。阶段 3 不做自动意图分类。

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

五类文档型 Artifact 使用唯一 H1 和固定顺序的 H2 章节；SQL 与 PySpark 直接输出带简短注释的
`sql` 或 `python` 代码围栏，不强制标题和长文档章节。模型输出由 CommonMark AST 直接校验，
格式不合格时返回错误，不自动修复或再次调用模型。

文档型专业输出按任务包含：

1. 标题。
2. 适用场景。
3. 前置条件。
4. 方案或代码。
5. 注意事项。
6. 风险点。
7. 人工确认事项。
8. 引用来源，如果有 RAG 上下文。

### 完成标准

1. `GET /api/prompts` 返回固定 Prompt 目录，不暴露模板正文或路径。
2. 同一个 Chat API 接受可选 Prompt 别名并输出结构化 Markdown Artifact。
3. `knowledge_qa` 在阶段 4 前明确返回不可用错误。
4. `model_calls` 保存 Prompt、Artifact 和结构校验审计字段。
5. Trace 1.3 保存实际 system message、Prompt 元数据和 Artifact 校验结果。

---

## 阶段 4：预置 Databricks 知识库 RAG

### 小目标

从受控 Databricks 官方来源离线构建本地知识索引。用户提问时只检索已经构建的预置知识库，不要求用户
上传文档，也不在聊天请求中实时抓取和建索引。

### 技术栈

1. PostgreSQL + pgvector。
2. SQLAlchemy 2.x + Alembic + psycopg 3。
3. OpenAI `text-embedding-3-small`，固定 1536 维。
4. httpx。
5. Beautiful Soup + markdownify。
6. markdown-it-py + tiktoken。
7. YAML 官方目录配置，只保存两个固定 `llms.txt` 入口。

阶段 4 不引入 LlamaIndex。同步事务、Alembic schema、混合检索、审计和 ChatService 集成均使用项目现有
边界显式实现；未来确实需要复杂 retriever 或 reranker 时再重新评估。

### 知识库来源

1. `https://docs.databricks.com/llms.txt`：全量发现并同步目录当前列出的全部唯一
   `docs.databricks.com` 通用文档页面。
2. `https://docs.databricks.com/api/llms.txt`：全量发现并同步目录当前列出的全部唯一 REST API 页面。

不再维护通用文档 URL、API module 或 operation 白名单。全量范围以每次同步时两个官方目录的实时内容为准，
目录中新增的站内页面自动进入同步；旧页面只有连续两次成功读取同一官方目录都不存在时才标记 disabled，
目录失败不累计缺失次数。目录列出的站外链接以 `catalog_link` 保存标题、摘要和 URL；普通文档正文中的站外
链接保留链接文字和 URL。两类站外链接都不抓取目标正文。全量不表示递归爬站；Agent Skills、Sitemap 和
社区站点正文不进入阶段 4。

### 知识库目录草案

```text
knowledge/
  databricks/
    sources.yml
```

仓库只保存两个官方目录配置、代码和少量测试 fixture，不提交批量官方正文。原始 HTML 和两个 `llms.txt` 不
持久化；规范化完整 Markdown、Chunk 正文、Embedding 和同步运行统一写入 PostgreSQL。

### 核心流程

```text
两个固定官方目录
  -> llms.txt / api/llms.txt 全量发现和站内 URL 去重
  -> 条件 GET 抓取官方 HTML / Markdown 正文
  -> 规范化 Markdown
  -> 内容哈希判断是否变化
  -> 标题感知 token chunk
  -> OpenAI Embedding
  -> PostgreSQL 单文档事务性发布
  -> 用户提问
  -> pgvector 精确候选 + PostgreSQL 全文候选
  -> RRF 融合和上下文预算
  -> 现有 ModelGateway 生成中文答案
  -> 保存 assistant message 与结构化官方引用
```

### API 草案

```text
GET  /api/knowledge/index/status
POST /api/chat/sessions/{session_id}/messages
     prompt=knowledge_qa
```

知识同步只通过开发者 CLI `databricks-zh-expert-kb sync` 发起，不开放 HTTP 写接口。
同步不区分白名单或其他范围模式；`--force` 只控制是否强制重建，不改变来源范围。

### 元数据草案

```text
kb_documents
  id
  source_key
  source_kind
  title
  category
  source_url
  canonical_url
  normalized_content
  content_hash
  source_version
  status
  chunk_count
  missing_sync_count
  missing_since_at

kb_chunks
  id
  document_id
  chunk_index
  heading_path
  content
  source_ref
  metadata JSONB
  embedding VECTOR(1536)
  embedding_model
  search_vector TSVECTOR

kb_ingestion_runs
  id
  status
  manifest_hash
  embedding_model
  embedding_dimensions
  discovered_count
  changed_count
  skipped_count
  failed_count
  chunk_count
  error_summary JSONB
  started_at
  completed_at

messages
  source_citations JSONB NULL
```

阶段 4 只新增三张知识表。检索候选、排名和分数写入 Trace 1.4，不增加检索审计表。assistant message 保存
引用快照，因此重新打开历史会话仍能展示当时的官方来源。

Embedding 模型与聊天模型分开配置。DeepSeek 聊天仍使用 OpenAI 查询 Embedding，因此用户问题的数据流必须
明确说明。同一个向量索引不得混用模型或维度，切换时必须显式重建。Demo 使用精确 cosine 检索，不创建
HNSW 或 IVFFlat。

### 完成标准

1. 开发者可用同一个 CLI 全量构建并增量更新两个官方目录当前列出的全部站内文档。
2. `knowledge_qa` 通过现有 Chat API 使用 OpenAI 或 DeepSeek 聊天并返回结构化官方引用。
3. 发送消息和重新打开历史会话时都能恢复相同引用。
4. 没有索引或没有相关上下文时不调用聊天模型。
5. Trace 1.4 可查看实际 RAG 上下文、排名和分数。
6. 中文固定检索评估达到 `Recall@5 >= 80%`。
7. 所有现有会话、消息、模型调用和阶段 3 验收数据不被清理。
8. 站外链接保留在 Markdown 中，但同步过程不抓取站外正文。
9. 目录中消失的页面经过两次成功目录快照确认后才 disabled；目录失败不改变缺失状态。

### 阶段 4 追加任务

任务 1 至任务 7 完成首版有限来源 RAG；任务 8 已移除页面、module 和 operation 白名单，并完成两个官方
目录的真实全量同步、目录站外链接索引、增量复验和质量门禁。当前索引包含 Docs 目录 225 个来源（其中 4 个
`catalog_link`）、API 1,034 篇，共 1,259 篇 active 文档和 17,712 个 Chunk；固定 28 题评估
`Recall@5 = 92.86%`，阶段 4 已达到完成标准，用户已确认直接提交当前分支。

### 后置能力

中文专家模板、Agent Skills 和项目经验在阶段 5 增加。用户上传、PDF / Word、多租户索引、HNSW、检索审计表、
定时同步、reranker 和 Databricks MCP / AI Search 均放到后续版本。

详细设计和逐任务计划见：

1. `docs/superpowers/specs/2026-07-12-stage-4-prebuilt-databricks-rag-design.md`。
2. `docs/superpowers/plans/2026-07-12-stage-4-prebuilt-databricks-rag-plan.md`。

---

## 阶段 5：Databricks 专家模板库

### 当前状态

实现与真实验收已完成。37 个模板和 121 个 Chunk 已同步，固定评估 Recall@3 为 96.67%，两次
`deepseek-v4-flash` 冒烟成功，验收会话与 Trace 1.5 已保留。

### 小目标

在阶段 4 官方事实 RAG 之外，增加可版本化、可检索、可审计的项目方法、架构取舍、代码模式、检查清单和
交付结构，使回答更接近真实项目交付。

### 技术栈

1. Markdown。
2. YAML。
3. PostgreSQL + pgvector。
4. Prompt Registry。
5. OpenAI Embedding。

### 已确认边界

1. 使用“通用核心层 + AWS 零售销售项目覆盖层”。
2. 同一 Git 仓库、同一 PostgreSQL、独立专家模板表，不混入 `kb_*` 官方知识表。
3. 模板使用 Markdown + YAML Front Matter，Profile 使用 YAML 清单。
4. 会话级 `expert_profile` 默认为 `generic`；具体模板由系统自动选择。
5. 项目架构覆盖 S3 日批、RDS PostgreSQL、AWS DMS、S3 Parquet、Auto Loader 和 Kinesis。
6. Medallion 转换使用 Lakeflow Spark Declarative Pipelines 的稳定能力，不采用 Preview 功能。
7. 模板分为 blueprint、decision guide、code pattern、checklist、deliverable 五类。
8. 第一版约 37 个短而具体的专家资产。
9. 官方事实与项目经验分别检索，官方引用只来自阶段 4 数据。
10. 模板候选、最终选择、版本、Profile 和继承关系写入 `model_calls` 与 Trace 1.5。

### 数据流

```text
Git Markdown / YAML
-> 严格 Registry 校验
-> 显式增量同步与 OpenAI Embedding
-> expert_templates / expert_template_chunks
-> Profile 与 Prompt 预过滤
-> 向量 + 全文混合检索
-> 与阶段 4 官方上下文组合
-> 模型生成 Artifact
-> model_calls 与 Trace 1.5 审计
```

### 完成标准

1. generic 与 retail_sales_demo 两个 Profile 可用且会话内不可变。
2. 专家模板可原子同步、版本化和检索，不污染官方来源引用。
3. 固定模板评估达到 Recall@3 >= 90%，跨 Profile 误用为 0。
4. Agent 能结合官方事实与专家模板生成代码、Workflow、提案和检查清单。
5. 真实验收数据和 Trace 保留，Ruff、Pyright、pytest、覆盖率和 Alembic 全部通过。

详细设计和逐任务计划见：

1. `docs/superpowers/specs/2026-07-16-stage-5-databricks-expert-template-library-design.md`。
2. `docs/superpowers/plans/2026-07-16-stage-5-databricks-expert-template-library-plan.md`。

---

## 阶段 6：代码生成模块

### 当前状态

阶段 6 的八个任务已经完成实现、固定评估和真实冒烟验收。

### 小目标

让 Databricks DDL、Mapping CSV、SQL、PySpark 和 Python source Notebook 草稿能够使用具体项目的需求、
业务规则和源 Schema，并把所有目标层设计明确保存为未确认 proposal；同时为最终本地工作区模式保留稳定接口。

### 技术栈

1. Prompt Registry。
2. LiteLLM Gateway。
3. Markdown Artifact。
4. PyYAML + Pydantic。
5. tiktoken。
6. Git 内置项目工作区。

### 已确认边界

1. 创建一个真实目录结构的 `retail_sales_demo` 示例工作区。
2. `expert_profile` 表示方法论，`workspace_id` 表示具体项目，两者保持独立。
3. 阶段 6 只读取清单显式列出的内置文件，不支持任意目录和上传。
4. Workspace 文件是项目事实来源；PostgreSQL 只保存 ID、版本、Hash 和选择审计。
5. 项目文件选择使用确定性关键词和 token 预算，不调用模型或 Embedding。
6. SQL 与 PySpark 直接输出代码围栏和必要注释，不强制长篇章节。
7. Notebook 输出为 Python source 格式草稿，不创建 `.py` 或 `.ipynb` 文件。
8. 不执行、编译、部署或验证任何生成代码。
9. 完整本地扫描、文件监听和 SQLite 索引放到后续桌面工作区阶段。

### 示例项目内容

1. S3 POS 日批。
2. RDS PostgreSQL 经 AWS DMS 写入 S3 Parquet。
3. Kinesis 电商事件流。
4. `project.yml`、需求文档和业务规则。
5. RDS PostgreSQL、POS Parquet 和 Kinesis 三份源 Schema DDL。
6. 不包含预制 Bronze、Silver、Gold DDL、Mapping、Notebook 或目标表定义。

### 代码生成范围

第一版支持：

1. Databricks DDL 提案。
2. 固定表头的源到目标 Mapping CSV 提案。
3. SELECT、JOIN、聚合和 Delta 表读写 SQL。
4. PySpark 读取、清洗、转换和写入 Delta。
5. Python source 格式 Notebook 草稿。
6. 有工作区时使用实际源表、源字段、需求和规则。
7. 无工作区时继续生成明确标注假设的通用草稿。

第一版不支持：

1. 自动连接数据库验证 SQL。
2. 自动运行 PySpark。
3. 自动创建 Databricks Notebook。
4. 自动部署 Job。
5. 用户本地目录扫描、SQLite 项目索引和文件监听。
6. 严格 SQL / Python AST 阻断或自动修复。

### 完成标准

1. DDL、Mapping、SQL、PySpark 和 Notebook 五类 Prompt 可以使用内置零售项目上下文。
2. 固定 Workspace Context 评估达到 `Recall@5 = 100%`，高于 90% 门禁。
3. `model_calls` 和 Trace 1.7 可以恢复实际工作区版本、Hash、相对文件选择和 proposal 状态。
4. 四类真实生成冒烟均成功并保留验收数据；一次 DeepSeek 超时及其 OpenAI fallback 也完整保留。
5. 没有引入 SQLite、任意目录扫描、代码执行或 Databricks 连接。

详细设计和逐任务计划见：

1. `docs/superpowers/specs/2026-07-17-stage-6-project-aware-code-generation-design.md`。
2. `docs/superpowers/plans/2026-07-17-stage-6-project-aware-code-generation-plan.md`。

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

1. `workflow_design@1.1.0` 可以结合官方 RAG、专家模板和 Workspace 事实输出固定 11 章 Markdown 提案。
2. Workspace 工作流固定评估达到 `Recall@5=100%`，没有历史提案上下文泄漏。
3. 三类 `deepseek-v4-flash` 真实冒烟均成功，数据库和 Trace 1.7 完整保留引用、模板选择、Workspace 选择和
   `project_fact_status=proposal`。
4. 没有新增数据库迁移、Workflow CRUD、Databricks 连接、代码执行或部署能力。

详细计划见：

`docs/superpowers/plans/2026-07-18-stage-7-workflow-design-plan.md`。

---

## 阶段 8：Markdown 文档生成

### 状态

跳过独立实施。当前模型输出已经是 Markdown，并保存在 `messages.content`；独立 Artifact CRUD 和重复持久化没有足够
价值。Markdown 预览和另存为 `.md` 合并到阶段 15 桌面客户端。

不新增 `/api/artifacts`、Artifact 表或独立版本模型。未来需要把多条回答组合成正式设计书时，再单独评估文档项目能力。

---

## 阶段 9：固定评估集

### 小目标

使用公开 `northwind_psql` Schema 建立唯一内置项目 Workspace，并通过正式 Chat API 固定评估最终回答质量。
`retail_sales_demo` 只保留为专家模板 Profile，不再作为 Workspace。

### 技术栈

1. pytest。
2. Pydantic 和 YAML。
3. HTTPX ASGI Transport。
4. 现有 Chat API、LiteLLM Gateway、PostgreSQL 和 Trace。

### 核心范围

1. 固定 `northwind_psql` 上游版本并建立唯一内置项目 Workspace。
2. `retail_sales_demo` 只保留为专家模板 Profile。
3. 把现有 Workspace 检索评估迁移到 Northwind。
4. 增加 12 个 Northwind 项目 Case 和 4 个通用 Databricks Case。
5. 通过正式 Chat API 分别运行 `deepseek-v4-flash` 和 `deepseek-v4-pro`，独立保存 Trace 和结果并生成对比报告。
6. 自动评分稳定事实，用户分别抽查两个模型的 SQL、PySpark 和 Workflow，共 6 份。

### 评估维度

1. 输出结构是否完整。
2. 是否使用 Northwind 真实表、字段和关系，且不虚构字段。
3. 是否正确选择 Workspace Context、专家模板和官方资料。
4. 是否有明确前置条件、风险和人工确认提示。
5. 如果使用 RAG，是否包含结构化官方引用。
6. 代码是否避免声称已执行、部署或验证。

### 完成标准

每次修改 Prompt、模型配置或 RAG 流程后，可以运行固定评估集，快速发现输出质量退化；阶段验收同时保留 Flash 和 Pro
两套独立日志、结果和对比报告。

### 当前状态（2026-07-20）

实现与真实双模型评估已完成。Northwind Workspace 固定评估为 `Recall@5=100%` 且上下文泄漏为 `0`；最终 Run
`stage9-final-v2-20260720` 中，Flash 的 Hard Pass 为 `100%`、Soft 平均为 `96.88%`，自动门禁通过；Pro 的
Hard Pass 为 `87.50%`、Soft 平均为 `89.58%`，因两个真实输出问题未通过。6 份人工抽查输出均已生成，用户已于
`2026-07-20` 全部批准。完整工程测试为 `525 passed`，覆盖率 `87.88%`。

这组结果固定为 Northwind Workspace 第一版历史基线。阶段 10 修改 Workspace 内容、评估 Case 或预期证据后，
不得覆盖该 Run；必须使用新的数据集版本和 Run ID 重新运行 Flash 与 Pro，并在报告中记录 Workspace 版本、
`source_hash`、Prompt 版本和模型配置。

详细计划见：

`docs/superpowers/plans/2026-07-19-stage-9-northwind-end-to-end-evaluation-plan.md`。

---

## 阶段 10：真实 Northwind Workspace 与评估再基线化

### 小目标

保留公开 `northwind_psql` Schema 作为事实基础，由用户人工校订并补全围绕它的真实项目材料，使 Workspace
更接近一个全新的 Databricks 数据平台项目；随后更新固定评估并重新建立当前直接生成流程的双模型基线。

### 核心范围

1. 保留 `northwind.sql` 的公开来源、版本和原始语义，不把模型生成内容伪装成上游事实。
2. 人工校订业务需求、指标口径、摄取约束、源到目标映射、数据质量规则、SLA、权限、成本和运维要求。
3. 用户提供的事实文件与程序生成的 proposal、代码和报告继续分目录保存，不相互污染。
4. 增加少量合理噪声、过期说明、相似表名和跨文件引用，验证检索能否找到正确证据，而不是只匹配显眼关键词。
5. 不加入真实密钥、个人信息、企业机密或可直接操作 Databricks 的凭据。
6. 更新 `tests/evals/workspace_context.yml` 和 `tests/evals/end_to_end.yml` 的问题、预期文件、表、字段和证据。
7. 固定数据集版本、Workspace 版本、`source_hash`、Prompt 版本、模型配置和运行 ID。
8. 使用当前 Direct 流程分别运行 `deepseek-v4-flash` 与 `deepseek-v4-pro`，保存完整结果、Trace 和日志。

### 评估要求

1. 不删除或覆盖阶段 9 已有数据集、报告、数据库验收数据和模型调用日志。
2. 在看到新模型结果前固定 Hard/Soft 规则和门禁，避免根据结果反向调整标准。
3. 除答案质量外，检查 Workspace 证据命中、虚构表字段、上下文泄漏、引用准确性、延迟和 Token 消耗。
4. 新基线作为阶段 11 至阶段 14 后续能力的共同控制组。

### 完成标准

1. Northwind Workspace 内容由用户完成人工抽查，且每项可验证事实都能追溯到明确文件。
2. 更新后的 Workspace Context 固定评估通过既定门禁。
3. Flash 与 Pro 均通过正式 Chat API 完成新版端到端评估。
4. 新旧结果可以按数据集、Workspace、Prompt、模型和 Run ID 独立比较。

---

## 阶段 11：Workspace 只读文件检索与工具系统

### 小目标

在现有一次性 Workspace Context 选择之外，建立受控、可审计的本地文件检索服务，让后续 Agent 能按需要列出、
搜索和分段读取真实项目文件，同时保持项目目录为事实来源。

### 技术栈

1. Python 3.12.10。
2. Pydantic 类型契约。
3. 现有 Workspace Registry。
4. `sqlparse` 及按文件类型选择的结构化解析器。
5. 受控文本搜索实现；具体采用 Python 实现或 `ripgrep` 适配器在阶段 specs 中固定。
6. 现有 PostgreSQL 调用审计和本地 Trace。

### 第一批工具

```text
list_files
search_text
read_file
inspect_sql_schema
find_references
```

### 核心边界

1. 建立统一 `ToolSpec`、参数 Schema、结构化结果、错误分类、超时、调用预算和 `ToolRegistry`。
2. 工具只能读取会话已绑定且 Registry 已注册的 Workspace 根目录。
3. 拒绝路径穿越、符号链接逃逸、隐藏密钥、`.env`、二进制文件、超大文件和未允许的文件类型。
4. 不提供 Shell、任意 Python、文件写入、删除、重命名、网络访问、数据库执行或 Databricks 操作工具。
5. 每次调用记录工具名、规范化参数、结果来源、相对路径、起止行、内容 Hash、截断状态、耗时和错误。
6. 第一版直接读取 Git 内置 Northwind Workspace，不要求 SQLite，也不复制完整项目文件到 PostgreSQL。
7. 先提供可由业务代码确定性调用的检索服务，再允许模型通过统一 Function Calling 契约进行有界选择。
8. 单次请求的工具调用次数、读取字节数、返回文本和总耗时必须有硬上限。

### 评估范围

新增 `tests/evals/file_retrieval.yml`，覆盖文件发现、精确字段定位、跨文件引用、噪声排除、越权路径拒绝、
调用预算和证据行号。使用与阶段 10 相同的 Workspace 和模型重新运行端到端评估，分别报告确定性 Context 与
文件工具检索结果，不覆盖控制组。

### 完成标准

1. 五类只读工具具备统一契约、权限边界、单元测试、集成测试和 Trace。
2. 固定文件检索评估达到阶段 specs 中预先确定的门禁，且越权访问测试全部拒绝。
3. Chat API 能在不执行项目代码的前提下，基于检索到的真实文件片段生成带文件证据的 Artifact。
4. 阶段 10 双模型基线与阶段 11 结果可以直接比较质量、成本和延迟。

---

## 阶段 12：LangGraph 顾问工作流编排

### 小目标

在 Direct 流程和文件工具均有稳定评估后，引入 LangGraph 编排需要规划、条件分支、多次检索和一次受控修订的
复杂顾问任务；普通问答继续使用现有快速路径。

### 技术栈

1. LangGraph 固定版本。
2. 现有 ModelGateway。
3. 现有 Prompt Registry 和 Markdown Artifact。
4. 官方 RAG、专家模板、Workspace Context 与阶段 11 文件工具。
5. PostgreSQL 会话、消息、模型调用审计和本地 Trace。

### 编排边界

1. 增加统一 `GenerationOrchestrator`，至少包含现有 `DirectOrchestrator` 和新的 `LangGraphOrchestrator`。
2. 普通 `databricks_qa` 和简单 `knowledge_qa` 默认走 Direct 快速路径。
3. SQL、PySpark、Notebook、Workflow 和提案等复杂交付物按明确规则进入 LangGraph，不做不可解释的随机路由。
4. 会话、消息、模型调用和引用仍以现有数据库为权威记录；不得无理由复制出第二套业务状态。
5. LangGraph Checkpoint 只保存恢复图执行所需的最小状态，并明确生命周期和清理规则。
6. 检索、反思和重试都设置最大次数；达到上限后返回可理解的失败或缺失信息，不允许无限循环。
7. 只记录结构化计划、节点输入输出、工具调用和状态转换，不记录模型隐藏思维过程。

### 第一张图

```text
任务路由
  -> 提取项目事实和约束
  -> 检查缺失信息
  -> 规划检索
  -> 官方知识 / 专家模板 / Workspace 文件检索
  -> 上下文充分性判断
       -> 不充分且未超预算：调整查询并再次检索
       -> 不充分且已超预算：返回待确认事项
       -> 充分：生成 Artifact
  -> 确定性结构校验
       -> 通过：保存结果
       -> 未通过且允许修订：最多一次审查与修订
       -> 仍未通过：保存失败审计并返回明确错误
```

### 评估范围

新增 `tests/evals/orchestration.yml`，覆盖路由、缺失信息分支、检索循环、工具预算、校验失败、一次修订、
终止条件和模型 fallback。使用相同 Case 分别运行 Direct 与 LangGraph，并用 Flash、Pro 各跑一遍，比较答案质量、
证据覆盖、工具次数、模型调用次数、Token、延迟和失败率。

### 完成标准

1. Direct 与 LangGraph 两条路径均可独立运行和审计，现有 Chat API 保持兼容。
2. 图中的每个节点、条件边、循环上限和失败出口都有固定测试。
3. LangGraph 在复杂任务上的质量或可恢复性有可测收益；无收益的简单任务不迁移。
4. 阶段 9、阶段 10、阶段 11 的历史结果、Trace 和验收数据全部保留。

---

## 阶段 13：AI 关键词提取与查询理解（后置）

### 状态

暂缓。阶段 10 至阶段 12 的真实 Workspace、文件检索和编排基线稳定后，再编写独立 specs 和实施计划。

### 小目标

在不改变用户原问题的前提下，使用模型把自然语言请求转换为可验证的结构化检索提示，提升官方知识库、专家模板、
Workspace Context 和文件工具对表名、字段、指标、Databricks 组件、任务类型、约束与否定条件的识别能力。

### 建议结构

```text
原始用户问题
  -> QueryAnalysis
       -> task_type
       -> databricks_products
       -> tables / columns
       -> business_metrics
       -> constraints / exclusions
       -> keyword_groups / query_expansions
  -> 现有官方 RAG / 专家模板 / Workspace 检索 / 文件工具
  -> 原始问题 + 可审计检索证据
```

### 核心边界

1. 原始问题始终完整保留并继续传给最终生成模型，提取结果不能替换或改写用户意图。
2. 使用严格 Pydantic Schema 接收结构化结果，不解析自由格式推理文本。
3. 关键词只作为召回、过滤、查询扩展和 rerank 信号，不能被当成业务事实或官方结论。
4. 提取模型失败、超时、格式无效或结果为空时，自动回退现有确定性检索，不阻断普通请求。
5. 对简单问答可跳过额外模型调用；触发规则、模型选择、token 和延迟预算在阶段 specs 中固定。
6. 开发环境优先评估 `deepseek-v4-flash`，但通过现有 ModelGateway 调用，不在业务代码中绑定供应商模型 ID。
7. Trace 记录提取器版本、结构化输入输出、耗时、token、回退和实际参与检索的词组，不记录隐藏思维过程。
8. 不因关键词提取引入新的文件权限、网络访问、数据库执行或 Databricks 操作能力。

### 评估范围

新增固定查询理解评估，覆盖中英文混合术语、表字段、业务指标、同义词、拼写差异、否定条件、未知字段和恶意提示。
同时在阶段 10 至阶段 12 的相同 Case 上比较启用前后的 Recall、误扩展率、最终证据覆盖、模型调用次数、token、延迟和
回答质量；不能只用“提取结果看起来合理”作为完成标准。

### 完成标准

1. 结构化提取契约、失败回退、调用预算和 Trace 均有固定测试。
2. 不增加虚构表、字段、指标或排除条件，原始查询语义始终可审计。
3. 至少一类现有检索在固定评估上获得可测收益，且端到端 Hard Gate 不下降。
4. 没有收益的简单请求继续走原始查询和 Direct 快速路径。

---

## 阶段 14：上下文自动压缩与会话记忆（后置）

### 状态

暂缓。只有在阶段 13 的结构化查询理解和阶段 12 的编排审计稳定后，才固定压缩策略、持久化契约和数值门禁。

### 小目标

在长会话、多轮文件检索和 LangGraph 多节点执行接近模型上下文上限时，自动缩减重复或低价值内容，同时保留项目事实、
代码、业务公式、否定条件、待确认事项、来源引用和最近对话，使长任务能够继续而不覆盖原始记录。

### 建议分层

```text
不可压缩层
  -> 当前 system / developer 约束
  -> 当前用户请求
  -> 被引用的代码、DDL、业务公式和否定条件
  -> 来源 ID、路径、Hash、行号和官方引用

近期原文层
  -> 最近若干轮用户与 Assistant 消息
  -> 当前 LangGraph 节点和未完成事项

可压缩层
  -> 更早的会话历史
  -> 重复检索片段
  -> 已完成节点的中间结果
  -> 可由来源重新读取的长文本
```

### 核心边界

1. 先做确定性去重、排序、裁剪和来源合并，仍超预算时才调用模型生成摘要。
2. 触发条件基于实际 token 预算、模型上下文窗口和预留输出空间，不只按消息条数判断。
3. `sessions`、`messages`、`model_calls`、工具结果和原始 Trace 继续作为权威记录，不删除、不覆盖、不回写摘要。
4. 压缩结果作为带版本的派生 Context Snapshot，记录覆盖的消息/来源 ID、输入 Hash、压缩器版本、token 前后值和时间。
5. 代码、DDL、字段清单、业务公式、硬约束、否定条件、待确认项和引用优先原文保留，不做可能改变语义的自由改写。
6. 摘要中的每项项目事实必须能追溯到原始消息或来源；无法追溯的内容不得进入最终上下文。
7. 压缩失败、结果无效或关键事实校验失败时，回退确定性裁剪或返回上下文超限错误，不静默丢失内容。
8. 是否新增 `context_snapshots` 表、快照生命周期和 LangGraph Checkpoint 关系，在阶段 specs 中一次性固定，避免双重状态。
9. 不保存模型隐藏思维过程，只保存可展示的摘要、事实条目、来源关系和压缩审计。

### 评估范围

新增长会话固定评估，使用多轮 Northwind 需求变更、代码讨论、相互冲突的旧规则和多次文件检索构造稳定输入。检查关键事实
保留率、禁止事实泄漏、引用可追溯、token 压缩率、最终答案 Hard Gate、额外模型成本和延迟，并与未压缩 Direct、
LangGraph 基线分别比较。

### 完成标准

1. 触发、分层、压缩、验证、回退和快照审计均有固定测试。
2. 原始会话、项目文件、检索证据和历史 Trace 保持不变。
3. 固定长会话中的表字段、公式、约束、否定条件、待确认项和引用全部保留。
4. 在预先固定的 token 缩减门禁下，端到端 Hard Gate 不低于未压缩基线。
5. 短会话不触发压缩，不为没有收益的请求增加额外模型调用。

---

## 阶段 15：桌面客户端与本地工作区（后置）

### 状态

暂缓。最终形态允许用户选择本地项目文件夹，但复用阶段 11 的只读工具契约、阶段 12 的编排接口、阶段 13 的查询理解和
阶段 14 的上下文预算，不在客户端重新实现这些业务逻辑。

### 候选范围

1. C# Avalonia 或 Electron，技术选型在阶段 specs 中决定。
2. 聊天、会话历史、模型选择和本地服务状态。
3. 本地文件夹选择、授权根目录和最近 Workspace。
4. Workspace 文件证据、来源、Markdown Artifact 预览与 `.md` 下载。
5. 增量扫描、文件 Hash、忽略规则和变更检测。
6. SQLite 保存可重建的解析结果、Chunk、FTS5 索引和客户端设置。
7. 项目源码始终保留在用户目录，不把完整项目复制到 PostgreSQL。

---

## 4. 推荐优先级

### 已完成基础

1. FastAPI、LiteLLM、PostgreSQL 会话和模型审计。
2. Prompt Registry 与 Markdown Artifact。
3. 预置 Databricks 官方 RAG 与专家模板库。
4. Workspace 感知代码和工作流生成。
5. Northwind 固定评估与真实双模型基线。

### 近期最高优先级

1. 人工校订 Northwind Workspace，使项目材料更接近真实场景。
2. 更新固定评估并重跑 Direct 双模型基线。
3. 建立 Workspace 只读文件检索和统一 Tool Registry。
4. 为文件证据、越权拒绝、成本和延迟增加固定评估。
5. 用 LangGraph 编排复杂交付物，并保留 Direct 控制组。

### 后续优先级

1. AI 关键词提取与结构化查询理解。
2. 上下文自动压缩与可追溯会话记忆。
3. 桌面客户端和本地文件夹选择。
4. Markdown 文件预览与下载。
5. SQLite 工作区派生索引。

### 暂缓

1. Word 导出。
2. PDF 导出。
3. 多用户系统。
4. Databricks API 直连。
5. 企业权限与租户隔离。
6. 文件写入、命令执行和自动部署工具。
7. AutoGen、AgentScope、CAMEL 等多智能体框架。

---

## 5. 建议的开发顺序

后续开发继续按阶段顺序推进，不再额外使用“第几个 Demo”的并行分组。阶段 9 的评估能力从此作为持续质量门禁，
不只在单独阶段运行。

1. 阶段 1：项目初始化与最小聊天后端。
2. 阶段 2：LiteLLM 模型网关。
3. 阶段 3：Prompt Registry 和 Markdown Artifact。
4. 阶段 4：预置 Databricks 知识库 RAG。
5. 阶段 5：Databricks 专家模板库。
6. 阶段 6：代码生成模块。
7. 阶段 7：工作流设计模块。
8. 阶段 8：跳过独立实施，Markdown 预览与下载合并到阶段 15。
9. 阶段 9：固定评估集。
10. 阶段 10：真实 Northwind Workspace 与评估再基线化。
11. 阶段 11：Workspace 只读文件检索与工具系统。
12. 阶段 12：LangGraph 顾问工作流编排。
13. 阶段 13：AI 关键词提取与查询理解，后置。
14. 阶段 14：上下文自动压缩与会话记忆，后置。
15. 阶段 15：桌面客户端与本地工作区，后置。

---

## 6. 后续需要进一步细化的小计划

阶段 1 至阶段 9 已有计划或明确跳过。后续按以下顺序分别编写 specs 和小计划，不把五个独立子系统塞入同一份
实施计划：

1. 阶段 10：真实 Northwind Workspace 与评估再基线化。
2. 阶段 11：Workspace 只读文件检索与工具系统。
3. 阶段 12：LangGraph 顾问工作流编排。
4. 阶段 13：AI 关键词提取与查询理解，待阶段 12 基线稳定后再写。
5. 阶段 14：上下文自动压缩与会话记忆，待阶段 13 查询结构和阶段 12 状态契约稳定后再写。
6. 阶段 15：桌面客户端与本地工作区，待后端检索、编排和上下文管理接口稳定后再写。

---

## 7. 风险和取舍

### 风险 1：过早引入复杂 Agent 框架

如果太早引入 LangGraph、多 Agent 或复杂工具调用，Demo 会被框架复杂度拖慢。

当前取舍：阶段 10 先固定真实语料和 Direct 基线，阶段 11 再提供受控文件工具，阶段 12 只编排有明确分支、循环和
质量收益的复杂任务。普通问答继续走 Direct 路径。

### 风险 2：RAG 文档质量不足

如果知识库材料太散，RAG 只会把无关内容拼进上下文。

当前取舍：官方 Docs/API 目录全部同步，通过确定性 Chunk、混合召回、上下文预算和固定评估控制噪声，不再用
人工白名单缩小来源范围。

### 风险 3：代码生成被误解为可直接执行

Agent 生成的 SQL 和 PySpark 可能存在环境差异，不能默认可执行。

当前取舍：代码直接输出带必要注释的草稿；有项目工作区时使用实际字段，无工作区时明确标识假设；始终不声称
已经运行、部署或验证。

### 风险 4：Demo 范围膨胀

文档导出、桌面端、多用户、Databricks API 直连都很容易吸引注意力。

当前取舍：阶段 10 至阶段 14 只强化真实项目理解、只读检索、顾问编排、查询理解和上下文管理；桌面端继续后置，
系统始终不做 Databricks 执行。

### 风险 5：过早拆分关系数据库和向量数据库

如果同时使用 PostgreSQL 和 Qdrant，需要处理双写、删除同步、版本一致性和备份恢复，会明显增加 Demo 复杂度。

当前取舍：第一版统一使用 PostgreSQL + pgvector。只有在真实数据量和性能测试证明 pgvector 不满足需求时，才把 Qdrant 作为可重建的派生索引引入。

### 风险 6：Embedding 模型切换导致索引不兼容

不同 Embedding 模型的向量维度和语义空间可能不同，不能把它们直接写入同一个索引并混合检索。

当前取舍：聊天模型和 Embedding 模型独立配置；第一版固定一个 Embedding 模型、维度和距离算法，切换模型时全量重建预置知识库索引。

### 风险 7：本地文件检索越权或泄露敏感信息

目录扫描和模型工具调用可能读取 Workspace 之外的路径、`.env`、密钥、二进制文件或体积失控的内容。

当前取舍：阶段 11 只读取 Registry 明确授权的根目录，统一执行路径规范化、类型和大小限制、敏感文件排除、
调用预算与 Trace；不提供 Shell、写文件、网络访问或代码执行。

### 风险 8：Workspace 与评估集共同变化导致结果失真

如果先看到模型结果再调整问题、预期证据或评分门禁，或者直接覆盖阶段 9 报告，就无法客观判断新能力是否有效。

当前取舍：每轮运行前固定数据集版本、Workspace Hash、评分规则和门禁；所有 Run 使用唯一 ID，旧结果、数据库数据、
Trace 和日志永久保留为对照。

### 风险 9：LangGraph 与现有持久化形成双重状态

如果图 Checkpoint、`sessions`、`messages` 和 `model_calls` 分别保存完整业务状态，恢复和审计时容易出现不一致。

当前取舍：现有 PostgreSQL 业务表继续作为权威记录；Checkpoint 只保存恢复图执行所需的最小状态，并在阶段 12 specs
中明确 `session_id`、图线程 ID、生命周期和清理规则。

### 风险 10：AI 关键词提取放大错误检索

如果提取模型补出用户没有提到的表、字段、产品或约束，错误关键词可能提高无关文档的排名，并把检索偏差继续传给
最终生成模型。

当前取舍：阶段 13 始终保留原始问题，提取结果只作为有界检索提示；使用严格结构、否定条件、失败回退和固定标注集
评估误扩展率。提取结果不得成为新的项目事实。

### 风险 11：上下文压缩丢失关键事实

如果摘要省略业务公式、字段、否定条件、待确认项或引用，长会话虽然 token 下降，最终输出却可能变得不可验证。

当前取舍：阶段 14 保留原始消息和来源，以分层 Context Snapshot 作为派生数据；代码、DDL、公式、硬约束和引用优先
原文保留，压缩结果必须通过关键事实与来源完整性检查，否则回退或明确失败。

---

## 8. 近期最推荐的下一步

阶段 1 至阶段 7 已完成实现和验收，阶段 8 已决定跳过独立实施，阶段 9 的功能实现、真实双模型基线和 6 份人工抽查
已经完成。阶段 10 逐任务计划已经编写，近期下一步是按计划人工校订 Northwind Workspace，更新
`workspace_context.yml` 与 `end_to_end.yml`，随后使用当前 Direct 流程重新运行 Flash、Pro 双模型基线。

阶段 10 完成后再依次编写阶段 11 文件检索和阶段 12 LangGraph 的独立 specs 与计划。阶段 13 AI 关键词提取、
阶段 14 上下文自动压缩和阶段 15 桌面客户端均为后置能力，暂不进入近期实施队列。

已完成与已规划阶段的详细设计和实施步骤见：

1. `docs/superpowers/specs/2026-07-10-stage-1-backend-design.md`。
2. `docs/superpowers/plans/2026-07-10-stage-1-backend-plan.md`。
3. `docs/superpowers/specs/2026-07-11-stage-2-model-gateway-design.md`。
4. `docs/superpowers/plans/2026-07-11-stage-2-model-gateway-plan.md`。
5. `docs/superpowers/specs/2026-07-11-stage-3-prompt-registry-markdown-artifact-design.md`。
6. `docs/superpowers/plans/2026-07-11-stage-3-prompt-registry-markdown-artifact-plan.md`。
7. `docs/superpowers/specs/2026-07-12-stage-4-prebuilt-databricks-rag-design.md`。
8. `docs/superpowers/plans/2026-07-12-stage-4-prebuilt-databricks-rag-plan.md`。
9. `docs/superpowers/specs/2026-07-16-stage-5-databricks-expert-template-library-design.md`。
10. `docs/superpowers/plans/2026-07-16-stage-5-databricks-expert-template-library-plan.md`。
11. `docs/superpowers/specs/2026-07-17-stage-6-project-aware-code-generation-design.md`。
12. `docs/superpowers/plans/2026-07-17-stage-6-project-aware-code-generation-plan.md`。
13. `docs/superpowers/plans/2026-07-18-stage-7-workflow-design-plan.md`。
14. `docs/superpowers/plans/2026-07-19-stage-9-northwind-end-to-end-evaluation-plan.md`。
