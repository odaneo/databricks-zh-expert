# 项目分类字段移除实施计划

> **执行要求：** 使用 TDD 按任务顺序实施；每个任务先观察目标测试失败，再写最小实现。用户要求本轮不提交 Git。

**目标：** 从当前 Workspace 和专家模板契约中完整移除项目模式与模拟标识，同时通过 `0009` 无损升级现有数据库。

**架构：** Workspace 只保留项目身份、版本、云和用户事实来源；专家模板只通过 Profile、Layer 和 Cloud 表达适用
范围。历史迁移和 Trace 保留旧版本事实，新数据库结构与 Trace 1.7 不再携带两个分类字段。

**技术栈：** Python 3.12.10、Pydantic 2、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、pytest、Ruff、Pyright。

## 全局约束

1. 不修改 `0007`、`0008` 历史迁移。
2. 不删除 Session、Message、ModelCall、模板版本、Chunk、Embedding、同步记录或 Trace。
3. 不增加替代字段、隐式常量或兼容别名。
4. 旧字段再次出现在 YAML 时必须由 `extra=forbid` 拒绝。
5. 37 个当前专家模板必须提升版本，不能同版本覆盖。
6. 新 Trace 使用 1.7；历史 Trace 1.6 不改写。
7. README 没有新增启动步骤，不修改。
8. 本轮完成后保留未提交改动，等待用户审核。

---

## 任务 1：移除 Workspace 当前契约

**文件：**

- Modify: `examples/workspaces/retail_sales_demo/.databricks-expert/project.yml`
- Modify: `tests/fixtures/workspaces/valid/retail_sales_demo/.databricks-expert/project.yml`
- Modify: `src/databricks_zh_expert/workspace/types.py`
- Modify: `src/databricks_zh_expert/workspace/registry.py`
- Modify: `src/databricks_zh_expert/workspace/context.py`
- Modify: `src/databricks_zh_expert/api/workspace_schemas.py`
- Modify: `tests/unit/test_workspace_registry.py`
- Modify: `tests/unit/test_workspace_context.py`
- Modify: `tests/unit/test_retail_workspace_content.py`
- Modify: `tests/integration/test_workspaces_api.py`

**产出接口：** `WorkspaceDefinition` 和 `WorkspaceContextBundle` 不再包含分类字段；Workspace API 不返回分类字段。

- [x] **步骤 1：先修改测试和有效夹具**

```python
assert "workspace_mode" not in response.json()
assert "is_mock" not in response.json()
assert not hasattr(workspace, "workspace_mode")
assert not hasattr(workspace, "is_mock")
```

增加两个旧键拒绝用例：向 `project.yml` 注入任一旧键时，Registry 返回“包含未支持字段”。

- [x] **步骤 2：观察 RED**

```powershell
uv run --locked pytest tests/unit/test_workspace_registry.py tests/unit/test_workspace_context.py tests/unit/test_retail_workspace_content.py tests/integration/test_workspaces_api.py -q
```

预期：旧 Pydantic 必填字段缺失或 API 仍返回旧字段，测试失败。

- [x] **步骤 3：实现最小删除**

删除 `WorkspaceMode`、清单模型字段、领域类型字段、Registry 映射、Context Bundle 字段和 API Schema 字段；删除两份
`project.yml` 中的旧键。保留 `extra="forbid"`。

- [x] **步骤 4：观察 GREEN**

运行步骤 2 的测试，预期全部通过。

---

## 任务 2：移除 Chat、审计和 Trace 当前契约

**文件：**

- Modify: `src/databricks_zh_expert/chat/repository.py`
- Modify: `src/databricks_zh_expert/chat/service.py`
- Modify: `src/databricks_zh_expert/observability/model_trace.py`
- Modify: `tests/unit/test_chat_service.py`
- Modify: `tests/unit/test_model_trace.py`
- Modify: `tests/integration/test_workspace_code_generation_messages_api.py`

**产出接口：** `ChatRepository.create_model_call()`、`ModelCallTrace` 和 Trace 1.7 不再接收或输出项目模式。

- [x] **步骤 1：先修改测试**

```python
assert payload["schema_version"] == "1.7"
assert "workspace_mode" not in payload["trace"]
assert not hasattr(model_call, "workspace_mode")
```

同步删除测试 Repository/Fake 参数和调用断言。

- [x] **步骤 2：观察 RED**

```powershell
uv run --locked pytest tests/unit/test_chat_service.py tests/unit/test_model_trace.py tests/integration/test_workspace_code_generation_messages_api.py -q
```

预期：Trace 仍为 1.6 或仍输出旧字段，测试失败。

- [x] **步骤 3：实现最小删除**

删除 ChatService 透传、Repository 参数、`ModelCallTrace` 字段和序列化键，将新日志 `schema_version` 改为 `1.7`。

- [x] **步骤 4：观察 GREEN**

运行步骤 2 的测试；数据库模型暂未迁移导致的失败留给任务 4，其余测试必须通过。

---

## 任务 3：移除专家模板当前契约并版本化资产

**文件：**

- Modify: `knowledge/expert_templates/profiles.yml`
- Modify: `knowledge/expert_templates/**/*.md`
- Modify: `tests/fixtures/expert_templates/valid/profiles.yml`
- Modify: `tests/fixtures/expert_templates/valid/**/*.md`
- Modify: `src/databricks_zh_expert/expert_templates/types.py`
- Modify: `src/databricks_zh_expert/expert_templates/registry.py`
- Modify: `src/databricks_zh_expert/expert_templates/repository.py`
- Modify: `src/databricks_zh_expert/api/expert_template_schemas.py`
- Modify: `tests/unit/test_expert_template_registry.py`
- Modify: `tests/unit/test_expert_template_content.py`
- Modify: `tests/integration/test_expert_template_repository.py`
- Modify: `tests/integration/test_expert_templates_api.py`

**产出接口：** Profile、Template Source、API Response 和持久化映射不再包含模拟标识。

- [x] **步骤 1：先修改测试和有效夹具**

```python
assert "is_mock" not in profile_payload
assert "is_mock" not in template_payload
assert not hasattr(profile, "is_mock")
assert not hasattr(template, "is_mock")
```

增加旧 Front Matter/Profile 键拒绝用例，并保留目录、Layer、Profile、Cloud 所有权校验。

- [x] **步骤 2：观察 RED**

```powershell
uv run --locked pytest tests/unit/test_expert_template_registry.py tests/unit/test_expert_template_content.py tests/integration/test_expert_template_repository.py tests/integration/test_expert_templates_api.py -q
```

预期：Pydantic 仍要求旧字段或 API 仍返回旧字段，测试失败。

- [x] **步骤 3：删除字段并提升版本**

删除 Profile 和 37 个模板中的旧元数据；删除类型、Registry Hash、校验、Repository 和 API Schema 字段。所有当前模板
版本按 `1.0.0 -> 1.1.0`、`1.1.0 -> 1.2.0` 提升，测试夹具同步契约但不承担生产版本历史。

- [x] **步骤 4：观察 GREEN**

运行步骤 2 的测试，预期全部通过。

---

## 任务 4：新增 `0009` 无损数据库迁移

**文件：**

- Create: `alembic/versions/0009_remove_project_classification_fields.py`
- Modify: `src/databricks_zh_expert/db/models.py`
- Modify: `tests/unit/test_models.py`
- Modify: `tests/integration/test_migrations.py`

**产出接口：** 当前 SQLAlchemy Metadata 和数据库 head 均不存在两个分类列及项目模式约束。

- [x] **步骤 1：先修改模型与迁移测试**

```python
assert "workspace_mode" not in model_call_columns
assert "is_mock" not in expert_template_columns
assert "ck_model_calls_workspace_mode" not in check_constraints
```

- [x] **步骤 2：观察 RED**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py -q
```

预期：当前 ORM 和迁移 head 仍包含旧列，测试失败。

- [x] **步骤 3：实现 Migration 与模型删除**

`upgrade()` 先删除项目模式约束，再删除 `model_calls` 的项目模式列和 `expert_templates` 的模拟标识列。
`downgrade()` 重建两列；项目模式按非空 `workspace_id` 回填，模板模拟标识按 `layer <> 'core'` 回填，然后恢复约束。

- [x] **步骤 4：验证迁移链**

```powershell
uv run --locked pytest tests/unit/test_models.py tests/integration/test_migrations.py -q
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

执行结果：测试通过，当前版本为 `0009_drop_classification_fields (head)`，无新增迁移差异。

---

## 任务 5：同步、文档和最终门禁

**文件：**

- Modify: `docs/superpowers/specs/2026-07-16-stage-5-databricks-expert-template-library-design.md`
- Modify: `docs/superpowers/plans/2026-07-16-stage-5-databricks-expert-template-library-plan.md`
- Modify: `docs/superpowers/specs/2026-07-17-stage-6-project-aware-code-generation-design.md`
- Modify: `docs/superpowers/plans/2026-07-17-stage-6-project-aware-code-generation-plan.md`
- Modify: `docs/superpowers/plans/2026-07-18-remove-project-classification-fields-plan.md`

- [x] **步骤 1：清理现行文档**

删除旧字段作为现行契约的描述；只在历史迁移说明和本次删除规格/计划中保留名称。

- [ ] **步骤 2：模板 dry-run 与真实同步**

```powershell
uv run --locked databricks-zh-expert-templates sync --dry-run
uv run --locked databricks-zh-expert-templates sync
uv run --locked databricks-zh-expert-templates evaluate
```

预期：37 个新版本可同步，旧版本 inactive；`Recall@3 >= 90%`，Profile 泄漏和继承缺失为 0。

执行记录：dry-run 已通过，结果为新增 37、激活 37、停用 37、失败 0，共 121 个 Chunk。真实同步需要把
模板 Chunk 发送给 OpenAI Embedding，当前执行环境的外部发送策略拒绝该操作，因此未执行真实同步与基于新版本的
真实评估；未绕过策略，也未改写现有模板数据。

- [x] **步骤 3：Workspace 与全量质量门禁**

```powershell
uv run --locked databricks-zh-expert-workspaces evaluate
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
git diff --check
git status --short
```

预期：Workspace `Recall@5 >= 90%`，覆盖率不低于 80%，静态检查和全量测试全部通过；改动保持未提交。

执行结果：Workspace `Recall@5 = 100%`、上下文泄漏 0；Ruff 和 Pyright 通过；全量测试 `497 passed`，覆盖率
`88.50%`；`git diff --check` 通过。改动保持未提交。
