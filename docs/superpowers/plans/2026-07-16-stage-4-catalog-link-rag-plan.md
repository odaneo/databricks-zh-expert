# 阶段 4：目录站外链接检索实施计划

> **执行要求：** 使用 `superpowers:executing-plans` 在当前会话逐任务执行，不使用子智能体。每个任务先写
> 失败测试，再做最小实现并运行 Pyright/Pylance。不得清理现有业务、验收或知识库数据。

**目标：** 将两个官方 `llms.txt` 目录中的全部站外 HTTPS 链接作为可检索的“仅链接来源”持久化，使价格
问题返回 Databricks Pricing 官方 URL，同时不抓取或伪装已读取目标页面正文。已抓取的普通官方文档及其中
保留的外链仍可正常参与回答。

**架构：** 复用 `kb_documents` 和 `kb_chunks`，新增 `catalog_link` 来源类型和文档级 `catalog_id`。目录标题、
摘要和 URL 生成一个短 Chunk 与 Embedding；同步器对该类型走本地规范化分支，永远不调用正文 fetcher。
检索上下文携带 `link_only` 标记，`knowledge_qa` 系统 Prompt 限制模型只能提供链接元数据。

**技术栈：** Python 3.12.10、SQLAlchemy 2.0.51、Alembic 1.18.5、PostgreSQL 18、pgvector、OpenAI
`text-embedding-3-small`、pytest、Ruff、Pyright。

## 全局约束

1. Docs 和 API 两个目录中的全部站外 HTTPS 链接统一收录，不允许 Pricing URL 特判或外链白名单。
2. 站外 URL 不得进入 `fetch_catalog()` 或 `fetch()` 的 HTTP 请求队列。
3. 只保存目录标题、摘要、URL 和固定的“未抓取目标正文”说明。
4. 每个链接只生成一个 Chunk；`source_ref` 必须等于目标 URL，不追加 anchor。
5. 用户询问价格时必须返回 Pricing URL 和“以官网最新信息为准”；不得把未抓取的 Pricing 页面当作事实
   来源。已抓取的普通官方文档及其保留外链可以按各自 citation 正常使用。
6. 外链同样使用两次成功目录快照缺失才 disabled 的规则；目录失败不改变缺失计数。
7. 不新增知识表，不修改现有 Chat API 路径，不清理任何已有数据。
8. 每次 Python 修改后运行 Ruff 和 Pyright；完整测试覆盖率必须不低于 80%。

---

### 任务 1：让目录外链成为可持久化来源并迁移目录身份

**文件：**

- 修改：`src/databricks_zh_expert/rag/types.py`
- 修改：`src/databricks_zh_expert/rag/catalogs.py`
- 修改：`src/databricks_zh_expert/db/models.py`
- 创建：`alembic/versions/0006_catalog_link_sources.py`
- 修改：`tests/unit/test_knowledge_sources.py`
- 修改：`tests/unit/test_models.py`
- 修改：`tests/integration/test_migrations.py`

**接口：**

- `SourceKind.CATALOG_LINK = "catalog_link"`。
- `ExternalCatalogLink` 替换为字段完整的 `DiscoveredSource`。
- `CatalogDiscoveryResult.all_sources` 返回正文来源与链接来源的稳定有序合并结果。
- `KnowledgeDocument.catalog_id: str` 非空，并创建 `ix_kb_documents_catalog_id`。

- [x] **步骤 1：先写目录外链领域测试**

断言 fixture 中 Pricing 和其他站外链接全部出现在 `external_links`，每项都有稳定 source key、
`kind=SourceKind.CATALOG_LINK`、目录 ID、category、cloud、locale、标题、摘要和原始 HTTPS URL。重复外链只保留
一次，非 HTTPS、凭据和自定义端口继续拒绝。

- [x] **步骤 2：先写 ORM 与 0006 迁移测试**

断言 `kb_documents.catalog_id` 非空、来源类型检查包含 `catalog_link`、目录 ID 索引存在；迁移必须保留现有
document id、正文、Chunk 和业务表数据，并按 `general_html/api_markdown` 回填两个固定 catalog ID。

- [x] **步骤 3：运行测试并确认旧实现失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_sources.py tests/unit/test_models.py `
  tests/integration/test_migrations.py -q
```

预期：外链仍是不可持久化的简化类型，ORM 没有 `catalog_id`，迁移 head 仍是 0005。

- [x] **步骤 4：实现领域类型、目录解析和迁移**

目录解析器对站外链接构造：

```python
DiscoveredSource(
    source_key=self._source_key(catalog.id, url),
    kind=SourceKind.CATALOG_LINK,
    title=link.title,
    url=url,
    category=self._catalog_link_category(catalog, link.topic),
    catalog_id=catalog.id,
    cloud=catalog.cloud,
    locale=catalog.locale,
    topic=link.topic,
    summary=link.summary,
)
```

0006 迁移增加 `catalog_id VARCHAR(100)`，回填后改为非空；替换来源类型 check 并创建目录 ID 索引。降级前把
`catalog_link` 按目录还原为 `general_html` 或 `api_markdown`，从而保留知识数据。

- [x] **步骤 5：运行聚焦门禁**

```powershell
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked pytest tests/unit/test_knowledge_sources.py tests/unit/test_models.py `
  tests/integration/test_migrations.py -q
```

---

### 任务 2：实现仅链接同步分支和按目录缺失确认

**文件：**

- 修改：`src/databricks_zh_expert/rag/normalizer.py`
- 修改：`src/databricks_zh_expert/rag/ingestion.py`
- 修改：`src/databricks_zh_expert/rag/repository.py`
- 修改：`tests/unit/test_knowledge_sources.py`
- 修改：`tests/unit/test_knowledge_ingestion.py`
- 修改：`tests/integration/test_knowledge_repository.py`

**接口：**

- `KnowledgeNormalizer.normalize_catalog_link(source: DiscoveredSource) -> NormalizedDocument`。
- `IngestionRepository.reconcile_catalog_presence(catalog_id: str, observed_source_keys: set[str], *, observed_at: datetime)`。
- `KnowledgeRepository.reconcile_source_identities()` 使用 `catalog_id + source_url` 识别来源。

- [x] **步骤 1：写仅链接规范化与零抓取失败测试**

断言 Pricing 生成的 Markdown 只包含标题、目录摘要、URL 和固定免责声明；不包含价格、DBU 或套餐数据。
`sync --dry-run` 与真实 `sync` 的 Fake fetcher 调用列表都不能出现任何站外 URL。

- [x] **步骤 2：写发布、增量和缺失状态失败测试**

断言首次同步为每条外链发布一个 document、一个 Chunk 和一个 Embedding；第二次摘要与 URL 未变化时 skipped
且不调用 Embedding。摘要变化只重建对应链接。第一次目录缺失仍 active，第二次缺失才 disabled；Docs/API
目录失败互不影响。

- [x] **步骤 3：运行测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_sources.py tests/unit/test_knowledge_ingestion.py `
  tests/integration/test_knowledge_repository.py -q
```

- [x] **步骤 4：实现本地规范化和同步分支**

`normalize_catalog_link()` 返回无 Markdown 标题的短内容，确保 Chunker 不给 URL 添加 anchor：

```text
资料类型：官方目录链接（未抓取目标正文）

标题：Pricing

目录摘要：Databricks pricing information

官方链接：https://www.databricks.com/product/pricing
```

`_validate_fetches()` 对 `catalog_link` 只验证本地结构；`_sync_source()` 直接规范化、计算哈希、切分、Embedding
和事务发布。presence reconciliation 改用 `catalog_id`，每次成功目录将 `all_sources` 一起协调。

- [x] **步骤 5：运行聚焦门禁**

```powershell
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked pytest tests/unit/test_knowledge_sources.py tests/unit/test_knowledge_ingestion.py `
  tests/integration/test_knowledge_repository.py -q
```

---

### 任务 3：让检索上下文和 Prompt 强制执行仅链接回答

**文件：**

- 修改：`src/databricks_zh_expert/rag/repository.py`
- 修改：`src/databricks_zh_expert/rag/retrieval.py`
- 修改：`src/databricks_zh_expert/rag/context.py`
- 修改：`src/databricks_zh_expert/prompts/registry.py`
- 修改：`src/databricks_zh_expert/prompts/templates/knowledge_qa.jinja2`
- 修改：`tests/evals/databricks_rag.yml`
- 修改：`tests/unit/test_knowledge_retrieval.py`
- 修改：`tests/unit/test_rag_context.py`
- 修改：`tests/unit/test_prompt_registry.py`
- 修改：`tests/unit/test_chat_service.py`
- 修改：`tests/unit/test_knowledge_eval.py`

**接口：**

- `KnowledgeCandidate.link_only: bool`。
- `RankedKnowledgeChunk.link_only: bool`。
- `knowledge_qa` Prompt 版本提升为 `1.2.0`。

- [x] **步骤 1：写 link_only 传播和上下文失败测试**

断言 `kb_chunks.metadata.link_only=true` 从 Repository 传播到排序结果；上下文渲染
`资料类型：官方目录链接（未抓取目标正文）`，citation URL 精确等于 Pricing URL。

- [x] **步骤 2：写 Prompt 与评估失败测试**

Prompt 必须明确禁止用模型记忆补充目录链接目标页事实，同时允许已抓取的普通官方文档按各自 citation 正常
参与回答。固定评估增加：

```yaml
- id: cost-pricing-link
  question: Databricks 的最新价格在哪里查看？
  expected_urls:
    - https://www.databricks.com/product/pricing
```

- [x] **步骤 3：运行测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_knowledge_retrieval.py tests/unit/test_rag_context.py `
  tests/unit/test_prompt_registry.py tests/unit/test_chat_service.py tests/unit/test_knowledge_eval.py -q
```

- [x] **步骤 4：实现标记传播、上下文与 Prompt**

Repository 从 `chunk.metadata` 读取 `link_only`；RRF 保留该字段；上下文对仅链接来源增加类型行。Prompt 要求
模型明确该目标正文未抓取、只把目录标题、摘要和 URL 归因于该条目；普通官方文档仍可正常使用。同步更新
Prompt Registry 版本和审计断言。

- [x] **步骤 5：运行聚焦门禁**

```powershell
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pyright
uv run --locked pytest tests/unit/test_knowledge_retrieval.py tests/unit/test_rag_context.py `
  tests/unit/test_prompt_registry.py tests/unit/test_chat_service.py tests/unit/test_knowledge_eval.py -q
```

---

### 任务 4：真实迁移、全量同步和价格问答验收

**文件：**

- 修改：`docs/superpowers/plans/2026-07-06-databricks-agent-demo-master-plan.md`
- 修改：`docs/superpowers/plans/2026-07-12-stage-4-prebuilt-databricks-rag-plan.md`
- 修改：`docs/superpowers/specs/2026-07-12-stage-4-prebuilt-databricks-rag-design.md`
- 修改：本计划，仅勾选实际完成步骤并记录结果

- [x] **步骤 1：记录只读数据基线并升级数据库**

记录 `sessions`、`messages`、`model_calls`、知识表数量和两个阶段 3 验收 session。执行：

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
```

- [x] **步骤 2：执行真实增量同步**

```powershell
uv run --locked databricks-zh-expert-kb sync --dry-run
uv run --locked databricks-zh-expert-kb sync
uv run --locked databricks-zh-expert-kb status
uv run --locked databricks-zh-expert-kb sync
```

验收全部当前目录外链变成 active `catalog_link`；Pricing 的 `source_url`、`canonical_url` 和 Chunk
`source_ref` 完全一致。第二次同步全部未变化来源 skipped，不重复 Embedding。不得删除已有 1,254 篇文档。

- [x] **步骤 3：执行真实检索与聊天验收**

```powershell
uv run --locked databricks-zh-expert-kb evaluate
```

评估 `Recall@5 >= 80%` 且价格题召回 Pricing URL。再用 `deepseek-v4-flash` 和 `prompt=knowledge_qa` 提问价格，
保留真实消息、model call 和 Trace；回答必须出现 Pricing URL，且不能声称已读取 Pricing 目标页。普通官方
文档正文中的定价说明和保留外链允许出现。

- [x] **步骤 4：运行完整质量门禁**

```powershell
git diff --check
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
```

- [x] **步骤 5：复核数据保护并更新中文文档**

只读确认业务和验收数据没有减少，站外正文请求数为 0，目录外链数量与数据库 active `catalog_link` 数一致。
记录实时文档数、Chunk 数、评估结果和价格回答验收结果。不得提交 `.env`、API Key、Trace、数据库 dump、
官方目录下载副本或批量正文。

**2026-07-16 实测记录：**

1. 迁移前基线为 `sessions=42`、`messages=360`、`model_calls=32`、active 文档 `1254`、Chunk
   `17664`；两个阶段 3 验收会话均存在。数据库从 `0005` 成功升级到 `0006_catalog_link_sources`。
2. 真实同步发现 `1259` 个来源：Docs 目录 `225` 个（含 4 个 `catalog_link`），API 目录 `1034` 个；首次
   增量同步 `changed=28`、`skipped=1231`、`failed=0`。紧接着第二次同步 `changed=0`、
   `skipped=1259`、`failed=0`，未重复生成 Embedding。
3. 数据库现有 active 文档 `1259`、Chunk `17712`。Pricing、Training、Knowledge Base 和 Community 四条
   站外目录链接均为 active、每条一个 Chunk、`link_only=true`，URL 与 `source_ref` 完全一致；Pricing
   只保存目录标题、摘要和 URL，抓取响应元数据为空。
4. 固定 28 题真实评估得到 `Recall@5=92.86%`、`MRR=83.93%`；价格题在第 1 名召回
   `https://www.databricks.com/product/pricing`。
5. 使用 `deepseek-v4-flash` 完成并保留两次 Pricing 真实会话、消息、model call 和 Trace。最终产品边界为：
   不抓取目录站外目标页；已抓取的普通官方文档及其正文中保留的外链可以正常参与回答。
6. 最终只读计数为 `sessions=44`、`messages=364`、`model_calls=34`，增长仅来自上述两次保留验收；阶段 3
   验收会话仍为 2 条，active 来源 URL 重复数为 0。
7. `git diff --check`、`uv lock --check`、Ruff、Pyright、Alembic check 均通过；306 条 pytest 全部通过，
   覆盖率 `90.30%`，用时 `13.72s`。

- [x] **步骤 6：等待用户确认后提交**

用户已确认直接在当前分支提交，不创建分支或 PR：

```powershell
git add docs knowledge src tests alembic pyproject.toml uv.lock README.md
git commit -m "feat: index official catalog links"
```
