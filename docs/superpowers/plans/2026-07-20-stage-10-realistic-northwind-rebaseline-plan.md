# 阶段 10：真实 Northwind Workspace 与评估再基线化实施计划

> **执行顺序：** 用户先完善 Workspace 项目内容，Agent 再适配程序、更新评估并运行模型。
> 用户确认 Workspace 完成前，不根据半成品修改固定评估，也不运行真实模型。

**目标：** 由用户把 Northwind Workspace 修改得更贴近真实项目；内容冻结后，Agent 根据最终文件调整 Registry、
Context 和评估集，并重新运行 `deepseek-v4-flash` 与 `deepseek-v4-pro` 基线。

**技术栈：** 继续使用现有 Python 3.12.10、FastAPI、Pydantic、PostgreSQL、Workspace Registry、pytest、Ruff 和
Pyright/Pylance。本阶段不预先增加依赖。

## 1. 谁先做

**用户先做。** 当前阶段的顺序固定为：

```text
Agent 建立文档骨架
  -> 用户手动完善 Workspace 内容
  -> 用户明确通知“Workspace 已完成”
  -> Agent 检查并冻结内容
  -> Agent 适配 Manifest / Registry / Context
  -> Agent 更新固定评估
  -> Agent 运行 Flash / Pro
  -> 用户审核代表性输出
  -> Agent 收尾并提交
```

## 2. 本轮 Agent 只做什么

1. 建立第 3 节的用户项目文档。
2. 保留已有 `requirements.md` 和 `business-rules.md` 的正文。
3. 在每份文档顶部增加中文注释，说明用途、维护责任和内容边界。
4. 不移动 `northwind-schema.sql`，不修改上游 SQL、许可证和来源说明。
5. 新文档暂不写入 `project.yml`，保证当前 Registry 继续按原契约启动。
6. 不更新 `workspace_context.yml` 或 `end_to_end.yml`。
7. 不调用 OpenAI、DeepSeek 或 Embedding API。

## 3. 用户需要完善的文件

```text
examples/workspaces/northwind_psql/.databricks-expert/
├── project.yml                         # 暂时由 Agent 维护，用户先不用改
├── requirements.md                     # 用户完善：需求、范围和待确认事项
├── business-rules.md                    # 用户完善：业务口径和数据规则
├── project/
│   ├── source-system.md                 # 用户完善：源系统和数据边界
│   ├── architecture.md                  # 用户完善：摄取与目标架构约束
│   ├── data-products.md                 # 用户完善：分析产品、粒度和指标
│   ├── data-quality.md                  # 用户完善：质量规则和异常处置
│   └── governance-and-operations.md     # 用户完善：权限、SLA、监控和成本
├── glossary/
│   └── business-glossary.md             # 用户按需完善：统一业务术语
└── source-schema/
    └── northwind-schema.sql             # 已有源 DDL，通常不需要修改
```

为保持当前服务可运行，`requirements.md` 和 `business-rules.md` 本阶段先保留在输入包根目录。用户完成后，Agent 再根据
最终文件结构决定是否移动文件和升级 Manifest，不在用户编辑前预设复杂契约。

## 4. 用户编辑规则

每项信息使用以下状态之一：

```text
状态：已确认
状态：设计约束
状态：待确认
状态：不在范围
```

用户可以修改或增加项目事实，但不要加入：

1. 密钥、连接串、真实账号或企业机密。
2. Agent 生成的 SQL、PySpark、Notebook 或 Workflow。
3. 尚不存在的 Bronze、Silver、Gold 物理表定义。
4. 为通过测试而刻意虚构的字段、指标或业务规则。
5. “已经部署”“已经执行”“已经验证”等未经证实的状态。

以下文件保持不变：

```text
upstream/northwind.sql
UPSTREAM.md
LICENSE.northwind
```

`source-schema/northwind-schema.sql` 只有在源数据库结构确实需要改变时才修改。

## 5. 用户完成后的 Agent 工作

### 任务 1：检查并冻结 Workspace

1. 阅读用户修改的全部文件和 Git diff。
2. 检查文件之间是否存在冲突、重复口径、虚构字段或未标状态的假设。
3. 只报告问题，不擅自改写用户业务决定。
4. 用户确认后固定 Workspace 版本和内容 Hash。

### 任务 2：适配程序契约

1. 根据最终文件结构更新 `project.yml`。
2. 只有实际需要时才升级 Workspace Manifest 和 Registry。
3. 将最终文档注册为只读项目输入。
4. 保持用户文件与 Agent 生成内容分离。
5. 更新 Context 选择和 Trace 审计，使每个选中片段可追溯到具体文件。

### 任务 3：更新固定评估

1. 归档阶段 9 的 `workspace_context.yml` 和 `end_to_end.yml`。
2. 根据最终 Workspace 内容更新检索问题和预期证据。
3. 保留原有 Northwind Case 中仍然有效的部分。
4. 增加跨文件、待确认事项和冲突规则的测试，但不为测试虚构项目内容。
5. 在看到模型回答前固定 Hard/Soft 门禁。

### 任务 4：离线验证

```powershell
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
uv run --locked alembic check
uv run --locked databricks-zh-expert-workspaces evaluate
uv run --locked databricks-zh-expert-evals validate
```

离线验证通过前不运行真实模型。

### 任务 5：重新运行双模型基线

1. 使用新的 Run ID，不覆盖 `stage9-final-v2-20260720`。
2. 运行 `deepseek-v4-flash` 完整评估。
3. 运行 `deepseek-v4-pro` 完整评估。
4. 保存全部 Session、Message、ModelCall、Trace、JSON 和 Markdown 报告。
5. 生成两个模型对比以及阶段 9/10 纵向对比。

### 任务 6：用户最终审核

用户检查两个模型各一份 SQL、PySpark 和 Workflow，共 6 份。Agent 根据审核结论记录结果，但不覆盖原始模型输出。

## 6. 阶段边界

1. 不直接操作 Databricks、AWS 或源数据库。
2. 不执行生成的 SQL、PySpark、Notebook 或 Workflow。
3. 不清理任何历史 Session、Message、ModelCall、Trace 或评估结果。
4. 不把 Workspace 正文复制到 PostgreSQL。
5. 不引入 LangGraph、通用文件工具、AI 关键词提取或上下文压缩；这些属于后续阶段。
6. 不制作任何前端或桌面客户端。
7. README 没有新增启动步骤，本阶段不修改 README。

## 7. 完成标准

1. 用户完成并确认 Workspace 项目内容。
2. Agent 根据最终内容完成程序契约和评估适配。
3. Workspace Context 固定评估通过预先确定的门禁。
4. Flash 和 Pro 均通过正式 Chat API 完成新版评估。
5. 用户完成 6 份代表性输出审核。
6. 新旧数据集、Workspace、Prompt、模型、Run 和日志可以独立比较。
7. 全量测试、Ruff、Pyright/Pylance 和 Alembic 检查通过。

## 8. 当前状态（2026-07-23）

Agent 侧实现、离线验收和真实双模型再基线均已完成：

1. Northwind Workspace 已冻结为 `2.0.0`，Source Hash 为
   `3dfa0751cf9ef2aa26d8b7d7728d4b60e4bcc394420544ba2df55d4a6cf6b3fb`。
2. 最终 9 份项目输入已注册；Context 共生成 519 个可追溯单元。
3. Workspace 固定评估命中 `45/45`，`Recall@5=100%`，上下文泄漏为 `0`。
4. 端到端数据集已冻结为 `stage10_northwind_end_to_end` `2.0.0`，数据集 Hash 为
   `afc66e4d68511d9d40dc545700442434c75abecf0ecaa4688dd0f10a6e8e15f0`。
5. 正式 Run ID 为 `stage10-final-20260723`。Flash 的 Hard Pass 为 `87.50%`、Soft 平均为
   `85.42%`；Pro 的 Hard Pass 为 `81.25%`、Soft 平均为 `80.21%`。两种模型各发生一次
   fallback，所有原始调用和结果均已保留。
6. 横向报告、相对 `stage9-final-v2-20260720` 的纵向报告，以及两个模型各 3 份人工抽查输出均已生成。
7. Ruff、Pyright/Pylance、Alembic 和全量测试均通过；测试结果为 `538 passed`，覆盖率为 `87.99%`。

第 6 节规定的 6 份代表性输出已于 `2026-07-23` 完成审核。最终状态为 `rejected`，中文结论为
“需要修改”：这些输出可作为讨论和修改底稿，但不应原样进入项目开发或交付。审核记录保存在
`.local/evaluations/stage10-final-20260723/manual-review.md`，只追加结论，不覆盖原始模型输出、自动评分、
Trace 或数据库审计。

因此，阶段 10 的 Workspace 冻结、程序适配、固定评估、双模型真实运行和人工审核均已完成；输出质量问题作为
后续精度提升工作的已知基线保留。
