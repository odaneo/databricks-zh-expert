# 阶段 4：预置 Databricks 知识库 RAG 实施计划

> **执行要求：** 使用 `superpowers:executing-plans` 在当前会话逐任务执行；按用户偏好不使用子智能体。
> 每个任务先写失败测试，再做最小实现，验证通过后单独提交。不得清理现有验收数据。

**目标：** 从受控 Databricks 官方来源构建 PostgreSQL + pgvector 预置知识库，并通过现有 Chat API 的
`knowledge_qa` Prompt 提供可恢复历史引用的中文问答。

**架构：** YAML 清单限定官方来源；两个 `llms.txt` 只负责发现，选中正文经受限 HTTP 抓取、Markdown
规范化和标题感知 Chunk 后，由 OpenAI Embedding 写入 PostgreSQL。在线请求使用 pgvector 精确检索与
PostgreSQL 全文检索，通过 RRF 融合后交给现有 ModelGateway。完整文档、Chunk 和向量持久化，引用快照保存
到 assistant message，检索分数只写 Trace 1.4。

**技术栈：** Python 3.12.10、FastAPI 0.139.0、SQLAlchemy 2.0.51、Alembic 1.18.5、PostgreSQL 18、
pgvector 0.8.5 服务端扩展、pgvector 0.5.0 Python 包、OpenAI 2.45.0、httpx 0.28.1、
Beautiful Soup 4.15.0、markdownify 1.2.3、markdown-it-py 4.2.0、tiktoken 0.13.0、PyYAML 6.0.3、
pytest、Ruff、Pyright。

详细设计见：

`docs/superpowers/specs/2026-07-12-stage-4-prebuilt-databricks-rag-design.md`

## 已确认决策

1. 只做预置知识库，不做用户上传和聊天请求期间实时建索引。
2. `llms.txt` 与 `/api/llms.txt` 是发现目录，数据库保存选中页面的规范化完整正文。
3. 首批约 30 至 50 篇资料，通用文档约 25 至 35 篇，API 页面约 5 至 15 篇。
4. 只抓 `docs.databricks.com`，不实现 Agent Skills、Sitemap 或任意 URL 适配器。
5. PostgreSQL 保存完整 Markdown、Chunk 正文、向量和同步运行，不保存原始 HTML。
6. 新增三张知识表：`kb_documents`、`kb_chunks`、`kb_ingestion_runs`。
7. `messages` 增加 `source_citations JSONB`，不增加检索运行或检索结果表。
8. Demo 使用 pgvector 精确 cosine 检索，不创建 HNSW 或 IVFFlat。
9. Embedding 固定为 OpenAI `text-embedding-3-small`、1536 维，聊天仍可选择 OpenAI 或 DeepSeek。
10. `knowledge_qa` 由客户端显式选择，不自动识别意图，不新增 `/api/rag/query`。
11. 没有合格检索结果时不调用聊天模型。
12. 检索排名和分数只写 Trace 1.4，用户历史引用从 `messages.source_citations` 恢复。
13. 不引入 LlamaIndex、LangGraph、reranker、自动同步或并发同步。
14. 阶段 3 的 Prompt/Artifact 行为和已有验收数据必须保留。

## 全局约束

1. 同步只由开发者 CLI 发起，HTTP API 不提供同步写入口。
2. 自动测试不得访问 Databricks、OpenAI 或 DeepSeek 网络。
3. 所有远程正文视为不可信数据，不能进入或覆盖 system message。
4. 只接受清单中的官方 URL，每次重定向都重新校验 HTTPS 和 host。
5. 未变化文档不得重复切分或调用 Embedding。
6. 单个文档全部抓取、解析、切分和 Embedding 成功后才事务性替换旧版本。
7. 同一索引只允许一个 Embedding 模型和维度，切换时显式全量重建。
8. 普通 Prompt 不自动检索，已有 API 字段保持兼容。
9. README 继续只记录安装和启动步骤，不添加架构解释或调试说明。
10. 每次 Python 改动后运行 Ruff 和 Pyright/Pylance；任务结束运行对应 pytest。
11. 不运行 truncate、drop schema、测试数据清理或任何会减少开发库业务数据的命令。
12. `.env`、API Key、Trace、数据库 dump 和官方正文副本不得提交到 Git。

## 基线

1. 当前分支：`main`。
2. 当前迁移 head：`0003_prompt_artifacts`。
3. 当前 Trace schema：`1.3`。
4. `knowledge_qa` 已注册，版本 `1.0.1`，状态为不可用。
5. Docker PostgreSQL 已启用 `vector` 扩展，应用 schema 为 `databricks_agent`。
6. 测试数据库独立；开发数据库中的验收数据不参与测试清理。
7. 必须保留验收 session：`8a67159d-e90d-4171-9be1-c7dbe6de11c8`。
8. 必须保留验收 session：`02173524-ef78-4b02-8ae9-016d3a79ad1d`。

## 目标文件结构

```text
knowledge/
  databricks/
    sources.yml                         受版本控制的官方来源清单

src/databricks_zh_expert/
  rag/
    __init__.py
    constants.py                        跨环境一致的 Embedding、抓取和检索参数
    types.py                            来源、文档、Chunk、Embedding、引用类型
    manifest.py                         YAML 清单解析和校验
    catalogs.py                         两种 llms.txt 目录解析
    fetcher.py                          受限 HTTP 和条件请求
    normalizer.py                       HTML / Markdown 正文规范化
    chunker.py                          标题感知 token 切分
    embeddings.py                       EmbeddingClient 与 OpenAI 实现
    repository.py                       文档、Chunk、同步状态和检索 SQL
    ingestion.py                        增量同步编排和单文档原子发布
    retrieval.py                        精确向量、全文候选和 RRF
    context.py                          不可信上下文与引用组装
    cli.py                              sync / status / evaluate
  api/
    knowledge.py                        GET /api/knowledge/index/status
    knowledge_schemas.py                索引状态响应
  chat/
    schemas.py                          source_citations API 契约
    repository.py                       消息引用持久化
    service.py                          knowledge_qa 编排
  db/
    models.py                           三张知识表和 message 引用列
  observability/
    model_trace.py                      Trace 1.4 retrieval 元数据
  prompts/
    registry.py                         启用 knowledge_qa 1.1.0
    templates/knowledge_qa.jinja2       引用和提示注入边界
  main.py                               知识依赖和状态路由装配

alembic/versions/
  0004_knowledge_rag.py

tests/
  fixtures/knowledge/                   少量离线 HTML、Markdown、llms fixture
  evals/databricks_rag.yml              中文固定检索评估集
  unit/
    test_knowledge_manifest.py
    test_knowledge_sources.py
    test_knowledge_chunker.py
    test_embeddings.py
    test_knowledge_ingestion.py
    test_knowledge_retrieval.py
    test_rag_context.py
  integration/
    test_knowledge_repository.py
    test_knowledge_api.py
    test_knowledge_messages_api.py
    test_migrations.py
```

---

### 任务 1：固定依赖、产品常量和官方来源清单

**小目标：** 项目可以确定性读取和校验一份有限的 Databricks 官方来源清单；此任务不访问网络、不修改数据库。

**文件：**

- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 创建：`knowledge/databricks/sources.yml`
- 创建：`src/databricks_zh_expert/rag/constants.py`
- 创建：`src/databricks_zh_expert/rag/types.py`
- 创建：`src/databricks_zh_expert/rag/manifest.py`
- 创建：`tests/unit/test_rag_constants.py`
- 创建：`tests/unit/test_knowledge_manifest.py`

**公开接口：**

```python
class CatalogKind(StrEnum):
    DATABRICKS_DOCS = "databricks_llms_index"
    DATABRICKS_API = "databricks_api_llms_index"


class SourceKind(StrEnum):
    GENERAL_HTML = "general_html"
    API_MARKDOWN = "api_markdown"


@dataclass(frozen=True, slots=True)
class KnowledgeManifest:
    version: int
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    catalogs: tuple[SourceCatalog, ...]


def load_manifest(path: Path) -> KnowledgeManifest: ...
```

- [x] **步骤 1：写产品常量和清单失败测试**

至少覆盖：

1. 九个 RAG 参数由 `rag/constants.py` 提供，不属于 `Settings` 或 `.env`。
2. Embedding 模型固定为 `text-embedding-3-small`，维度固定为 1536。
3. `chunk_overlap_tokens < chunk_size_tokens`。
4. catalog id 和 source key 唯一。
5. 只允许 `https://docs.databricks.com/...`。
6. API 白名单必须到具体 operation，不能只指定空模块。
7. 未知字段、未知 source kind、空清单和非法 URL 失败。
8. 仓库中的实际 `sources.yml` 可成功解析。

- [x] **步骤 2：确认测试失败**

```powershell
uv run --locked pytest tests/unit/test_rag_constants.py tests/unit/test_knowledge_manifest.py -q
```

- [x] **步骤 3：添加精确直接依赖**

```powershell
uv add "openai==2.45.0" "pgvector==0.5.0" "httpx==0.28.1" `
  "beautifulsoup4==4.15.0" "markdownify==1.2.3" "tiktoken==0.13.0" "pyyaml==6.0.3"
uv lock --check
```

把 `httpx==0.28.1` 从 dev group 移到 runtime，不能在两个依赖组重复声明。不得手工编辑 `uv.lock`。

- [x] **步骤 4：实现产品常量和领域类型**

按照设计规格第 17 节在 `rag/constants.py` 定义九个带 `Final` 的产品常量。它们跨环境一致，不进入
`core/config.py`、`.env.example` 或本地 `.env`。来源类型和清单结构继续使用冻结 dataclass。

- [x] **步骤 5：创建初始来源清单**

通用文档约 25 至 35 篇，覆盖 Delta Lake、Medallion、Jobs、Pipelines、Auto Loader、Structured Streaming、
Unity Catalog、Databricks SQL、Photon、性能和成本。API 约 5 至 15 篇，明确列出 Jobs、Pipelines 等具体
operation，不使用目录通配符。

- [x] **步骤 6：验证并提交**

```powershell
uv run --locked pytest tests/unit/test_rag_constants.py tests/unit/test_knowledge_manifest.py -q
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add pyproject.toml uv.lock knowledge src tests docs
git commit -m "feat: define databricks knowledge sources"
```

---

### 任务 2：实现官方目录发现、受限抓取和正文规范化

**小目标：** 使用本地 fixture 验证两个官方目录，并把选中 HTML / Markdown 转换为干净的规范化 Markdown。

**文件：**

- 创建：`src/databricks_zh_expert/rag/catalogs.py`
- 创建：`src/databricks_zh_expert/rag/fetcher.py`
- 创建：`src/databricks_zh_expert/rag/normalizer.py`
- 创建：`src/databricks_zh_expert/rag/urls.py`
- 修改：`src/databricks_zh_expert/rag/constants.py`
- 修改：`src/databricks_zh_expert/rag/types.py`
- 修改：`src/databricks_zh_expert/rag/manifest.py`
- 创建：`tests/fixtures/knowledge/databricks_llms.txt`
- 创建：`tests/fixtures/knowledge/databricks_api_llms.txt`
- 创建：`tests/fixtures/knowledge/docs_page.html`
- 创建：`tests/fixtures/knowledge/api_page.md`
- 创建：`tests/unit/test_knowledge_sources.py`

**公开接口：**

```python
class KnowledgeCatalogParser:
    def discover(
        self,
        index_content: str,
        catalog: SourceCatalog,
    ) -> tuple[DiscoveredSource, ...]: ...


class KnowledgeFetcher:
    async def fetch_catalog(self, catalog: SourceCatalog) -> CatalogFetchResult: ...

    async def fetch(
        self,
        source: DiscoveredSource,
        condition: FetchCondition | None,
    ) -> FetchResult: ...


class KnowledgeNormalizer:
    def normalize(self, fetched: FetchResult) -> NormalizedDocument: ...
```

- [x] **步骤 1：写目录解析失败测试**

使用 `markdown-it-py` token 提取标题和链接，不用正则拼 Markdown。覆盖：

1. 通用目录只返回清单 URL，并保留标题和主题。
2. API 目录只返回指定模块和 operation。
3. URL 去重后保持官方目录顺序。
4. 白名单项在目录中不存在时失败，不直接绕过目录抓取。
5. 目录正文不会作为知识文档返回。

- [x] **步骤 2：写 HTTP 安全失败测试**

使用 `httpx.MockTransport` 覆盖：

1. ETag / Last-Modified 条件请求和 304。
2. 同 host HTTPS 重定向成功。
3. HTTP、跨域、localhost、IP 和用户 URL 失败。
4. Content-Type 不符、正文超过上限和重定向过多失败。
5. 429 / 5xx 最多重试 2 次，普通 4xx 不重试。
6. 日志不输出 Authorization 或 API Key。

- [x] **步骤 3：写规范化失败测试**

覆盖：

1. HTML 只提取 `article.theme-doc-markdown` 或明确 `<article>`。
2. 导航、页脚、脚本和反馈控件不进入正文。
3. 保留 H1-H3、列表、表格、链接和 fenced code block。
4. API Markdown 不经过 HTML 转换。
5. canonical URL、标题和来源更新时间正确。
6. 缺少正文或正文过短时失败。

- [x] **步骤 4：确认测试失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_sources.py -q
```

- [x] **步骤 5：实现发现、抓取和规范化**

目录解析使用 Markdown AST；URL 处理使用统一的官方 HTTPS URL 校验器；HTML 使用 Beautiful Soup
定位正文，再用 markdownify 转换。Fetcher 注入 `httpx.AsyncClient` 和等待函数，手动校验每一次
重定向，并为后续同步任务提供独立的 `fetch_catalog()`。此任务不保存原始 HTML 或 `llms.txt`。

- [x] **步骤 6：验证并提交**

```powershell
uv run --locked pytest tests/unit/test_knowledge_sources.py -q
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add src tests
git commit -m "feat: fetch official databricks documents"
```

---

### 任务 3：实现确定性 Chunk 和独立 OpenAI EmbeddingClient

**小目标：** 将规范化 Markdown 稳定切分，并通过可替换客户端生成经过严格校验的 1536 维向量。

**文件：**

- 创建：`src/databricks_zh_expert/rag/chunker.py`
- 创建：`src/databricks_zh_expert/rag/embeddings.py`
- 创建：`tests/unit/test_knowledge_chunker.py`
- 创建：`tests/unit/test_embeddings.py`

**公开接口：**

```python
class MarkdownChunker:
    def split(self, document: NormalizedDocument) -> tuple[KnowledgeChunk, ...]: ...


class EmbeddingClient(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingResult, ...]: ...
    async def embed_query(self, text: str) -> EmbeddingResult: ...
```

- [x] **步骤 1：写 Chunk 失败测试**

至少覆盖：

1. 普通 Chunk 不超过 600 tokens，重叠接近 80 tokens。
2. 短代码围栏和表格不被拆开。
3. 超长代码块按明确兜底规则拆分，不造成无限循环。
4. heading path 和 source_ref 正确。
5. 相同输入两次生成相同顺序、token 数和 SHA-256。
6. 空章节不生成 Chunk。

- [x] **步骤 2：写 Embedding 失败测试**

注入 Fake OpenAI client，覆盖：

1. 文档批次保持输入顺序。
2. 请求明确使用 `text-embedding-3-small` 和 `dimensions=1536`。
3. 返回数量、index、维度、NaN 或 Infinity 异常时失败。
4. OpenAI 错误归一化后不包含 Key。
5. 缺少 Key 只使知识能力失败，不影响普通 DeepSeek 聊天和 `create_app`。
6. 日志不保存正文或向量数组，只保存模型、数量、token、延迟和状态。

- [x] **步骤 3：确认测试失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_chunker.py tests/unit/test_embeddings.py -q
```

- [x] **步骤 4：实现 Chunker 和 AsyncOpenAI 适配器**

Chunker 使用 markdown-it token 的 heading 与 source map，不以字符数作为唯一切分依据；token 编码固定
`cl100k_base`。每个 Chunk 带完整 H1-H3 标题前缀；短代码围栏、表格和列表保持完整，超长代码围栏拆成
多个闭合代码块。Embedding 生产实现直接使用官方 `AsyncOpenAI`，不经过 LiteLLM；拒绝空文本和超过
2048 项的单批输入，并严格校验返回模型、数量、index、维度和有限浮点数。

- [x] **步骤 5：验证并提交**

```powershell
uv run --locked pytest tests/unit/test_knowledge_chunker.py tests/unit/test_embeddings.py -q
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add src tests
git commit -m "feat: chunk and embed knowledge documents"
```

---

### 任务 4：创建三张知识表、消息引用列和增量同步 CLI

**小目标：** 使用非破坏性迁移持久化完整 Markdown、Chunk 与向量，并通过 CLI 原子发布新增或变化文档。

**文件：**

- 修改：`src/databricks_zh_expert/db/models.py`
- 创建：`alembic/versions/0004_knowledge_rag.py`
- 创建：`src/databricks_zh_expert/rag/repository.py`
- 创建：`src/databricks_zh_expert/rag/ingestion.py`
- 创建：`src/databricks_zh_expert/rag/cli.py`
- 修改：`pyproject.toml`
- 无需修改：`uv.lock`，任务 1 已固定全部直接依赖，`uv lock --check` 通过
- 修改：`tests/conftest.py`
- 修改：`tests/integration/test_migrations.py`
- 修改：`tests/unit/test_models.py`
- 创建：`tests/integration/test_knowledge_repository.py`
- 创建：`tests/unit/test_knowledge_ingestion.py`

**数据库变化：**

```text
kb_documents
kb_chunks
kb_ingestion_runs
messages.source_citations JSONB NULL
```

- [x] **步骤 1：写迁移失败测试**

至少覆盖：

1. 从 `0003_prompt_artifacts` 升级后只有三张新增知识表。
2. `kb_documents.normalized_content` 和增量同步字段存在。
3. `kb_chunks.embedding` 是 `VECTOR(1536)`，没有 HNSW 或 IVFFlat 索引。
4. `search_vector` 有 GIN 索引。
5. `messages.source_citations` 是可空 JSONB。
6. status、计数、唯一键和外键约束正确。
7. 升级前的 session、message 和 model_call 在升级后内容不变。
8. downgrade 只在测试数据库执行，并能回到 `0003`。

- [x] **步骤 2：写 Repository 和同步失败测试**

至少覆盖：

1. 首次同步写 document、chunks 和 succeeded run。
2. 304 或相同 normalized hash 跳过 Chunk 和 Embedding。
3. 只替换变化文档，不重建其他文档。
4. Embedding 或发布失败保留旧 document/chunks，run 为 partial/failed。
5. 发布事务中断不留下半套 Chunk。
6. 清单移除标记 disabled，不物理删除。
7. `--dry-run` 不写数据库、不调用 Embedding。
8. `--force` 只重建知识数据，不修改 sessions、messages 或 model_calls。

- [x] **步骤 3：确认测试失败**

```powershell
uv run --locked pytest tests/integration/test_migrations.py `
  tests/integration/test_knowledge_repository.py `
  tests/unit/test_knowledge_ingestion.py -q
```

- [x] **步骤 4：实现 ORM 和 Alembic 迁移**

使用 `pgvector.sqlalchemy.Vector(1536)`、PostgreSQL JSONB 和 TSVECTOR。迁移只新增表、索引和 nullable 列，
不得 truncate、删除或重写既有业务表。

- [x] **步骤 5：实现 Repository、同步状态机和 CLI**

同步顺序固定为 manifest -> catalogs -> fetch -> normalize -> hash -> chunk -> embed -> publish。网络和
Embedding 在事务外完成，每个文档使用单独发布事务。新增项目脚本：

```toml
databricks-zh-expert-kb = "databricks_zh_expert.rag.cli:main"
```

- [x] **步骤 6：升级开发数据库并保护验收数据**

迁移前记录 `sessions`、`messages`、`model_calls` 数量和两个验收 session。只执行：

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

迁移后数量不得减少，两个验收 session 必须仍存在。开发数据库禁止执行 downgrade。

- [x] **步骤 7：验证并提交**

```powershell
uv run --locked pytest tests/integration/test_migrations.py `
  tests/integration/test_knowledge_repository.py `
  tests/unit/test_knowledge_ingestion.py -q
uv run --locked databricks-zh-expert-kb status
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add pyproject.toml uv.lock src alembic tests
git commit -m "feat: persist and sync knowledge documents"
```

此任务的自动测试使用 fixture 或 MockTransport，并覆盖 `sync --dry-run` 的完整 CLI 路径；不从生产 CLI
暴露替换清单参数。真实官方 `sync --dry-run` 和同步均放到任务 7。

---

### 任务 5：实现 pgvector 精确检索与全文混合召回

**小目标：** 中文问题能稳定返回有限、可引用的官方 Chunk；没有足够相关内容时明确停止。

**文件：**

- 修改：`src/databricks_zh_expert/rag/repository.py`
- 创建：`src/databricks_zh_expert/rag/retrieval.py`
- 创建：`src/databricks_zh_expert/rag/context.py`
- 创建：`tests/unit/test_knowledge_retrieval.py`
- 创建：`tests/unit/test_rag_context.py`
- 修改：`tests/integration/test_knowledge_repository.py`

**公开接口：**

```python
class KnowledgeRetriever:
    async def retrieve(self, query: str) -> RetrievalBundle: ...
```

`RetrievalBundle` 是不可变内存对象，包含引用、选中 Chunk、分数和上下文，不写检索审计表。

- [x] **步骤 1：写数据库候选失败测试**

在测试库插入小规模固定向量，验证：

1. cosine distance 精确排序。
2. 只检索 active 文档。
3. 向量候选和全文候选上限生效。
4. `simple` 全文索引能命中英文 API 名、SQL 和代码标识符。
5. 数据库不存在 ANN 索引也能正常检索。

- [x] **步骤 2：写 RRF 和上下文失败测试**

至少覆盖：

1. 纯向量、纯全文和两边命中的 rank 融合。
2. 同分结果使用稳定 secondary key。
3. 重复 Chunk 去重，同文档相邻 Chunk 可合并。
4. 最终 top-k 和 5,000 token 预算同时生效。
5. 引用编号稳定为 S1...Sn。
6. 上下文包含标题、URL、heading 和“不可信资料”边界。
7. 阈值以下且无全文匹配时抛出 `KnowledgeContextNotFoundError`。

- [x] **步骤 3：确认测试失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_retrieval.py tests/unit/test_rag_context.py `
  tests/integration/test_knowledge_repository.py -q
```

- [x] **步骤 4：实现精确检索和 RRF**

查询 Embedding 只生成一次。向量和全文各取前 30，RRF 初始 `k=60`，最终前 6；数据库距离换算为
`similarity = 1 - cosine_distance`。不实现 query rewrite、reranker 或检索持久化。

- [x] **步骤 5：验证并提交**

```powershell
uv run --locked pytest tests/unit/test_knowledge_retrieval.py tests/unit/test_rag_context.py `
  tests/integration/test_knowledge_repository.py -q
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add src tests
git commit -m "feat: add hybrid knowledge retrieval"
```

---

### 任务 6：启用 knowledge_qa、历史引用、索引状态和 Trace 1.4

**小目标：** 现有消息 API 完成检索、模型调用、Artifact 保存和结构化引用，重新打开会话时引用不丢失。

**文件：**

- 修改：`src/databricks_zh_expert/prompts/registry.py`
- 修改：`src/databricks_zh_expert/prompts/templates/knowledge_qa.jinja2`
- 修改：`src/databricks_zh_expert/chat/schemas.py`
- 修改：`src/databricks_zh_expert/chat/repository.py`
- 修改：`src/databricks_zh_expert/chat/service.py`
- 修改：`src/databricks_zh_expert/api/chat.py`
- 创建：`src/databricks_zh_expert/api/knowledge_schemas.py`
- 创建：`src/databricks_zh_expert/api/knowledge.py`
- 修改：`src/databricks_zh_expert/api/dependencies.py`
- 修改：`src/databricks_zh_expert/core/errors.py`
- 修改：`src/databricks_zh_expert/observability/model_trace.py`
- 修改：`src/databricks_zh_expert/main.py`
- 修改：`tests/unit/test_prompt_registry.py`
- 修改：`tests/unit/test_prompt_renderer.py`
- 修改：`tests/unit/test_chat_service.py`
- 修改：`tests/unit/test_model_trace.py`
- 创建：`tests/integration/test_knowledge_api.py`
- 创建：`tests/integration/test_knowledge_messages_api.py`

- [x] **步骤 1：写 Prompt 和 ChatService 失败测试**

至少覆盖：

1. `knowledge_qa` 可用、版本 `1.1.0`，并要求现有回答章节加 `引用来源`。
2. 普通 Prompt 不调用 retriever，消息引用为 null。
3. `knowledge_qa` 先保存 user message，再检索一次。
4. 模型消息顺序为 system、历史、检索上下文、本轮问题。
5. 检索正文不进入 system message。
6. 无索引和无上下文均不调用 ModelGateway，不保存 assistant message/model_call。
7. Embedding 失败不触发聊天 fallback。
8. 聊天 fallback 多次 attempt 复用同一个 RetrievalBundle。
9. Artifact 失败遵守阶段 3 行为，不保存 assistant message。
10. 成功时 assistant message 和 `source_citations` 一起保存。

- [x] **步骤 2：写 API 与历史引用失败测试**

覆盖：

1. 发送消息响应包含最多 6 条结构化引用。
2. `GET /api/chat/sessions/{id}` 返回相同引用快照。
3. 非 RAG 历史消息的引用为 null。
4. `GET /api/knowledge/index/status` 正确表示未初始化、可查询、partial 和维度不匹配。
5. 不存在来源列表或同步写路由。
6. 普通 `/health/ready` 不因知识索引未构建而失败。

- [x] **步骤 3：写 Trace 1.4 失败测试**

覆盖：

1. `schema_version=1.4`。
2. RAG 调用包含 Embedding 模型、延迟、rank、score、chunk id 和 URL。
3. `request.messages` 包含实际检索正文。
4. 非 RAG 调用的 retrieval 为 null。
5. 不包含 API Key、Authorization、原始 HTML 或向量数组。

- [x] **步骤 4：确认测试失败**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py `
  tests/unit/test_chat_service.py tests/unit/test_model_trace.py `
  tests/integration/test_knowledge_api.py `
  tests/integration/test_knowledge_messages_api.py -q
```

- [x] **步骤 5：启用 Prompt 并接入 ChatService**

检索上下文作为明确标记的不可信 user 数据加入模型消息。结构化引用由 RetrievalBundle 生成，不解析模型自行
编写的 URL。`MessageResponse` 直接从持久化 `source_citations` 恢复历史引用。

- [x] **步骤 6：实现状态 API 和 Trace 1.4**

索引状态只读三张知识表和当前配置，不访问网络。Trace dataclass 接受不可变 retrieval snapshot，不在
序列化器里查询数据库，也不增加 model_calls 检索外键。

- [x] **步骤 7：验证并提交**

```powershell
uv run --locked pytest tests/unit/test_prompt_registry.py tests/unit/test_prompt_renderer.py `
  tests/unit/test_chat_service.py tests/unit/test_model_trace.py `
  tests/integration/test_knowledge_api.py `
  tests/integration/test_knowledge_messages_api.py -q
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
git add src tests
git commit -m "feat: add cited knowledge chat"
```

---

### 任务 7：固定检索评估、真实官方同步和阶段收尾

**小目标：** 使用固定中文问题验证检索质量，并用 DeepSeek 开发模型完成非破坏性真实 Demo 验收。

**文件：**

- 创建：`tests/evals/databricks_rag.yml`
- 修改：`src/databricks_zh_expert/rag/cli.py`
- 创建：`tests/unit/test_knowledge_eval.py`
- 修改：`README.md`，只增加必要启动步骤
- 修改：本计划，在实际执行时勾选任务状态
- 修改：设计规格，仅在实现与规格确有偏差时更新

- [ ] **步骤 1：创建固定中文评估集和 evaluator 测试**

至少 20 题，覆盖 Jobs、Medallion、Auto Loader、Streaming、Unity Catalog、SQL 性能、成本和精选 API 页面。
每题保存预期 source key、类别或 URL。evaluator 输出 Recall@5、MRR、失败题和实际来源，不调用聊天模型。

- [ ] **步骤 2：运行完整自动质量门禁**

```powershell
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic current
uv run --locked alembic check
```

覆盖率必须不低于 80%，Pyright/Pylance 不得有错误。

- [ ] **步骤 3：记录并保护现有验收数据**

真实同步前记录业务表数量和两个验收 session。不得运行 seed 清理、truncate、drop schema 或测试 fixture
清理命令。同步后业务表数量只能因人工聊天验收增加，不能减少。

- [ ] **步骤 4：真实 dry-run、同步和增量验证**

```powershell
uv run --locked databricks-zh-expert-kb sync --dry-run
uv run --locked databricks-zh-expert-kb sync
uv run --locked databricks-zh-expert-kb status
uv run --locked databricks-zh-expert-kb sync
uv run --locked databricks-zh-expert-kb evaluate
```

检查：

1. 只访问清单允许的 `docs.databricks.com` URL。
2. 数据库保存 normalized Markdown、Chunk 和向量，不保存原始 HTML。
3. 第二次同步时未变化文档跳过 Embedding。
4. active 文档约 30 至 50 篇，Chunk 数量处于合理范围。
5. `Recall@5 >= 80%`；不达标时只调整来源、Chunk 或 RRF 参数。

- [ ] **步骤 5：使用 DeepSeek V4 Flash 做真实聊天验收**

使用 `prompt=knowledge_qa`、`model=deepseek-v4-flash` 至少验证 Jobs、Unity Catalog、Streaming、SQL 性能和
超出范围的问题。确认查询 Embedding 使用 OpenAI，聊天使用 DeepSeek，响应和历史会话返回相同引用。

- [ ] **步骤 6：检查 Trace 与数据保护**

人工查看最新 1.4 JSONL，确认完整 RAG 上下文和分数存在，没有 Key、Authorization、原始 HTML 或向量数组；
两个验收 session 和既有数据仍存在且内容未改变。

- [ ] **步骤 7：精简更新 README**

只补充 `alembic upgrade head`、首次知识同步和服务启动命令。不新增 RAG 环境变量，也不加入内部架构、API
示例、预期输出或调试章节。

- [ ] **步骤 8：最终验证并提交**

```powershell
git diff --check
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
git status --short
git add README.md docs src tests knowledge pyproject.toml uv.lock alembic
git commit -m "test: complete stage four knowledge rag"
```

提交前确认没有 `.env`、Trace、数据库 dump、API Key、原始 HTML 或下载的官方正文文件。

## 阶段 4 完成定义

1. 来源范围固定为约 30 至 50 篇 Databricks 官方资料。
2. 一条 CLI 命令可以构建和增量更新知识库。
3. 数据库只新增三张知识表和一个消息引用列。
4. 未变化文档不重新生成 Embedding，失败文档保留上一版。
5. pgvector 精确检索与全文检索能够返回稳定上下文。
6. `knowledge_qa` 使用现有 Chat API 返回并持久化结构化官方引用。
7. 历史会话重新打开后引用仍然存在。
8. 无索引或无相关上下文时不调用聊天模型。
9. Trace 1.4 可以调试检索和完整模型上下文且不泄密。
10. 固定评估达到 `Recall@5 >= 80%`。
11. Ruff、Pyright/Pylance、pytest、覆盖率和 Alembic 门禁全部通过。
12. 所有既有业务和验收数据均未被清理或重写。
