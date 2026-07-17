# Databricks 顾问型 Agent Demo Implementation Plan

> **给后续 agentic workers 的说明：** 如果后续要按本文执行开发，请先使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，再把每个阶段拆成独立、可测试、可提交的小任务。

**目标：** 构建一个本地运行的 Databricks 顾问型 Agent Demo，能够回答 Databricks 问题、检索预置 Databricks 知识库、生成 SQL/PySpark/工作流设计草案，并以 Markdown 形式输出可交付内容。

**架构：** 第一版采用“单体后端 + 简单 Web UI/API 调试”的结构，先把模型调用、会话保存、Prompt 模板、RAG 和 Markdown 交付物跑通。Agent 不直接操作 Databricks，不执行 SQL，不提交 Job，只负责生成建议、代码草稿、设计文档和引用来源。

**技术栈：** Python 3.12.10、FastAPI、LiteLLM、PostgreSQL、pgvector、SQLAlchemy 2.x、Alembic、
psycopg 3、OpenAI Embeddings、httpx、Beautiful Soup、markdown-it-py、pytest、Ruff、Pyright、Markdown。

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
11. 系统输出使用项目字段或明确假设、带必要注释且可人工审查的代码草稿。

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
        +-- Workspace Registry / Context Provider
        +-- Evaluation Runner
        |
        +-- PostgreSQL + pgvector
        |     +-- 会话、消息和 Artifact
        |     +-- 模型调用与评估记录
        |     +-- 知识库元数据、Chunk 和 Embedding
        |
        +-- Local File Storage
              +-- 预置知识库原始 Markdown / YAML
              +-- 内置 Mock 项目工作区
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
11. 每次修改 Python 代码后，完成当前任务前必须运行 Ruff 格式检查、Ruff lint、Pyright 和 pytest；仅修改 Markdown 等文档时不强制运行 Pyright 和 pytest。
12. 具体项目的源代码、DDL 和配置始终以用户本地工作区文件为准；数据库只保存可重建索引和调用审计。
13. Demo 阶段先使用 Git 内置 Mock 工作区；最终桌面端再实现本地文件夹选择、增量扫描和 SQLite 工作区索引。

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

1. 使用“通用核心层 + AWS 零售销售 Mock 覆盖层”。
2. 同一 Git 仓库、同一 PostgreSQL、独立专家模板表，不混入 `kb_*` 官方知识表。
3. 模板使用 Markdown + YAML Front Matter，Profile 使用 YAML 清单。
4. 会话级 `expert_profile` 默认为 `generic`；具体模板由系统自动选择。
5. Mock 架构覆盖 S3 日批、RDS PostgreSQL、AWS DMS、S3 Parquet、Auto Loader 和 Kinesis。
6. Medallion 转换使用 Lakeflow Spark Declarative Pipelines 的稳定能力，不采用 Preview 功能。
7. 模板分为 blueprint、decision guide、code pattern、checklist、deliverable 五类。
8. 第一版约 37 个短而具体的专家资产。
9. 官方事实与 Mock 经验分别检索，官方引用只来自阶段 4 数据。
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

设计规格与八任务实施计划已经完成，尚未开始实现。

### 小目标

让 Databricks SQL、PySpark 和 Python source Notebook 草稿能够使用具体项目的表、字段、映射、业务规则和
既有代码风格，同时为最终本地工作区模式保留稳定接口。

### 技术栈

1. Prompt Registry。
2. LiteLLM Gateway。
3. Markdown Artifact。
4. PyYAML + Pydantic。
5. tiktoken。
6. Git 内置项目工作区。

### 已确认边界

1. 创建一个真实目录结构的 `retail_sales_demo` Mock 工作区。
2. `expert_profile` 表示方法论，`workspace_id` 表示具体项目，两者保持独立。
3. 阶段 6 只读取清单显式列出的内置文件，不支持任意目录和上传。
4. Workspace 文件是项目事实来源；PostgreSQL 只保存 ID、版本、Hash 和选择审计。
5. 项目文件选择使用确定性关键词和 token 预算，不调用模型或 Embedding。
6. SQL 与 PySpark 直接输出代码围栏和必要注释，不强制长篇章节。
7. Notebook 输出为 Python source 格式草稿，不创建 `.py` 或 `.ipynb` 文件。
8. 不执行、编译、部署或验证任何生成代码。
9. 完整本地扫描、文件监听和 SQLite 索引放到后续桌面工作区阶段。

### Mock 项目内容

1. S3 POS 日批。
2. RDS PostgreSQL 经 AWS DMS 写入 S3 Parquet。
3. Kinesis 电商事件流。
4. 16 张 Bronze、Silver、Gold 表。
5. 字段、业务键、CDC、PII、金额和业务日期规则。
6. 三层 DDL、最小 `databricks.yml` 和 PySpark 风格样例。

### 代码生成范围

第一版支持：

1. SELECT / JOIN / 聚合 SQL。
2. Delta 表读写 SQL。
3. 基础性能优化建议。
4. PySpark 读取、清洗、转换、写入 Delta。
5. Python source 格式 Notebook 草稿。
6. 有工作区时使用实际项目表、字段和规则。
7. 无工作区时继续生成明确标注假设的通用草稿。

第一版不支持：

1. 自动连接数据库验证 SQL。
2. 自动运行 PySpark。
3. 自动创建 Databricks Notebook。
4. 自动部署 Job。
5. 用户本地目录扫描、SQLite 项目索引和文件监听。
6. 严格 SQL / Python AST 阻断或自动修复。

### 完成标准

1. SQL、PySpark 和 Notebook 三类 Prompt 可以使用内置零售项目上下文。
2. 固定 Workspace Context 评估达到 `Recall@4 >= 90%`。
3. `model_calls` 和 Trace 1.6 可以恢复实际工作区版本、Hash 和相对文件选择。
4. 三次 `deepseek-v4-flash` 真实冒烟成功并保留验收数据。
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

当前取舍：官方 Docs/API 目录全部同步，通过确定性 Chunk、混合召回、上下文预算和固定评估控制噪声，不再用
人工白名单缩小来源范围。

### 风险 3：代码生成被误解为可直接执行

Agent 生成的 SQL 和 PySpark 可能存在环境差异，不能默认可执行。

当前取舍：代码直接输出带必要注释的草稿；有项目工作区时使用实际字段，无工作区时明确标识假设；始终不声称
已经运行、部署或验证。

### 风险 4：Demo 范围膨胀

文档导出、桌面端、多用户、Databricks API 直连都很容易吸引注意力。

当前取舍：第一版只保证本地顾问输出能力，不做执行型系统。

### 风险 5：过早拆分关系数据库和向量数据库

如果同时使用 PostgreSQL 和 Qdrant，需要处理双写、删除同步、版本一致性和备份恢复，会明显增加 Demo 复杂度。

当前取舍：第一版统一使用 PostgreSQL + pgvector。只有在真实数据量和性能测试证明 pgvector 不满足需求时，才把 Qdrant 作为可重建的派生索引引入。

### 风险 6：Embedding 模型切换导致索引不兼容

不同 Embedding 模型的向量维度和语义空间可能不同，不能把它们直接写入同一个索引并混合检索。

当前取舍：聊天模型和 Embedding 模型独立配置；第一版固定一个 Embedding 模型、维度和距离算法，切换模型时全量重建预置知识库索引。

### 风险 7：过早实现完整本地工作区

任意目录扫描、忽略规则、文件监听、代码解析、SQLite 和向量索引会把代码生成阶段扩展成另一个大型 RAG
项目。

当前取舍：阶段 6 只固定 Workspace 契约并读取一个 Git 内置 Mock 工作区；最终桌面端使用本地 SQLite 保存
文件 Hash、解析结果、Chunk 和 FTS5 等可重建派生索引，项目源码仍保留在用户选择的文件夹。

---

## 8. 近期最推荐的下一步

阶段 1 至阶段 5 已完成实现和验收。阶段 6 的设计规格和实施计划已经完成，近期下一步是执行阶段 6 任务 1：
固定 Workspace 契约、常量和 Registry。

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
