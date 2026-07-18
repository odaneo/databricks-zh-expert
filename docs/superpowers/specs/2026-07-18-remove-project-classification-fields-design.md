# 项目分类字段移除设计

## 1. 背景

当前 Workspace 契约使用 `workspace_mode=greenfield`，Workspace 和专家模板又使用 `is_mock` 区分模拟内容。
产品已经确认：接入系统的项目都按真实项目处理，当前也只支持从需求、规则和源 Schema 开始设计的新项目；这两个
字段没有业务分支价值，反而增加配置、API、数据库和审计耦合。

## 2. 设计决策

1. 不再保存、返回或校验项目模式。
2. 不再区分模拟项目、真实项目、模拟模板或真实模板。
3. 不增加替代字段、隐式常量或兼容别名。
4. Workspace 仍只接收需求、业务规则和源 Schema，目标 DDL、Mapping 和代码仍是未确认 proposal。
5. 专家模板继续通过 `layer`、`profile` 和 `cloud` 表达适用范围，这些字段具有真实检索和继承语义，予以保留。

## 3. 当前契约变更

### Workspace

从以下位置删除两个分类字段：

1. `.databricks-expert/project.yml`。
2. Pydantic 清单模型、领域类型、Registry 和 Context Bundle。
3. `GET /api/workspaces` 与 `GET /api/workspaces/{workspace_id}` 响应。
4. ChatService、Repository 和 `model_calls` 审计。
5. Trace 中的 Workspace 元数据。
6. 示例工作区、测试夹具、测试断言以及阶段 6 现行文档。

删除后，Workspace API 只返回 ID、名称、说明、版本、cloud、source Hash、源文件数量和相对路径。

### 专家模板

从以下位置删除模拟标识：

1. `profiles.yml`。
2. 37 个专家模板 Front Matter。
3. Pydantic 模型、领域类型、Registry 校验、Repository 和数据库模型。
4. `GET /api/expert-templates` 响应。
5. 测试夹具、测试断言以及阶段 5 现行文档。

删除后，core 与覆盖层的所有权继续由目录、`layer` 和 `profile` 校验，不再附加模拟标识一致性规则。

## 4. 数据库迁移

新增 Alembic `0009`：

1. 删除 `model_calls` 上的项目模式约束和列。
2. 删除 `expert_templates` 上的模拟标识列。
3. 不删除或重写任何 Session、Message、ModelCall、模板版本、Chunk、Embedding、同步记录或 Trace 文件。

`0007` 和 `0008` 已经应用，必须保留原始定义，确保现有数据库和全新数据库使用同一迁移链。两个旧字段名称只允许
继续出现在历史迁移及 `0009` 的删除/降级代码中。

降级仅用于技术回滚：项目模式按已有 `workspace_id` 恢复为 `greenfield`；模板模拟标识按 `layer != core` 恢复。

## 5. 模板版本与同步

模拟标识当前参与模板规范化 Hash。删除该元数据后，全部 37 个模板的 `content_hash` 都会变化。为保持
`template_id + version` 不可变：

1. 所有当前模板提升版本，不覆盖同版本记录。
2. 运行模板 dry-run，确认全部当前模板被识别为新版本。
3. 执行原子同步和 Embedding，激活新版本并将旧版本设为 inactive。
4. 运行固定模板评估，门禁仍为 `Recall@3 >= 90%`，Profile 泄漏和继承缺失为 0。

不通过忽略 Hash、原地改写数据库或隐藏派生模拟标识绕过版本规则。

## 6. Trace 兼容性

新模型调用日志升级为 Trace 1.7，并从当前结构中删除项目模式。已有 Trace 1.6 是保留的验收数据，不做改写或清理；
它和历史迁移一样只代表旧版本事实，不再构成当前契约。

## 7. 测试与验收

1. 先修改契约测试并确认因旧字段仍存在而失败。
2. Registry 能加载不包含分类字段的 Workspace 和专家模板。
3. 清单中再次出现已删除字段时，由 Pydantic `extra=forbid` 拒绝，避免静默保留旧配置。
4. Workspace 和专家模板 API 响应不包含已删除字段。
5. `model_calls`、Trace 1.7 和 SQLAlchemy 模型不包含已删除字段。
6. `0009` upgrade/downgrade 和全新迁移链通过，`alembic check` 无漂移。
7. Workspace Recall、专家模板 Recall、Ruff、Pyright/Pylance 和全量 pytest 全部通过。

## 8. 非目标

1. 不改变 `workspace_id`、`expert_profile`、`layer` 或 `cloud` 的含义。
2. 不引入已有项目模式、目录扫描、SQLite 或客户端能力。
3. 不重新生成或清理已有聊天验收数据。
4. 不修改历史迁移和历史 Trace 内容。
